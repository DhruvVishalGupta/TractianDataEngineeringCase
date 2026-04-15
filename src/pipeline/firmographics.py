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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
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


def fetch_wikipedia_data(company_name: str, website: str) -> dict:
    """
    Fetch firmographic data from Wikipedia's infobox.
    Uses the Wikipedia API to search, then scrapes the infobox.
    """
    result: dict = {"source": "wikipedia", "found": False}

    # Wikipedia REST API search
    search_url = (
        f"https://en.wikipedia.org/w/api.php"
        f"?action=opensearch&search={requests.utils.quote(company_name)}"
        f"&limit=3&namespace=0&format=json"
    )
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return result
        search_data = r.json()
        titles = search_data[1] if len(search_data) > 1 else []
        if not titles:
            return result

        # Use the first result
        title = titles[0]
        page_url = f"https://en.wikipedia.org/wiki/{requests.utils.quote(title.replace(' ', '_'))}"
        html = _fetch(page_url)
        if not html:
            return result

        text = _strip_html(html)
        result["found"] = True
        result["source_url"] = page_url
        result["raw_text"] = text[:5000]

        # Extract revenue
        rev_data = _extract_revenue_from_infobox(html)
        result.update(rev_data)

        # Extract employees
        emp_data = _extract_employees_from_infobox(html)
        result.update(emp_data)

        # Extract industry
        ind = _extract_industry_from_infobox(html)
        if ind:
            result["industry"] = ind
            result["industry_text"] = ind

        # Extract HQ
        hq = _extract_hq_from_infobox(html)
        if hq:
            result["headquarters"] = hq

        # Extract description (first paragraph)
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
            # Parse the number
            nums = re.findall(r'[\d,]+\.?\d*', rev_text)
            if nums:
                val = _parse_number(nums[0])
                if val:
                    # Normalize to billions
                    if "million" in rev_text.lower() or "M" in rev_text:
                        val = val / 1000
                    if 0.001 <= val <= 10000:
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
        r'([\d,]+)\s+employees?',
    ]

    for pattern in emp_patterns:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            emp_text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            nums = re.findall(r'[\d,]+', emp_text)
            if nums:
                val = _parse_number(nums[0])
                if val and 10 <= val <= 5_000_000:
                    result["employee_count"] = int(val)
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
            hq_text = wiki["headquarters"]
            parts = [p.strip() for p in hq_text.split(",")]
            if len(parts) >= 2:
                firmographic.headquarters_city = parts[0]
                firmographic.headquarters_country = parts[-1]
            elif len(parts) == 1:
                firmographic.headquarters_city = parts[0]

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
