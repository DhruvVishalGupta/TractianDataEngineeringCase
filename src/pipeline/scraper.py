"""
Web scraper module — uses Firecrawl MCP for primary scraping,
Playwright as fallback for JS-rendered pages.

Since we're running in the Claude environment, Firecrawl/Playwright are
available as MCP tools. This module prepares scrape jobs and processes results.
For standalone pipeline execution, it uses direct HTTP requests as fallback.
"""
from __future__ import annotations
import re
import time
import requests
from urllib.parse import urljoin, urlparse
from typing import Optional
from .config import LOCATION_URL_KEYWORDS
from .logger import get_logger, log_failure
from .raw_store import save_raw, load_raw, has_raw

log = get_logger("scraper")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
REQUEST_TIMEOUT = 30


def get_base_url(website: str) -> str:
    if not website.startswith("http"):
        return f"https://{website}"
    return website


def discover_location_urls(homepage_html: str, base_url: str) -> list[str]:
    """Find URLs likely to contain location/facility data."""
    found = set()
    # Extract all hrefs
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', homepage_html, re.IGNORECASE)

    for href in hrefs:
        href_lower = href.lower()
        if any(kw in href_lower for kw in LOCATION_URL_KEYWORDS):
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            # Only same domain
            base_parsed = urlparse(base_url)
            if parsed.netloc == base_parsed.netloc or base_parsed.netloc in parsed.netloc:
                found.add(full_url)

    return list(found)[:20]  # Cap at 20 to avoid crawling entire site


def fetch_page(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[str]:
    """Fetch a page with basic error handling."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        log.debug(f"HTTP {resp.status_code} for {url}")
        return None
    except requests.exceptions.SSLError:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout,
                              allow_redirects=True, verify=False)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            log.debug(f"SSL fallback failed for {url}: {e}")
    except requests.exceptions.Timeout:
        log.debug(f"Timeout fetching {url}")
    except Exception as e:
        log.debug(f"Error fetching {url}: {e}")
    return None


def extract_text_from_html(html: str) -> str:
    """Strip HTML tags and extract clean text."""
    # Remove scripts and styles
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fetch_sitemap_urls(base_url: str) -> list[str]:
    """Try to extract location URLs from sitemap.xml."""
    sitemap_urls_to_try = [
        f"{base_url}/sitemap.xml",
        f"{base_url}/sitemap_index.xml",
        f"{base_url}/sitemap/sitemap.xml",
    ]
    location_urls = []
    for sitemap_url in sitemap_urls_to_try:
        content = fetch_page(sitemap_url)
        if not content:
            continue
        # Extract all <loc> entries
        locs = re.findall(r'<loc>([^<]+)</loc>', content)
        for loc in locs:
            if any(kw in loc.lower() for kw in LOCATION_URL_KEYWORDS):
                location_urls.append(loc.strip())
        if location_urls:
            log.debug(f"Found {len(location_urls)} location URLs in sitemap: {sitemap_url}")
            break

    return location_urls[:15]


def scrape_company(company_name: str, website: str, force_refresh: bool = False) -> dict:
    """
    Main scraping function for a company.
    1. Fetch homepage
    2. Discover location pages via URL patterns + sitemap
    3. Fetch all discovered pages
    4. Extract text content
    Returns dict with all scraped content, cached to disk.
    """
    cache_key = "scraped_pages"
    if not force_refresh and has_raw(company_name, cache_key):
        log.info(f"[{company_name}] Using cached scraped pages")
        return load_raw(company_name, cache_key)

    base_url = get_base_url(website)
    log.info(f"[{company_name}] Scraping {base_url}...")

    result = {
        "company_name": company_name,
        "website": website,
        "base_url": base_url,
        "pages": [],
        "location_text": [],
        "total_pages_scraped": 0,
    }

    # 1. Homepage
    homepage_html = fetch_page(base_url)
    if not homepage_html:
        # Try www prefix
        if not website.startswith("www"):
            homepage_html = fetch_page(f"https://www.{website}")
        if not homepage_html:
            log.warning(f"[{company_name}] Could not fetch homepage")
            save_raw(company_name, cache_key, result)
            return result

    homepage_text = extract_text_from_html(homepage_html)
    result["pages"].append({
        "url": base_url,
        "type": "homepage",
        "text": homepage_text[:10000],
    })

    # 2. Discover location pages
    location_urls = discover_location_urls(homepage_html, base_url)
    sitemap_urls = fetch_sitemap_urls(base_url)

    all_urls = list(set(location_urls + sitemap_urls))
    log.info(f"[{company_name}] Discovered {len(all_urls)} potential location pages")

    # 3. Fetch discovered pages
    for url in all_urls[:15]:
        try:
            page_html = fetch_page(url)
            if page_html:
                page_text = extract_text_from_html(page_html)
                result["pages"].append({
                    "url": url,
                    "type": "location_page",
                    "text": page_text[:15000],
                })
                time.sleep(0.3)  # Polite crawling
        except Exception as e:
            log.debug(f"[{company_name}] Failed to fetch {url}: {e}")

    result["total_pages_scraped"] = len(result["pages"])

    # 4. Combine all text for location extraction
    combined_text = " ".join(p["text"] for p in result["pages"])
    result["combined_text"] = combined_text[:50000]

    log.info(f"[{company_name}] Scraped {result['total_pages_scraped']} pages")
    save_raw(company_name, cache_key, result)
    return result


def extract_location_candidates_from_scraped(
    scraped: dict,
    company_name: str,
) -> list[dict]:
    """
    Extract candidate location strings from scraped page content.
    Returns list of RawLocation-like dicts.
    """
    candidates = []
    seen = set()

    address_patterns = [
        # US address: 123 Main St, City, ST 12345
        r'\d+\s+[A-Z][a-zA-Z0-9\s\.]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Blvd|Boulevard|Way|Lane|Ln|Pkwy|Parkway)[,\s]+[A-Z][a-zA-Z\s]+,\s*[A-Z]{2}\s*\d{5}',
        # City, State/Country lines
        r'\b([A-Z][a-zA-Z\s]{2,25}),\s*([A-Z][a-zA-Z\s]{2,20})\s*(?:\d{5})?',
        # "Located in X" / "Plant in X" / "Facility in X"
        r'(?:located|plant|facility|operations|site|mill|refinery|mine|brewery|factory|office|headquarters?)\s+(?:in|at|near)\s+([A-Z][a-zA-Z\s,]{3,50}?)(?:\.|,|\s{2})',
        # Explicit facility names with locations
        r'([A-Z][a-zA-Z\s]+(?:Plant|Mill|Refinery|Mine|Facility|Center|Complex|Works|Brewery|Factory))[,\s]+(?:in\s+)?([A-Z][a-zA-Z\s,]+?)(?:\.|,|\s{2})',
    ]

    for page in scraped.get("pages", []):
        text = page.get("text", "")
        url = page.get("url", scraped.get("base_url", ""))

        for pattern in address_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    raw = ", ".join(str(m).strip() for m in match if m.strip())
                else:
                    raw = str(match).strip()

                # Basic quality filters
                if len(raw) < 5 or len(raw) > 200:
                    continue
                if raw.lower() in seen:
                    continue
                # Filter months, days, generic words
                skip_words = ["january", "february", "march", "april", "june", "july",
                              "august", "september", "october", "november", "december",
                              "monday", "tuesday", "copyright", "privacy", "terms"]
                if any(sw in raw.lower() for sw in skip_words):
                    continue

                seen.add(raw.lower())
                candidates.append({
                    "raw_text": raw,
                    "source_url": url,
                    "source_type": "WEBSITE",
                    "company_name": company_name,
                })

    log.debug(f"[{company_name}] Extracted {len(candidates)} location candidates from scraping")
    return candidates
