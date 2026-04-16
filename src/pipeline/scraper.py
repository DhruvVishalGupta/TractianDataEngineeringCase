"""
Web scraper module utilizing Firecrawl REST API for dynamic JS-rendered extraction.
Uses requests directly (the Firecrawl SDK depends on httpx which hangs on some Windows setups).
Returns highly structured Markdown of target URLs.
"""
import time
import requests
from .logger import get_logger
from .raw_store import save_raw, load_raw, has_raw
from .config import FIRECRAWL_API_KEY

log = get_logger("scraper")

FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"


def _firecrawl_scrape(url: str) -> str:
    """Scrape a single URL via the Firecrawl REST API. Returns markdown or empty string."""
    if not FIRECRAWL_API_KEY:
        log.error("FIRECRAWL_API_KEY is missing.")
        return ""
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {"url": url, "formats": ["markdown"]}
    try:
        resp = requests.post(FIRECRAWL_URL, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            return data.get("data", {}).get("markdown", "")
        log.warning(f"Firecrawl returned success=false for {url}")
        return ""
    except Exception as e:
        log.warning(f"Firecrawl REST failed for {url}: {e}")
        return ""


def _filter_off_topic_pages(
    company_name: str, pages: list[dict], website: str = ""
) -> list[dict]:
    """Remove scraped pages that don't mention the target company at all."""
    company_lower = company_name.lower()
    first_word = company_lower.split()[0] if company_lower.split() else ""
    company_domain = website.lower().replace("www.", "") if website else ""

    filtered = []
    for page in pages:
        md_lower = (page.get("markdown") or "").lower()
        url_lower = (page.get("url") or "").lower()
        try:
            domain = url_lower.split("/")[2]
        except IndexError:
            domain = ""

        on_company_site = company_domain and company_domain in domain
        mentions_company = (
            company_lower in md_lower
            or (len(first_word) >= 4 and first_word in md_lower)
        )

        if on_company_site or mentions_company:
            filtered.append(page)
        else:
            log.debug(
                f"[{company_name}] FILTERED OUT off-topic page: {page.get('url', '?')} "
                f"(no mention of '{company_lower}' in {len(page.get('markdown', ''))} chars)"
            )

    if len(filtered) < len(pages):
        log.info(
            f"[{company_name}] Removed {len(pages) - len(filtered)} off-topic pages "
            f"({len(filtered)} relevant pages remain)"
        )
    return filtered


def scrape_urls(
    company_name: str, urls: list[str], website: str = ""
) -> list[dict]:
    """Scrape specific URLs using Firecrawl to fetch hydrated markdown."""
    cache_key = "firecrawl_markdown"
    if has_raw(company_name, cache_key):
        log.info(f"[{company_name}] Loaded cached Firecrawl data")
        return load_raw(company_name, cache_key)

    results = []
    log.info(f"[{company_name}] Initiating Firecrawl extraction for {len(urls)} target pages...")

    for url in urls[:8]:
        log.debug(f"[{company_name}] Firecrawling {url}...")
        md_text = _firecrawl_scrape(url)
        if md_text:
            results.append({"url": url, "markdown": md_text})
        time.sleep(1)

    filtered = _filter_off_topic_pages(company_name, results, website)
    save_raw(company_name, cache_key, filtered)
    return filtered


def scrape_company_domain(company_name: str, website: str) -> list[dict]:
    """
    Basic fallback to scrape the main contact/about domain if deep links fail.
    """
    urls = [
        f"https://{website}/contact",
        f"https://{website}/about-us",
        f"https://{website}/locations",
    ]
    return scrape_urls(company_name, urls)
