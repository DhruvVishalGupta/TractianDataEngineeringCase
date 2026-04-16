"""
Firmographics module — discovers revenue, employee count, industry, and HQ
from live public sources: Wikipedia, Macrotrends, Craft.co, company website.

No hardcoded per-company values. All data discovered at runtime.
"""
from __future__ import annotations
import re
import time
import requests
from typing import Optional
from .schema import FirmographicData
from .searcher import extract_firmographics_from_text
from .raw_store import save_raw, load_raw, has_raw
from .logger import get_logger, log_failure

log = get_logger("firmographics")

HEADERS = {
    "User-Agent": "TractianLeadGen/1.0 (https://github.com/tractian; pipeline@tractian.com)",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}
WIKI_API_HEADERS = {
    "User-Agent": "TractianLeadGen/1.0 (https://github.com/tractian; pipeline@tractian.com)",
    "Accept": "application/json",
}
TIMEOUT = 20


def _fetch(url: str) -> Optional[str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        log.debug(f"Fetch failed for {url}: {e}")
    return None


def _strip_html(html: str) -> str:
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', text).strip()


def _parse_number(s: str) -> Optional[float]:
    """Parse a numeric string like '155,000' or '177.3' to float."""
    try:
        return float(s.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


_US_STATE_NAMES = {
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "minnesota","mississippi","missouri","montana","nebraska","nevada","new hampshire",
    "new jersey","new mexico","new york","north carolina","north dakota","ohio",
    "oklahoma","oregon","pennsylvania","rhode island","south carolina","south dakota",
    "tennessee","texas","utah","vermont","virginia","washington","west virginia",
    "wisconsin","wyoming","district of columbia",
}
_US_STATE_ABBREV = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS",
    "KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY",
    "NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV",
    "WI","WY","DC",
}
_COUNTRY_NORMALIZATION = {
    "u.s.": "United States", "us": "United States", "usa": "United States",
    "u.s.a.": "United States", "u.s": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "great britain": "United Kingdom",
}
_KNOWN_COUNTRIES = {
    "united states","united kingdom","canada","mexico","brazil","china","india",
    "germany","france","japan","australia","south korea","italy","spain","netherlands",
    "switzerland","sweden","norway","denmark","finland","belgium","austria","ireland",
    "singapore","luxembourg","poland","czech republic","hungary","portugal","greece",
    "romania","turkey","russia","saudi arabia","uae","united arab emirates",
    "egypt","nigeria","kenya","new zealand","philippines","vietnam","taiwan","israel",
    "argentina","colombia","chile","peru","south africa","indonesia","malaysia","thailand",
}


_REGION_BLACKLIST = {
    "north america", "south america", "latin america", "central america",
    "asia pacific", "asia-pacific", "apac", "emea", "europe",
    "middle east", "africa", "oceania", "global", "worldwide",
    "international",
}


def _try_recover_hq_from_text(company_name: str, firmographic, text: str) -> None:
    """
    Scan a free-text blob for HQ phrasing. Populates firmographic.headquarters_*
    in place. Runs only when Wikipedia infobox parsing already failed.
    Rejects regional words ("North America") and prefers US-resident HQs for
    dual-HQ companies like Stripe.
    """
    if not text:
        return
    patterns = [
        # "headquartered in San Francisco, California"
        r"\b(?:headquartered|head[- ]?quartered|global\s+headquarters|head\s+office|headquarters)\s+"
        r"(?:is\s+|are\s+)?(?:located\s+)?(?:in|at)\s+"
        r"([A-Z][a-zA-Z\.\s\-']{2,35}?)(?:,\s*([A-Z][a-zA-Z\s]{2,35}?))?"
        r"(?:\.|,|;|\s+is\b|\s+and\b|\s+with\b|\s+where\b|$)",
        # "based in Springdale, Arkansas"
        r"\b(?:based|headquartered)\s+(?:in|at)\s+"
        r"([A-Z][a-zA-Z\.\s\-']{2,35}?)(?:,\s*([A-Z][a-zA-Z\s]{2,35}?))?"
        r"(?:\.|,|;|\s+is\b|\s+and\b|\s+with\b|\s+where\b|$)",
        # Forbes/Crunchbase-style "Headquarters · San Francisco, California" (with bullet,
        # bullet point, hyphen, pipe, colon as separator). Decoded HTML entity bullets
        # often render as "·" / "•" / "▪" or get stripped to a literal symbol.
        r"\bHeadquarters\b\s*[·•▪|:\-–—]\s*"
        r"([A-Z][a-zA-Z\.\s\-']{2,35}?)(?:[,·•▪]\s*([A-Z][a-zA-Z\s]{2,35}?))?"
        r"(?:[·•▪|]|\s+(?:Country|Founded|Industry|Type|CEO|Chief|Revenue)\b|$)",
    ]
    for pat in patterns:
        # Try EVERY match in text; pick the first that yields a non-region city.
        # Prefer US matches when present (handles Stripe's "Dublin, Ireland; San Francisco, California").
        candidates: list[tuple[str, Optional[str]]] = []
        for m in re.finditer(pat, text):
            raw = f"{m.group(1).strip()}, {(m.group(2) or '').strip()}".strip(", ")
            city, country = _parse_hq(raw)
            if not city:
                continue
            if city.lower() in _REGION_BLACKLIST:
                continue
            candidates.append((city, country))
        if not candidates:
            continue
        # Prefer US over non-US for dual-HQ companies; otherwise first match.
        chosen = next(
            (c for c in candidates if c[1] and c[1].lower() == "united states"),
            candidates[0],
        )
        firmographic.headquarters_city = chosen[0]
        if chosen[1] and not firmographic.headquarters_country:
            firmographic.headquarters_country = chosen[1]
        log.info(f"[{company_name}] HQ recovered from text: {chosen}")
        return


def _parse_hq(raw_hq: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse a Wikipedia headquarters field into (city, country).

    Handles: "Chicago, Illinois, U.S." → (Chicago, United States)
             "Salesforce TowerSan Francisco, California, U.S." → (San Francisco, United States)
             "Chicago, Illinois & Pittsburgh, Pennsylvania, U.S." → (Chicago, United States)
             "300 Park Avenue, New York City, U.S." → (New York City, United States)
    """
    if not raw_hq:
        return None, None
    raw = raw_hq.strip().rstrip(",;")

    # If multiple HQs are listed (& / ;), keep the first.
    raw = re.split(r"\s*(?:&|/|;|\sand\s)\s*", raw, maxsplit=1)[0].strip()

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None, None

    # Normalize country candidate
    country: Optional[str] = None
    last = parts[-1].lower().strip(".")
    if last in _COUNTRY_NORMALIZATION:
        country = _COUNTRY_NORMALIZATION[last]
        parts = parts[:-1]
    elif last in _KNOWN_COUNTRIES:
        country = parts[-1].title()
        parts = parts[:-1]

    # Strip US states (we already captured country)
    if parts and (parts[-1].lower() in _US_STATE_NAMES or parts[-1].upper() in _US_STATE_ABBREV):
        if not country:
            country = "United States"
        parts = parts[:-1]

    if not parts:
        return None, country

    # The "city" candidate is the last remaining part. But beware addresses like
    # "Salesforce TowerSan Francisco" or "300 Park Avenue, New York City".
    city = parts[-1]

    # Strip building/street prefixes by detecting concatenated CamelCase
    # ("TowerSan Francisco" → "San Francisco")
    m = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)$", city)
    if m and len(m.group(1)) >= 4:
        city = m.group(1)

    # Drop obvious street-address tokens ("300 Park Avenue") in favor of next part if present
    if re.search(r"\d", city) and len(parts) >= 2:
        city = parts[-2]

    city = re.sub(r"\s+", " ", city).strip()
    if not city or len(city) > 50 or re.search(r"\d", city):
        city = None

    return city, country


def _clean_wiki_text(raw: str) -> str:
    """Strip residual wikitext template noise for display-friendly text."""
    s = re.sub(r'\{\{[^}]*\}\}', '', raw)
    s = re.sub(r'\[\[([^\]|]+\|)?([^\]]+)\]\]', r'\2', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'\|[a-z_]+=\S*', '', s)
    s = s.replace('}}', '').replace('{{', '')
    s = re.sub(r'\s+', ' ', s).strip().strip('|').strip()
    return s[:80] if s else raw[:80]


def fetch_wikipedia_data(company_name: str, website: str) -> dict:
    """
    Fetch firmographic data from Wikipedia using the parse API (wikitext).
    This is more reliable than HTML scraping because infobox fields are structured.
    Falls back to HTML scraping for description text.
    """
    result: dict = {"source": "wikipedia", "found": False}

    try:
        # Search for the page
        search_url = (
            f"https://en.wikipedia.org/w/api.php"
            f"?action=opensearch&search={requests.utils.quote(company_name)}"
            f"&limit=5&namespace=0&format=json"
        )
        r = requests.get(search_url, headers=WIKI_API_HEADERS, timeout=15)
        if r.status_code != 200:
            return result
        search_data = r.json()
        titles = search_data[1] if len(search_data) > 1 else []
        if not titles:
            return result

        # Pick best title: prefer those with corporate suffixes or exact company name
        name_lower = company_name.lower()
        corp_suffixes = ("inc.", "inc", "corp", "company", "group", "ltd", "plc", "s.a.", "n.v.")
        title = titles[0]  # default
        for t in titles:
            t_lower = t.lower()
            if name_lower in t_lower and any(s in t_lower for s in corp_suffixes):
                title = t
                break

        if not title:
            return result
        page_url = f"https://en.wikipedia.org/wiki/{requests.utils.quote(title.replace(' ', '_'))}"
        result["found"] = True
        result["source_url"] = page_url

        # Get structured wikitext via parse API
        parse_url = (
            f"https://en.wikipedia.org/w/api.php"
            f"?action=parse&page={requests.utils.quote(title)}"
            f"&prop=wikitext&format=json"
        )
        r = requests.get(parse_url, headers=WIKI_API_HEADERS, timeout=15)
        wikitext = ""
        if r.status_code == 200:
            wikitext = r.json().get("parse", {}).get("wikitext", {}).get("*", "")

        if wikitext:
            infobox_fields = _extract_wikitext_fields(wikitext)

            # Employees
            emp_raw = infobox_fields.get("num_employees") or infobox_fields.get("employees") or infobox_fields.get("number_of_employees") or ""
            emp_nums = re.findall(r'[\d,]+', emp_raw)
            for n in emp_nums:
                val = _parse_number(n)
                if val and 1900 <= val <= 2030:
                    continue
                if val and 100 <= val <= 5_000_000:
                    result["employee_count"] = int(val)
                    result["employee_text"] = _clean_wiki_text(emp_raw)
                    break

            # Revenue: try to parse from raw wikitext (before template stripping)
            rev_field = ""
            for field in ["revenue", "net_income", "net_revenue"]:
                m = re.search(rf'\|\s*{field}\s*=\s*(.+?)(?:\n\||\n\}})', wikitext, re.IGNORECASE)
                if m:
                    rev_field = m.group(1).strip()
                    break
            if rev_field:
                rev_data = _parse_revenue_from_wikitext(rev_field)
                if "revenue_text" in rev_data:
                    rev_data["revenue_text"] = _clean_wiki_text(rev_data["revenue_text"])
                result.update(rev_data)

            # Industry
            ind = infobox_fields.get("industry", "")
            if ind and 3 < len(ind) < 200:
                result["industry"] = ind
                result["industry_text"] = ind

            # HQ
            hq = infobox_fields.get("hq_location") or infobox_fields.get("headquarters") or infobox_fields.get("hq_location_city") or ""
            if hq and 2 < len(hq) < 100:
                result["headquarters"] = hq

        # Fetch HTML for description only
        html = _fetch(page_url)
        if html:
            result["raw_text"] = _strip_html(html)[:5000]
            desc_match = re.search(
                r'<p[^>]*>([^<]{100,}(?:<[^/][^>]*>[^<]*</[^>]+>)*[^<]*)</p>',
                html[:20000]
            )
            if desc_match:
                desc = re.sub(r'<[^>]+>', '', desc_match.group(1))
                result["description"] = re.sub(r'\s+', ' ', desc).strip()[:500]

    except Exception as e:
        log.debug(f"Wikipedia fetch failed for {company_name}: {e}")

    return result


def _extract_wikitext_fields(wikitext: str) -> dict:
    """Extract clean field values from wikitext infobox."""
    fields = {}
    target_fields = [
        "num_employees", "employees", "number_of_employees",
        "revenue", "industry", "headquarters",
        "hq_location_city", "hq_location",
    ]
    for field in target_fields:
        m = re.search(rf'\|\s*{field}\s*=\s*(.+?)(?:\n\||\n\}})', wikitext, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.sub(r'<[^>]+>', '', val)
            # Unwrap wiki links [[Display|Text]] → Text, [[Text]] → Text
            val = re.sub(r'\[\[([^\]|]+\|)?([^\]]+)\]\]', r'\2', val)
            # For templates like {{ubl|A|B|C}}, keep A, B, C as text
            val = re.sub(r'\{\{(?:ubl|hlist|unbulleted list|plainlist|flatlist)[|]', '', val, flags=re.IGNORECASE)
            # Remove remaining templates but keep their parameters as text
            val = re.sub(r'\{\{[^|}]+\|([^}]*)\}\}', r'\1', val)
            val = re.sub(r'\{\{[^}]*\}\}', '', val)
            val = val.replace('}}', '').replace('{{', '')
            val = re.sub(r'\s+', ' ', val).strip().strip('|').strip()
            if val:
                fields[field] = val
    return fields


def _parse_revenue_from_wikitext(raw_field: str) -> dict:
    """Parse revenue from raw wikitext field (before template stripping)."""
    result = {}
    lower = raw_field.lower()
    nums = re.findall(r'[\d,]+\.?\d*', raw_field)
    has_billion = "billion" in lower or "|b" in lower or "{{decrease}}" in lower or "{{increase}}" in lower
    has_million = "million" in lower or "|m" in lower

    for n in nums:
        val = _parse_number(n)
        if val is None:
            continue
        if 1900 <= val <= 2030:
            continue
        if has_million:
            val = val / 1000
        if 0.01 <= val <= 2000:
            result["revenue_usd"] = val
            clean = re.sub(r'\{\{[^}]*\}\}', '', raw_field).strip()
            clean = re.sub(r'<[^>]+>', '', clean).strip()
            result["revenue_text"] = clean[:50]
            return result
    return result


def _extract_revenue_from_infobox(html: str) -> dict:
    """Extract revenue from Wikipedia infobox HTML."""
    result: dict = {}

    # Look for revenue in infobox table
    revenue_patterns = [
        r'(?:revenue|net\s+revenue|net\s+sales)[^<]*?</th>[^<]*?<td[^>]*>([^<]+)',
        r'revenue[^"]*">\s*(?:US\$|USD|\$)\s*([\d,\.]+)\s*(?:billion|B|million|M)',
        r'\brevenue\b[^>]*>([^<]+billion[^<]+)',
    ]

    for pattern in revenue_patterns:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            rev_text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            rev_lower = rev_text.lower()
            has_scale = any(s in rev_lower for s in ("billion", "million", " b ", " m "))
            nums = re.findall(r'[\d,]+\.?\d*', rev_text)
            if nums:
                val = _parse_number(nums[0])
                if val:
                    # Skip year-like values (1900-2030) unless explicitly has billion/million
                    if 1900 <= val <= 2030 and not has_scale:
                        continue
                    if "million" in rev_lower:
                        val = val / 1000
                    if 0.001 <= val <= 2000:
                        result["revenue_usd"] = val
                        result["revenue_text"] = rev_text[:50]
                        return result

    # Fallback: search full text for revenue mentions
    text = _strip_html(html[:10000])
    firmographic = extract_firmographics_from_text(text)
    result.update(firmographic)
    return result


def _extract_employees_from_infobox(html: str) -> dict:
    """Extract employee count from Wikipedia infobox HTML."""
    result: dict = {}

    emp_patterns = [
        r'(?:employees?|headcount|workforce)[^<]*?</th>[^<]*?<td[^>]*>([^<]+)',
        r'employees?[^>]*>([^<]*(?:[\d,]+)[^<]*(?:employees?|people|workers)?)',
    ]

    for pattern in emp_patterns:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            emp_text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            nums = re.findall(r'[\d,]+', emp_text)
            # Pick the largest number that looks like an employee count (skip years)
            best = None
            for n in nums:
                val = _parse_number(n)
                if val and 1900 <= val <= 2030:
                    continue  # Skip year-like values
                if val and 100 <= val <= 5_000_000:
                    if best is None or val > best:
                        best = val
            if best:
                result["employee_count"] = int(best)
                result["employee_text"] = emp_text[:50]
                return result

    return result


def _extract_industry_from_infobox(html: str) -> Optional[str]:
    """Extract industry field from Wikipedia infobox."""
    patterns = [
        r'(?:industry|sector)[^<]*?</th>[^<]*?<td[^>]*>(.*?)</td>',
        r'"industry"[^>]*>(.*?)</(?:td|div|span)>',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', ' ', m.group(1)).strip()
            text = re.sub(r'\s+', ' ', text).strip()
            if 3 < len(text) < 200:
                return text
    return None


def _extract_hq_from_infobox(html: str) -> Optional[str]:
    """Extract headquarters location from Wikipedia infobox."""
    patterns = [
        r'(?:headquarters?|hq|head\s+office)[^<]*?</th>[^<]*?<td[^>]*>(.*?)</td>',
        r'"headquarters"[^>]*>(.*?)</(?:td|div|span)>',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            text = re.sub(r'<[^>]+>', ' ', m.group(1)).strip()
            text = re.sub(r'\s+', ' ', text).strip()
            if 2 < len(text) < 100:
                return text
    return None


def discover_firmographics(
    company_name: str,
    website: str,
    is_public: bool,
    search_snippets: list[dict] | None = None,
    force_refresh: bool = False,
) -> FirmographicData:
    """
    Discover firmographic data for a company from multiple live sources.
    Priority: Wikipedia → search snippets → company website about page.
    Returns FirmographicData with whatever was found.
    """
    cache_key = "firmographics"
    if not force_refresh and has_raw(company_name, cache_key):
        log.info(f"[{company_name}] Using cached firmographics")
        cached = load_raw(company_name, cache_key)
        return FirmographicData(**cached)

    log.info(f"[{company_name}] Discovering firmographics...")

    firmographic = FirmographicData(
        company_name=company_name,
        website=website,
        is_public=is_public,
    )
    sources_used = []
    industry_text_parts = []

    # 1. Wikipedia
    wiki = fetch_wikipedia_data(company_name, website)
    if wiki.get("found"):
        sources_used.append(wiki.get("source_url", "https://en.wikipedia.org"))

        if wiki.get("revenue_usd") and firmographic.revenue_usd is None:
            firmographic.revenue_usd = wiki["revenue_usd"]
            firmographic.revenue_text = wiki.get("revenue_text")

        if wiki.get("employee_count") and firmographic.employee_count is None:
            firmographic.employee_count = wiki["employee_count"]
            firmographic.employee_text = wiki.get("employee_text")

        if wiki.get("industry"):
            if not firmographic.industry:
                firmographic.industry = wiki["industry"]
            industry_text_parts.append(wiki["industry"])

        if wiki.get("description"):
            industry_text_parts.append(wiki["description"])

        if wiki.get("headquarters"):
            city, country = _parse_hq(wiki["headquarters"])
            if city:
                firmographic.headquarters_city = city
            if country:
                firmographic.headquarters_country = country

        log.info(f"[{company_name}] Wikipedia: employees={firmographic.employee_count}, revenue=${firmographic.revenue_usd}B")

    # 2. Extract from search snippets
    if search_snippets:
        snippet_text = " ".join(
            f"{s.get('title', '')} {s.get('description', '')}"
            for s in search_snippets
        )
        snippet_data = extract_firmographics_from_text(snippet_text)

        if snippet_data.get("revenue_usd") and firmographic.revenue_usd is None:
            firmographic.revenue_usd = snippet_data["revenue_usd"]
            firmographic.revenue_text = snippet_data.get("revenue_text")

        if snippet_data.get("employee_count") and firmographic.employee_count is None:
            firmographic.employee_count = snippet_data["employee_count"]
            firmographic.employee_text = snippet_data.get("employee_text")

        # HQ fallback from snippet phrasing like "headquartered in San Francisco" or
        # "based in Dublin, Ireland". Only used when Wikipedia parsing failed entirely.
        if not firmographic.headquarters_city:
            _try_recover_hq_from_text(company_name, firmographic, snippet_text)

        industry_text_parts.append(snippet_text[:1000])

    # 3. Try company website /about page
    base_url = f"https://{website}" if not website.startswith("http") else website
    about_urls = [
        f"{base_url}/about",
        f"{base_url}/about-us",
        f"{base_url}/company",
        f"{base_url}/who-we-are",
    ]
    for url in about_urls:
        try:
            html = _fetch(url)
            if html:
                text = _strip_html(html)[:3000]
                about_data = extract_firmographics_from_text(text)
                if about_data.get("revenue_usd") and firmographic.revenue_usd is None:
                    firmographic.revenue_usd = about_data["revenue_usd"]
                    firmographic.revenue_text = about_data.get("revenue_text")
                if about_data.get("employee_count") and firmographic.employee_count is None:
                    firmographic.employee_count = about_data["employee_count"]
                    firmographic.employee_text = about_data.get("employee_text")
                industry_text_parts.append(text[:500])
                sources_used.append(url)
                break
        except Exception:
            pass
        time.sleep(0.2)

    # Final HQ recovery pass across the combined blob (catches cases where Wikipedia
    # infobox parse missed and snippets alone didn't contain HQ phrasing, but the
    # longer Wikipedia description does — e.g. "Tyson Foods is headquartered in Springdale, Arkansas").
    if not firmographic.headquarters_city:
        combined_blob = " ".join(industry_text_parts)
        _try_recover_hq_from_text(company_name, firmographic, combined_blob)

    firmographic.industry_keywords = industry_text_parts
    firmographic.data_sources = sources_used
    firmographic.has_sec_data = is_public  # Will be confirmed by edgar module

    log.info(
        f"[{company_name}] Firmographics complete: "
        f"employees={firmographic.employee_count}, "
        f"revenue=${firmographic.revenue_usd}B, "
        f"industry={firmographic.industry}"
    )

    # Cache as dict
    save_raw(company_name, cache_key, firmographic.model_dump())
    return firmographic
