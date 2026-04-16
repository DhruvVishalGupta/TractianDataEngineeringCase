"""
Searcher module using Brave Search API.
Discovers facility pages, press releases, and SEC filings.
"""
import re
import requests
import hashlib
from urllib.parse import urlparse
from .logger import get_logger
from .raw_store import save_raw, load_raw, has_raw
from .config import BRAVE_API_KEY

log = get_logger("searcher")


def extract_firmographics_from_text(text: str) -> dict:
    """
    Lightweight parser for firmographic snippets.
    Returns a best-effort dict with revenue_usd (billions), employee_count, and text evidence.
    """
    if not text:
        return {}

    result: dict = {}
    clean = " ".join(str(text).split())

    # Revenue: examples "$55 billion", "USD 12.3B", "revenue 900 million"
    rev_match = re.search(
        r"(?:revenue|sales)[^$0-9]{0,40}(?:US\$|USD|\$)?\s*([\d,]+(?:\.\d+)?)\s*(billion|bn|b|million|mn|m)",
        clean,
        re.IGNORECASE,
    )
    if rev_match:
        value = float(rev_match.group(1).replace(",", ""))
        unit = rev_match.group(2).lower()
        revenue_b = value if unit in {"billion", "bn", "b"} else (value / 1000.0)
        if 0.001 <= revenue_b <= 10000:
            result["revenue_usd"] = round(revenue_b, 3)
            result["revenue_text"] = rev_match.group(0)[:80]

    # Employees: examples "37,000 employees", "employee count 12000"
    emp_match = re.search(
        r"(?:employees?|employee count|workforce|headcount)[^0-9]{0,20}([\d,]{2,9})",
        clean,
        re.IGNORECASE,
    )
    if not emp_match:
        emp_match = re.search(r"\b([\d,]{2,9})\s+employees?\b", clean, re.IGNORECASE)
    if emp_match:
        employees = int(emp_match.group(1).replace(",", ""))
        if 10 <= employees <= 5_000_000:
            result["employee_count"] = employees
            result["employee_text"] = emp_match.group(0)[:80]

    return result

def execute_brave_search(query: str, count: int = 5) -> list[dict]:
    """Execute a query against the Brave Search API."""
    if not BRAVE_API_KEY:
        log.error("BRAVE_API_KEY is not set.")
        return []
    
    headers = {
        "X-Subscription-Token": BRAVE_API_KEY,
        "Accept": "application/json"
    }
    
    try:
        url = "https://api.search.brave.com/res/v1/web/search"
        params = {"q": query, "count": count}
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return results
    except Exception as e:
        log.warning(f"Brave Search failed for query '{query}': {e}")
        return []

def discover_facility_urls(company_name: str, website: str) -> list[str]:
    """
    Search for URLs highly likely to contain structured facility data,
    using targeted open source intelligence (OSINT) dorks.
    """
    cache_key = "brave_facility_urls"
    if has_raw(company_name, cache_key):
        return load_raw(company_name, cache_key)
        
    queries = [
        # On-site: deep links from the company's own website
        f'site:{website} ("manufacturing plant" OR "processing plant" OR "production facility" OR refinery OR factory)',
        f'site:{website} ("locations" OR "facilities" OR "operations" OR "where we operate")',
        f'"{company_name}" "manufacturing plant" site:{website}',
        f'"{company_name}" "processing plant" site:{website}',
        f'"{company_name}" "distribution center" site:{website}',
        # Off-site: third-party facility lists, Wikipedia, press releases
        f'"{company_name}" facilities list site:wikipedia.org',
        f'"{company_name}" "plant locations" OR "manufacturing locations" OR "facility locations"',
        f'"{company_name}" plant OR factory OR refinery OR mill filetype:html -site:{website}',
    ]
    
    found_urls = set()
    for q in queries:
        results = execute_brave_search(q, count=3)
        for r in results:
            url = r.get("url", "")
            if url and not url.endswith(".pdf"):
                found_urls.add(url)
                
    def _url_rank(u: str) -> int:
        lower = u.lower()
        rank = 0
        if any(k in lower for k in ["plant", "facility", "facilities", "operations", "locations", "manufacturing", "processing", "refinery", "site"]):
            rank += 3
        if any(k in lower for k in ["careers", "investor", "newsroom", "press", "blog", "contact"]):
            rank -= 2
        if website.lower() in lower:
            rank += 2
        return rank

    url_list = sorted(found_urls, key=_url_rank, reverse=True)
    log.info(f"[{company_name}] Discovered {len(url_list)} targeted facility URLs via Brave Search")
    save_raw(company_name, cache_key, url_list)
    return url_list

def _netloc(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _result_location_match(company_name: str, city: str, text: str) -> bool:
    """Company + city must appear in the same snippet/title/url blob."""
    text_l = text.lower()
    cn = company_name.strip().lower()
    if not cn or not city.strip():
        return False
    first = cn.split()[0] if cn.split() else ""
    company_hit = cn in text_l or (len(first) >= 4 and first in text_l)
    city_hit = city.strip().lower() in text_l
    return bool(company_hit and city_hit)


AUTHORITATIVE_DOMAINS = {
    "wikipedia.org", "sec.gov", "bloomberg.com", "reuters.com",
    "businesswire.com", "prnewswire.com", "globenewswire.com",
    "macrotrends.net", "dnb.com", "craft.co", "owler.com",
}


def _hit_score(
    company_name: str,
    city: str,
    country: str,
    state_region: str,
    source_domain: str,
    r: dict,
) -> int:
    """Single-result strength 0–8+ (used to aggregate verify strength)."""
    title = r.get("title", "") or ""
    desc = r.get("description", "") or ""
    url = r.get("url", "") or ""
    blob = f"{title} {desc} {url}".lower()
    if not _result_location_match(company_name, city, blob):
        return 0
    score = 2  # company + city together
    context_terms = (
        "plant", "facility", "manufacturing", "operations", "distribution",
        "refinery", "warehouse", "headquarters", "head office", "corporate",
        "office", "location", "site", "mill", "production",
    )
    if any(t in blob for t in context_terms):
        score += 1
    ctry = (country or "").strip().lower()
    if len(ctry) >= 3 and ctry in blob:
        score += 1
    sr = (state_region or "").strip().lower()
    if len(sr) >= 2 and sr in blob:
        score += 1
    netloc = _netloc(url)
    if source_domain and netloc and (source_domain in netloc or netloc == source_domain):
        score += 2
    if netloc and any(ad in netloc for ad in AUTHORITATIVE_DOMAINS):
        score += 1
    return score


def verify_location_strength(
    company_name: str,
    location_str: str,
    facility_type: str,
    source_url: str | None = None,
    *,
    category: str = "industrial",
    state_region: str = "",
) -> str:
    """
    Corroborate a facility via Brave Search with graded strength (not a boolean).

    Returns:
        "strong" — multiple independent mentions, or domain-aligned official hit,
                    or multiple high-quality snippets.
        "weak"   — a single plausible OSINT hit (legacy True equivalent).
        "none"   — no usable corroboration.
    """
    cache_input = (
        f"{company_name}|{location_str}|{facility_type}|{category}|{source_url or ''}|{state_region}"
    ).lower().encode("utf-8")
    cache_key = f"verify_v4_{hashlib.md5(cache_input).hexdigest()[:16]}"
    if has_raw(company_name, cache_key):
        cached = load_raw(company_name, cache_key)
        return str(cached.get("strength", "none"))

    city = location_str.split(",")[0].strip()
    tail = location_str.split(",", 1)
    country = tail[1].strip() if len(tail) > 1 else ""
    sr = (state_region or "").strip()

    source_domain = _netloc(source_url or "")
    ft = (facility_type or "").strip()

    location_with_state = f"{city}, {sr}" if sr else city

    if category == "general":
        queries = [
            f'"{company_name}" "{city}" (headquarters OR "head office" OR corporate OR campus)',
            f'"{company_name}" "{city}" office',
            f'"{company_name}" {location_str} headquarters',
        ]
    else:
        queries = [
            f'"{company_name}" "{city}" (plant OR facility OR manufacturing OR operations)',
            f'"{company_name}" {location_with_state} (plant OR facility OR factory)',
            f'"{company_name}" "{city}" "{ft}"' if ft else f'"{company_name}" "{city}" factory',
            f'"{company_name}" facilities site:wikipedia.org',
        ]

    scored_urls: dict[str, int] = {}
    max_hit = 0
    for query in queries:
        for r in execute_brave_search(query, count=5):
            url = (r.get("url") or "").strip()
            if not url:
                continue
            sc = _hit_score(company_name, city, country, sr, source_domain, r)
            if sc <= 0:
                continue
            scored_urls[url] = max(scored_urls.get(url, 0), sc)
            max_hit = max(max_hit, sc)

    good_urls = [u for u, s in scored_urls.items() if s >= 3]
    any_good = [u for u, s in scored_urls.items() if s >= 2]

    strength = "none"
    if len(good_urls) >= 2 or max_hit >= 5:
        strength = "strong"
    elif len(any_good) >= 2 or max_hit >= 4:
        strength = "strong"
    elif len(any_good) >= 1 or max_hit >= 2:
        strength = "weak"

    save_raw(
        company_name,
        cache_key,
        {
            "strength": strength,
            "location_str": location_str,
            "facility_type": facility_type,
            "category": category,
            "state_region": sr,
            "hit_urls": list(scored_urls.keys())[:12],
            "max_hit": max_hit,
        },
    )
    log.debug(
        f"[{company_name}] verify_location_strength {location_str!r} -> {strength} "
        f"(hits={len(scored_urls)}, max={max_hit})"
    )
    return strength


def get_verification_breakdown(
    company_name: str,
    location_str: str,
    facility_type: str,
    source_url: str | None = None,
    *,
    category: str = "industrial",
    state_region: str = "",
) -> dict:
    """Read the cached OSINT verification breakdown (for UI explanations)."""
    cache_input = (
        f"{company_name}|{location_str}|{facility_type}|{category}|{source_url or ''}|{state_region}"
    ).lower().encode("utf-8")
    cache_key = f"verify_v4_{hashlib.md5(cache_input).hexdigest()[:16]}"
    if has_raw(company_name, cache_key):
        return load_raw(company_name, cache_key)
    return {}


def verify_location_via_search(company_name: str, location_str: str, facility_type: str) -> bool:
    """Backward-compatible: True if any corroboration exists."""
    return verify_location_strength(company_name, location_str, facility_type) != "none"

def discover_firmographics(company_name: str) -> dict:
    """
    Extract firmographics by leveraging snippet descriptions from search engines.
    """
    cache_key = "brave_firmographics"
    if has_raw(company_name, cache_key):
        return load_raw(company_name, cache_key)

    query = f"{company_name} company employee count revenue industry Wikipedia"
    results = execute_brave_search(query, count=5)
    
    snippets = [
        {
            "title": r.get("title", ""),
            "description": r.get("description", ""),
            "url": r.get("url", ""),
        }
        for r in results
    ]
    combined_text = " | ".join(
        f"{s.get('title', '')} {s.get('description', '')}" for s in snippets
    )
    
    # We will pass this text block to Claude to extract the hard numbers.
    data = {
        "raw_search_text": combined_text,
        "snippets": snippets,
    }
    
    save_raw(company_name, cache_key, data)
    return data


def discover_market_research(company_name: str, website: str) -> dict:
    """
    Collect market-facing operational signals that indicate Tractian relevance:
    maintenance maturity, reliability programs, industrial operations, and capex/opex posture.
    """
    cache_key = "brave_market_research"
    if has_raw(company_name, cache_key):
        return load_raw(company_name, cache_key)

    queries = [
        f'"{company_name}" maintenance reliability operations',
        f'"{company_name}" predictive maintenance condition monitoring',
        f'"{company_name}" plant downtime asset performance',
        f'site:{website} maintenance reliability manufacturing operations',
    ]

    snippets: list[dict] = []
    for q in queries:
        results = execute_brave_search(q, count=4)
        for r in results:
            snippets.append(
                {
                    "title": r.get("title", ""),
                    "description": r.get("description", ""),
                    "url": r.get("url", ""),
                    "query": q,
                }
            )

    # De-duplicate by URL to reduce noise.
    seen = set()
    unique_snippets = []
    for s in snippets:
        key = s.get("url", "").strip().lower() or f"{s.get('title','')}|{s.get('description','')}"
        if key in seen:
            continue
        seen.add(key)
        unique_snippets.append(s)

    research_text = " | ".join(
        f"{s.get('title', '')} {s.get('description', '')}" for s in unique_snippets
    )
    data = {
        "market_research_text": research_text,
        "snippets": unique_snippets,
    }
    save_raw(company_name, cache_key, data)
    return data
