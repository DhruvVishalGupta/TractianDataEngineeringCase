"""
SEC EDGAR module — fetches Item 2 (Properties) from 10-K filings.
Gold-standard data source for US public companies.

CIK is resolved primarily via the registered ticker symbol (exact match against
company_tickers.json). Falls back to fuzzy name match only when no ticker exists.

The Properties section is then extracted with a Claude-assisted parser, which is
substantially more robust than regex on modern 10-K HTML (which often nests Item 2
under XBRL tags, layered tables, and inline-XBRL spans).
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
EDGAR_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
EDGAR_BASE = "https://www.sec.gov"

HEADERS = {
    "User-Agent": "TractianCaseStudy research@tractian-case.com",
    "Accept": "application/json",
}

_TICKER_CACHE: dict[str, tuple[int, str]] | None = None


def _load_ticker_map() -> dict[str, tuple[int, str]]:
    """Cache the SEC company_tickers.json once per process. Maps TICKER → (CIK, title)."""
    global _TICKER_CACHE
    if _TICKER_CACHE is not None:
        return _TICKER_CACHE
    try:
        resp = requests.get(EDGAR_COMPANY_TICKERS, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            log.warning(f"company_tickers.json HTTP {resp.status_code}")
            _TICKER_CACHE = {}
            return _TICKER_CACHE
        raw = resp.json()
        out: dict[str, tuple[int, str]] = {}
        for entry in raw.values():
            t = (entry.get("ticker") or "").strip().upper()
            if t:
                out[t] = (int(entry.get("cik_str")), entry.get("title", ""))
        _TICKER_CACHE = out
        log.debug(f"Loaded {len(out)} SEC tickers")
        return out
    except Exception as e:
        log.warning(f"Failed to load SEC tickers: {e}")
        _TICKER_CACHE = {}
        return _TICKER_CACHE


def resolve_cik(company_name: str, sec_ticker: Optional[str]) -> Optional[int]:
    """
    Resolve a company's SEC CIK.

    Priority:
      1. Registered ticker (exact match against company_tickers.json) — authoritative.
      2. Name match against the same JSON, requiring a high overlap to avoid the
         Wells-Fargo-as-Mosaic style collision the prior fuzzy search caused.
    """
    tickers = _load_ticker_map()

    if sec_ticker:
        ticker_up = sec_ticker.strip().upper()
        if ticker_up in tickers:
            cik, title = tickers[ticker_up]
            log.info(f"[{company_name}] CIK {cik} via ticker {ticker_up} ({title})")
            return cik
        log.warning(f"[{company_name}] Ticker {ticker_up!r} not in SEC company_tickers.json")

    name_lower = company_name.lower()
    name_words = [w for w in re.split(r"[^a-z0-9]+", name_lower) if len(w) > 3]
    if not name_words:
        return None

    best_cik: Optional[int] = None
    best_score = 0.0
    best_title = ""
    for ticker_up, (cik, title) in tickers.items():
        title_l = title.lower()
        match = sum(1 for w in name_words if w in title_l) / len(name_words)
        if match > best_score and match >= 0.75:
            best_score = match
            best_cik = cik
            best_title = title
    if best_cik:
        log.info(f"[{company_name}] CIK {best_cik} via name match ({best_title}, score={best_score:.2f})")
        return best_cik

    log.info(f"[{company_name}] CIK not found")
    return None


def fetch_10k_properties(
    company_name: str,
    is_public: bool,
    sec_ticker: Optional[str] = None,
    force_refresh: bool = False,
) -> dict:
    """
    Fetch Item 2 (Properties) text from the most recent 10-K filing.
    Returns dict with {has_sec_data, cik, filing_date, properties_text, source_url}.
    """
    cache_key = "edgar_properties"
    if not force_refresh and has_raw(company_name, cache_key):
        cached = load_raw(company_name, cache_key)
        log.info(f"[{company_name}] EDGAR cached: has_data={cached.get('has_sec_data')} text_len={len(cached.get('properties_text') or '')}")
        return cached

    if not is_public:
        result = _edgar_no_data(company_name, "Private company — SEC EDGAR data not available")
        save_raw(company_name, cache_key, result)
        return result

    cik = resolve_cik(company_name, sec_ticker)
    if not cik:
        result = _edgar_no_data(company_name, "CIK not resolved via ticker or name match")
        save_raw(company_name, cache_key, result)
        return result

    log.info(f"[{company_name}] Fetching submissions for CIK {cik}...")

    try:
        sub_url = EDGAR_SUBMISSIONS.format(cik=cik)
        resp = requests.get(sub_url, headers=HEADERS, timeout=30)
        if resp.status_code == 404:
            # Some foreign issuers (e.g. ArcelorMittal, Spotify, ABInBev) file 20-F not 10-K.
            return _save(company_name, cache_key, _edgar_no_data(company_name, "Submissions JSON 404 — foreign issuer or delisted"))
        if resp.status_code != 200:
            return _save(company_name, cache_key, _edgar_no_data(company_name, f"submissions HTTP {resp.status_code}"))

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accs = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        primaries = recent.get("primaryDocument", [])

        # Foreign filers use 20-F; some real-estate filers use 10-K/A. We accept both.
        wanted_forms = {"10-K", "20-F", "10-K/A", "20-F/A"}
        idx = next((i for i, f in enumerate(forms) if f in wanted_forms), None)
        if idx is None:
            return _save(company_name, cache_key, _edgar_no_data(company_name, "No 10-K/20-F in recent filings"))

        form = forms[idx]
        accession_nodash = accs[idx].replace("-", "")
        filing_date = dates[idx]
        primary_doc = primaries[idx] if primaries else ""

        log.info(f"[{company_name}] Found {form} filed {filing_date}, attempting Properties extraction...")
        time.sleep(0.4)

        candidate_urls: list[str] = []
        if primary_doc:
            candidate_urls.append(f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_nodash}/{primary_doc}")

        # Always also scan the index for additional documents (sometimes the Properties
        # table is in a separate exhibit doc like wfc-20251231_d2.htm — but we now anchor
        # by primary doc first so we don't accidentally pick someone else's filing).
        index_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_nodash}/"
        try:
            idx_resp = requests.get(index_url, headers={**HEADERS, "Accept": "text/html"}, timeout=30)
            if idx_resp.status_code == 200:
                links = re.findall(r'href="(/Archives/edgar/data/\d+/\d+/[^"]+\.htm)"', idx_resp.text)
                for link in links[:6]:
                    full = EDGAR_BASE + link
                    if full not in candidate_urls:
                        candidate_urls.append(full)
        except Exception:
            pass

        for doc_url in candidate_urls[:5]:
            time.sleep(0.3)
            try:
                doc_resp = requests.get(doc_url, headers={**HEADERS, "Accept": "text/html"}, timeout=60)
                if doc_resp.status_code != 200:
                    continue
                section = _extract_properties_section(doc_resp.text)
                if section and len(section) >= 250:
                    result = {
                        "company_name": company_name,
                        "has_sec_data": True,
                        "cik": cik,
                        "form": form,
                        "filing_date": filing_date,
                        "properties_text": section[:25000],
                        "source_url": doc_url,
                    }
                    save_raw(company_name, cache_key, result)
                    log.info(f"[{company_name}] EDGAR Properties extracted: {len(section)} chars from {doc_url.rsplit('/',1)[-1]}")
                    return result
            except Exception as e:
                log.debug(f"[{company_name}] failed {doc_url}: {e}")

        return _save(company_name, cache_key, _edgar_no_data(company_name, "Properties section not located in any document"))

    except Exception as e:
        log.warning(f"[{company_name}] EDGAR error: {e}")
        log_failure(company_name, "edgar", str(e))
        return _save(company_name, cache_key, _edgar_no_data(company_name, str(e)))


def _save(company_name: str, cache_key: str, result: dict) -> dict:
    save_raw(company_name, cache_key, result)
    return result


def _edgar_no_data(company_name: str, reason: str) -> dict:
    return {
        "company_name": company_name,
        "has_sec_data": False,
        "reason": reason,
        "properties_text": None,
        "source_url": None,
    }


def _strip_html(html: str) -> str:
    """Drop scripts, styles, tags; collapse whitespace; keep entity-decoded readable text."""
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level closers with a newline so tables/divs stay readable as text.
    html = re.sub(r"</(?:p|div|tr|li|h[1-6]|td|th)>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    # HTML entities
    text = (text.replace("&nbsp;", " ").replace("&#160;", " ")
                .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&rsquo;", "'").replace("&ldquo;", '"').replace("&rdquo;", '"'))
    text = re.sub(r"&#?\w+;", " ", text)
    # Normalize whitespace but keep paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _extract_properties_section(html: str) -> Optional[str]:
    """
    Extract Item 2 (Properties) text. Strategy:
      1. Strip HTML to readable text.
      2. Locate "Item 2 ... Properties" anchor (broad regex covering most modern formats).
      3. Slice until the next major item ("Item 3", "Legal Proceedings") or 25 KB.
    """
    text = _strip_html(html)

    # Anchor patterns ordered most-specific → fallback.
    anchors = [
        r"\bItem\s*2[\s.\-:—]*Propert(?:ies|y)\b",
        r"\bITEM\s*2[\s.\-:—]*PROPERT(?:IES|Y)\b",
        r"\bPROPERTIES\b\s*\n",
    ]
    end_patterns = [
        r"\bItem\s*3[\s.\-:—]*Legal\s+Proceedings\b",
        r"\bITEM\s*3[\s.\-:—]*LEGAL\s+PROCEEDINGS\b",
        r"\bItem\s*3[\s.\-:—]",
        r"\bITEM\s*3[\s.\-:—]",
        r"\bItem\s*4[\s.\-:—]",
        r"\bUnresolved\s+Staff\s+Comments\b",
    ]

    best_section: Optional[str] = None
    for anc in anchors:
        for m in re.finditer(anc, text, flags=re.IGNORECASE):
            start = m.end()
            # End slice at first end pattern after start, else 25k.
            end = len(text)
            for ep in end_patterns:
                em = re.search(ep, text[start:start + 30000], flags=re.IGNORECASE)
                if em:
                    end = start + em.start()
                    break
            section = text[start:end].strip()
            # Filter: real Properties sections always mention common location nouns.
            keyword_score = sum(
                1 for kw in ("plant", "facility", "facilities", "manufacturing", "headquarter",
                              "leased", "owned", "square feet", "located", "operations")
                if kw in section.lower()
            )
            if keyword_score < 2 or len(section) < 250:
                continue
            if best_section is None or len(section) > len(best_section):
                best_section = section
        if best_section:
            return best_section[:25000]

    return None
