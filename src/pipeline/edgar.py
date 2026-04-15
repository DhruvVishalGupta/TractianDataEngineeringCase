"""
SEC EDGAR module — extracts Item 2 (Properties) from 10-K filings.
Gold standard data source for US public companies.

CIK numbers are discovered at runtime via the EDGAR company search API.
No hardcoded CIKs, no hardcoded company data.
"""
from __future__ import annotations
import re
import time
import requests
from typing import Optional
from .logger import get_logger, log_failure
from .raw_store import save_raw, load_raw, has_raw

log = get_logger("edgar")

EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
EDGAR_COMPANY_SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22{name}%22&forms=10-K&dateRange=custom&startdt=2022-01-01&enddt=2025-12-31"
EDGAR_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
EDGAR_BASE = "https://www.sec.gov"

HEADERS = {
    "User-Agent": "TractianCaseStudy research@tractian-case.com",
    "Accept": "application/json",
}


def discover_cik(company_name: str) -> Optional[int]:
    """
    Discover a company's CIK number via EDGAR's company search API.
    Returns CIK integer or None if not found.
    """
    # Try the full-text search first
    search_terms = [
        company_name,
        company_name.replace(" & ", " "),
        company_name.split(" ")[0],  # First word only as fallback
    ]

    for term in search_terms:
        try:
            # Use EDGAR full-text search
            url = f"https://efts.sec.gov/LATEST/search-index?q=%22{requests.utils.quote(term)}%22&forms=10-K"
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("hits", {}).get("hits", [])
                if hits:
                    entity_name = hits[0].get("_source", {}).get("entity_name", "")
                    cik_str = hits[0].get("_source", {}).get("file_num", "")
                    # Also try entity_id field
                    entity_id = hits[0].get("_source", {}).get("entity_id", "")
                    if entity_id:
                        try:
                            cik = int(entity_id)
                            log.info(f"[{company_name}] Found CIK {cik} via full-text search (entity: {entity_name})")
                            return cik
                        except (ValueError, TypeError):
                            pass
            time.sleep(0.3)
        except Exception as e:
            log.debug(f"[{company_name}] EDGAR full-text search failed for term '{term}': {e}")

    # Try the company tickers JSON (covers most large public companies)
    try:
        resp = requests.get(EDGAR_COMPANY_TICKERS, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            tickers_data = resp.json()
            name_lower = company_name.lower()

            # Search for closest match
            best_cik = None
            best_score = 0

            for entry in tickers_data.values():
                edgar_name = entry.get("title", "").lower()
                # Check if company name words appear in EDGAR name
                words = [w for w in name_lower.split() if len(w) > 3]
                match_count = sum(1 for w in words if w in edgar_name)
                score = match_count / max(len(words), 1)

                if score > best_score and score >= 0.5:
                    best_score = score
                    best_cik = entry.get("cik_str")

            if best_cik:
                cik = int(best_cik)
                log.info(f"[{company_name}] Found CIK {cik} via company tickers (score: {best_score:.2f})")
                return cik

    except Exception as e:
        log.debug(f"[{company_name}] Company tickers search failed: {e}")

    # Try EDGAR company search endpoint
    try:
        name_encoded = requests.utils.quote(company_name)
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={name_encoded}&CIK=&type=10-K&dateb=&owner=include&count=5&search_text=&action=getcompany&output=atom"
        resp = requests.get(url, headers={**HEADERS, "Accept": "text/xml"}, timeout=20)
        if resp.status_code == 200:
            cik_matches = re.findall(r'<CIK>(\d+)</CIK>', resp.text)
            if cik_matches:
                cik = int(cik_matches[0])
                log.info(f"[{company_name}] Found CIK {cik} via EDGAR browse")
                return cik
    except Exception as e:
        log.debug(f"[{company_name}] EDGAR browse search failed: {e}")

    log.info(f"[{company_name}] CIK not found via EDGAR — likely private or not in EDGAR")
    return None


def fetch_10k_properties(company_name: str, is_public: bool, force_refresh: bool = False) -> dict:
    """
    Fetch Item 2 (Properties) from the most recent 10-K filing.
    CIK is discovered at runtime via EDGAR APIs.
    Returns dict with extracted text, source URL, and location candidates.
    """
    cache_key = "edgar_properties"
    if not force_refresh and has_raw(company_name, cache_key):
        log.info(f"[{company_name}] Using cached EDGAR data")
        return load_raw(company_name, cache_key)

    if not is_public:
        log.info(f"[{company_name}] Private company — SEC EDGAR data not available")
        result = _edgar_no_data(company_name, "Private company — SEC EDGAR data not available")
        save_raw(company_name, cache_key, result)
        return result

    log.info(f"[{company_name}] Discovering CIK via EDGAR...")
    cik = discover_cik(company_name)

    if not cik:
        log.info(f"[{company_name}] Could not find CIK — skipping EDGAR")
        result = _edgar_no_data(company_name, "CIK not found via EDGAR company search")
        save_raw(company_name, cache_key, result)
        return result

    log.info(f"[{company_name}] Fetching 10-K filing data for CIK {cik}...")

    try:
        sub_url = EDGAR_SUBMISSIONS.format(cik=cik)
        resp = requests.get(sub_url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            log.warning(f"[{company_name}] EDGAR submissions fetch failed: {resp.status_code}")
            return _edgar_failure(company_name, cache_key, f"HTTP {resp.status_code} from submissions API")

        data = resp.json()
        filings = data.get("filings", {}).get("recent", {})

        forms = filings.get("form", [])
        accession_numbers = filings.get("accessionNumber", [])
        filing_dates = filings.get("filingDate", [])
        primary_docs = filings.get("primaryDocument", [])

        ten_k_idx = None
        for i, form in enumerate(forms):
            if form == "10-K":
                ten_k_idx = i
                break

        if ten_k_idx is None:
            log.warning(f"[{company_name}] No 10-K found in recent filings")
            return _edgar_failure(company_name, cache_key, "No 10-K in recent EDGAR filings")

        accession_clean = accession_numbers[ten_k_idx]
        accession_nodash = accession_clean.replace("-", "")
        filing_date = filing_dates[ten_k_idx]
        primary_doc = primary_docs[ten_k_idx] if primary_docs else ""

        log.info(f"[{company_name}] Found 10-K filed {filing_date}, extracting Properties section...")
        time.sleep(0.5)

        # Try fetching the primary document
        if primary_doc:
            doc_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_nodash}/{primary_doc}"
            properties_text, actual_url = _try_fetch_properties(doc_url)
            if properties_text:
                locations = extract_locations_from_properties(properties_text, company_name, actual_url)
                result = {
                    "company_name": company_name,
                    "has_sec_data": True,
                    "cik": cik,
                    "filing_date": filing_date,
                    "properties_text": properties_text[:20000],
                    "source_url": actual_url,
                    "locations": locations,
                }
                save_raw(company_name, cache_key, result)
                log.info(f"[{company_name}] EDGAR: extracted {len(locations)} location candidates from 10-K Properties")
                return result

        # Fallback: scan the filing index for any .htm document
        index_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_nodash}/"
        idx_resp = requests.get(
            index_url,
            headers={**HEADERS, "Accept": "text/html"},
            timeout=30
        )
        if idx_resp.status_code == 200:
            # Extract all document links from the index
            doc_links = re.findall(
                r'href="(/Archives/edgar/data/\d+/\d+/[^"]+\.htm)"',
                idx_resp.text
            )
            for link in doc_links[:5]:
                doc_url = EDGAR_BASE + link
                properties_text, actual_url = _try_fetch_properties(doc_url)
                if properties_text:
                    locations = extract_locations_from_properties(properties_text, company_name, actual_url)
                    result = {
                        "company_name": company_name,
                        "has_sec_data": True,
                        "cik": cik,
                        "filing_date": filing_date,
                        "properties_text": properties_text[:20000],
                        "source_url": actual_url,
                        "locations": locations,
                    }
                    save_raw(company_name, cache_key, result)
                    log.info(f"[{company_name}] EDGAR: extracted {len(locations)} locations from index scan")
                    return result
                time.sleep(0.3)

        return _edgar_failure(company_name, cache_key, "Could not extract Properties section from any 10-K document")

    except Exception as e:
        log.warning(f"[{company_name}] EDGAR error: {e}")
        log_failure(company_name, "edgar", str(e))
        return _edgar_failure(company_name, cache_key, str(e))


def _try_fetch_properties(doc_url: str) -> tuple[Optional[str], str]:
    """Fetch a document and extract its Properties section. Returns (text, url)."""
    try:
        resp = requests.get(
            doc_url,
            headers={**HEADERS, "Accept": "text/html"},
            timeout=60
        )
        if resp.status_code == 200:
            props = extract_properties_section(resp.text)
            if props:
                return props, doc_url
    except Exception as e:
        log.debug(f"Failed to fetch {doc_url}: {e}")
    return None, doc_url


def _edgar_no_data(company_name: str, reason: str) -> dict:
    return {
        "company_name": company_name,
        "has_sec_data": False,
        "reason": reason,
        "properties_text": None,
        "source_url": None,
        "locations": [],
    }


def _edgar_failure(company_name: str, cache_key: str, reason: str) -> dict:
    result = _edgar_no_data(company_name, reason)
    save_raw(company_name, cache_key, result)
    return result


def extract_properties_section(html: str) -> Optional[str]:
    """
    Extract the Item 2 (Properties) section from a 10-K filing HTML.
    Returns clean text or None if not found.
    """
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()

    patterns = [
        r'ITEM\s*2\.?\s*PROPERT(?:IES|Y)\s*\.(.*?)(?=ITEM\s*3[\.\s]|$)',
        r'Item\s*2\.?\s*Propert(?:ies|y)\s*\.(.*?)(?=Item\s*3[\.\s]|$)',
        r'ITEM\s*2\s*[.—–]\s*PROPERT(?:IES|Y)(.*?)(?=ITEM\s*3\s*[.—–]|$)',
        r'Item\s*2\s*[.—–]\s*Propert(?:ies|y)(.*?)(?=Item\s*3\s*[.—–]|$)',
        r'PROPERTIES\s*\n(.*?)(?=LEGAL\s+PROCEEDINGS|Item\s*3|ITEM\s*3|$)',
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            section = m.group(1).strip()
            if len(section) > 200:
                return section[:15000]

    return None


def extract_locations_from_properties(text: str, company_name: str, source_url: str) -> list[dict]:
    """
    Extract location mentions from the Properties section text.
    All patterns are generic — no company-specific assumptions.
    """
    candidates = []
    seen: set[str] = set()

    patterns = [
        # "plant/facility/mill in City, State" — core SEC pattern
        r'(?:plant|facility|mill|refinery|mine|complex|center|headquarters?|office|warehouse|distribution\s+center|brewery|factory)[^.]{0,80}?(?:in|at|near|located\s+in)\s+([A-Z][a-zA-Z\s]{2,30}(?:,\s*[A-Z][a-zA-Z\s]{2,30})?)',
        # City, ST abbreviation
        r'\b([A-Z][a-zA-Z\s]{2,25}),\s+([A-Z]{2})\b',
        # City, Full Country name
        r'\b([A-Z][a-zA-Z\s]{2,25}),\s+(Germany|France|Brazil|Canada|Mexico|Belgium|Netherlands|Spain|Italy|India|China|Australia|Argentina|Colombia|Poland|Czech Republic|Hungary|South Africa|Japan|South Korea|Turkey|Russia|Indonesia|Malaysia|Singapore)\b',
        # "approximately X square feet in Location"
        r'approximately\s+[\d,]+\s+square\s+feet[^.]{0,60}?(?:in|at)\s+([A-Z][a-zA-Z\s,]{3,50}?)(?:\.|,\s*(?:and|which|the|a\s))',
        # Named facilities with location
        r'([A-Z][a-zA-Z\s]+(?: Plant| Mill| Refinery| Mine| Facility| Works| Complex| Brewery| Factory))\s*(?:,|in|at|located\s+in)\s+([A-Z][a-zA-Z\s,]{2,40}?)(?:\.|,)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                parts = [str(m).strip() for m in match if m.strip() and len(m.strip()) > 1]
                raw = ", ".join(parts)
            else:
                raw = str(match).strip()

            raw = re.sub(r'\s+', ' ', raw).strip().strip(",").strip()

            if len(raw) < 4 or len(raw) > 150:
                continue
            if raw.lower() in seen:
                continue

            skip_terms = [
                "january", "february", "march", "april", "june", "july",
                "august", "september", "october", "november", "december",
                "monday", "approximately", "section", "annual", "fiscal",
                "pursuant", "included", "following", "additional", "certain",
                "various", "significant", "primary", "principal",
            ]
            if any(sw in raw.lower() for sw in skip_terms):
                continue

            seen.add(raw.lower())
            candidates.append({
                "raw_text": raw,
                "source_url": source_url,
                "source_type": "SEC_EDGAR",
                "company_name": company_name,
            })

    log.debug(f"[{company_name}] Extracted {len(candidates)} location candidates from EDGAR Properties section")
    return candidates[:60]
