"""
Pipeline orchestrator — drives 20 companies through the full
discovery → extraction → validation → scoring → output pipeline.

Usage:
    python -m src.pipeline.orchestrator
"""
import time
import traceback
from datetime import datetime, UTC
from tqdm import tqdm

from .companies import get_all_companies, Company
from .scraper import scrape_urls, scrape_company_domain
from .searcher import discover_facility_urls, discover_firmographics, discover_market_research
from .edgar import fetch_10k_properties
from .claude_client import extract_facilities
from .firmographics import discover_firmographics as discover_company_firmographics
from .validator import validate_facilities, PLANT_LIKE_TYPES
from .deduplicator import deduplicate_facilities
from .reclassifier import reclassify_all
from .geocoder import geocode_facility
from .icp_scorer import calculate_icp_score
from .output_csv import write_csv
from .output_xlsx import write_xlsx
from .output_json import write_json
from .logger import get_logger

log = get_logger("orchestrator")


def _build_hq_fallback_row(company: Company, firmo, icp_score, source_url: str) -> dict:
    """
    When no facilities are validated for a company (often happens for SaaS / fintech /
    marketplaces with no plants), still emit one Corporate HQ row from cached
    firmographic HQ data so the company appears in the final output. Matches the case
    sample where Salesforce / Apple / Kalshi / McDonald's are shown with one HQ row.
    """
    city = firmo.headquarters_city or ""
    country = firmo.headquarters_country or ""
    location = ", ".join([p for p in (city, country) if p]) or "Unknown HQ location"

    row = {
        "company_name": company.name,
        "website": company.website,
        "icp_score": icp_score.total,
        "score_breakdown": _score_breakdown_dict(icp_score),
        "facility_location": location,
        "city": city,
        "state_region": "",
        "country": country,
        "lat": None,
        "lon": None,
        "facility_type": "Corporate HQ",
        "classification_basis": (
            "Fallback HQ row from firmographic data — no individual facilities surfaced "
            "via website/SEC scraping. Confidence is LOW because location was not "
            "cross-verified against a primary facility document."
        ),
        "confidence": "LOW" if city else "ESTIMATED",
        "needs_verification": True,
        "source_url": source_url or f"https://{company.website}",
        "source_type": "WIKIPEDIA" if "wikipedia" in (source_url or "").lower() else "WEBSITE",
        "source_count": 1,
        "date_collected": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    return row


def _score_breakdown_dict(icp_score) -> dict:
    return {
        "total": icp_score.total,
        "industry_fit": icp_score.industry_fit.__dict__,
        "operational_scale": icp_score.operational_scale.__dict__,
        "physical_footprint": icp_score.physical_footprint.__dict__,
        "equipment_dependency": icp_score.equipment_dependency.__dict__,
        "score_confidence": icp_score.score_confidence,
        "plain_english": icp_score.plain_english,
    }


def process_company(company: Company, on_progress=None) -> tuple[list[dict], dict]:
    """
    Run full discovery → scoring pipeline for one company.

    on_progress(stage: str, detail: str = "") is an optional callback fired at each
    pipeline milestone — used by the live-demo API endpoint to stream progress.
    """
    name, website = company.name, company.website
    log.info("=" * 60)
    log.info(f"Processing: {name}")
    log.info("=" * 60)

    def _p(stage, detail=""):
        if on_progress:
            try:
                on_progress(stage, detail)
            except Exception:
                pass  # progress reporting must never break the pipeline

    _p("discovery", "Searching Brave OSINT dorks for facility URLs")
    # ── Phase 1: Discovery ───────────────────────────────────────────
    facility_urls = discover_facility_urls(name, website)
    firmo_search_data = discover_firmographics(name)
    market_research_data = discover_market_research(name, website)

    _p("edgar", f"Resolving SEC EDGAR filing (ticker: {company.sec_ticker or 'none'})")
    # SEC EDGAR — now uses the registered ticker, not fuzzy name search.
    edgar_data = fetch_10k_properties(name, company.is_public, sec_ticker=company.sec_ticker)
    edgar_text = edgar_data.get("properties_text") or ""
    edgar_url = edgar_data.get("source_url") or "SEC EDGAR 10-K"

    # ── Phase 2: Scrape ──────────────────────────────────────────────
    _p("scrape", f"Fetching {len(facility_urls) or 'fallback'} candidate pages via Firecrawl")
    if facility_urls:
        scraped_pages = scrape_urls(name, facility_urls, website=website)
    elif website:
        scraped_pages = scrape_company_domain(name, website)
    else:
        scraped_pages = []

    pages_with_urls = list(scraped_pages)
    if edgar_text:
        pages_with_urls.insert(0, {"url": edgar_url, "markdown": edgar_text})

    source_text_by_url = {p["url"]: p.get("markdown", "") for p in pages_with_urls if p.get("url")}

    # ── Phase 3: Claude extraction ───────────────────────────────────
    _p("extract", f"Claude reading {len(pages_with_urls)} pages for facilities")
    raw_facilities = extract_facilities(name, pages_with_urls)
    log.info(f"[{name}] Claude extracted {len(raw_facilities)} candidate facilities")

    # ── Phase 4: Firmographics ───────────────────────────────────────
    _p("firmographics", "Fetching Wikipedia/Brave firmographics")
    firmo = discover_company_firmographics(
        company_name=name,
        website=website,
        is_public=company.is_public,
        search_snippets=firmo_search_data.get("snippets", []),
    )
    industry_text = " ".join(filter(None, [
        firmo.industry or "",
        " ".join(firmo.industry_keywords or []),
    ])).strip()

    # ── Phase 5: Validate, reclassify, dedup ─────────────────────────
    _p("validate", f"Verifying {len(raw_facilities)} candidates with OSINT corroboration")
    valid_facilities = validate_facilities(
        name,
        raw_facilities,
        industry_text=industry_text,
        source_text_by_url=source_text_by_url,
        company_website=website,
    )
    valid_facilities = reclassify_all(valid_facilities, industry_text=industry_text)
    deduped = deduplicate_facilities(valid_facilities)
    log.info(f"[{name}] After validate→reclassify→dedup: {len(deduped)} facilities")

    # ── Phase 6: Geocode (free OSM Nominatim, polite-rate-limited) ───
    _p("geocode", f"Geocoding {len(deduped)} facilities via OSM Nominatim")
    log.info(f"[{name}] Geocoding {len(deduped)} facilities...")
    for f in deduped:
        geocode_facility(f)

    # ── Phase 7: ICP scoring ─────────────────────────────────────────
    _p("score", "Computing 4-dimension ICP score")
    industrial_count = sum(1 for f in deduped if f.get("facility_type") in PLANT_LIKE_TYPES)

    equipment_evidence = " ".join(p.get("markdown", "") for p in scraped_pages)[:30000]

    icp_score = calculate_icp_score(
        company_name=name,
        industry_text=industry_text,
        employees=firmo.employee_count,
        revenue_billions=firmo.revenue_usd,
        confirmed_industrial_count=industrial_count,
        confirmed_total_count=len(deduped),
        equipment_evidence_text=equipment_evidence,
        market_research_text=market_research_data.get("market_research_text", ""),
        employee_text=firmo.employee_text or str(firmo.employee_count or "Unknown"),
        revenue_text=firmo.revenue_text or (f"${firmo.revenue_usd}B" if firmo.revenue_usd is not None else "Unknown"),
    )

    breakdown = _score_breakdown_dict(icp_score)

    # ── Phase 8: Build final rows ────────────────────────────────────
    final_rows: list[dict] = []
    for f in deduped:
        source_url = f.get("source_url", f"https://{website}")
        s_lower = str(source_url).lower()
        if "sec.gov" in s_lower or "edgar" in s_lower:
            source_type = "SEC_EDGAR"
        elif "wikipedia" in s_lower:
            source_type = "WIKIPEDIA"
        elif website.lower() in s_lower:
            source_type = "WEBSITE"
        else:
            source_type = "SEARCH"

        row = {
            "company_name": name,
            "website": website,
            "icp_score": icp_score.total,
            "score_breakdown": breakdown,
            "facility_location": f.get("facility_location", ""),
            "city": f.get("city", ""),
            "state_region": f.get("state_region", ""),
            "country": f.get("country", ""),
            "lat": f.get("lat"),
            "lon": f.get("lon"),
            "facility_type": f.get("facility_type"),
            "classification_basis": f.get("classification_basis", ""),
            "confidence": f.get("confidence", "LOW"),
            "needs_verification": f.get("confidence") in {"LOW", "ESTIMATED"},
            "source_url": source_url,
            "source_type": source_type,
            "source_count": f.get("source_count", 1),
            # Provenance fields exposed separately (kept out of classification_basis to keep it clean)
            "osint_corroboration": f.get("osint_corroboration"),
            "primary_source_tier": f.get("primary_source_tier"),
            "reclassification_note": f.get("reclassification_note"),
            "confidence_boost_reason": f.get("confidence_boost_reason"),
            "source_tier_breakdown": f.get("source_tier_breakdown"),
            "osint_breakdown": f.get("osint_breakdown"),
            "date_collected": datetime.now(UTC).strftime("%Y-%m-%d"),
        }
        final_rows.append(row)

    # ── Phase 9: HQ fallback ─────────────────────────────────────────
    # Every company appears in the output, even when nothing passes validation.
    if not final_rows:
        # Use Wikipedia as the source URL when we have it (firmo data_sources lists it).
        fallback_source = next(
            (s for s in (firmo.data_sources or []) if "wikipedia" in s.lower()),
            f"https://{website}",
        )
        fallback_row = _build_hq_fallback_row(company, firmo, icp_score, fallback_source)
        # Geocode the fallback HQ as well.
        geocode_facility(fallback_row)
        final_rows = [fallback_row]
        log.info(f"[{name}] No validated facilities — emitting HQ fallback row ({fallback_row['facility_location']})")

    log.info(f"[{name}] Final: {len(final_rows)} rows | ICP {icp_score.total}/10")

    company_summary = {
        "company_name": name,
        "website": website,
        "icp_score": icp_score.total,
        "score_breakdown": breakdown,
        "facilities": final_rows,
    }
    return final_rows, company_summary


def run_pipeline() -> list[dict]:
    companies = get_all_companies()
    all_rows: list[dict] = []
    summaries: list[dict] = []
    failures: list[str] = []

    log.info(f"Starting Tractian GTM pipeline — {len(companies)} companies")
    for company in tqdm(companies, desc="Pipeline"):
        try:
            rows, summary = process_company(company)
            all_rows.extend(rows)
            summaries.append(summary)
            time.sleep(1)
        except Exception as e:
            log.error(f"[{company.name}] pipeline failed: {e}")
            log.error(traceback.format_exc())
            failures.append(company.name)

    log.info(f"Pipeline complete: {len(all_rows)} rows from {len(companies)} companies")
    if failures:
        log.warning(f"Failed: {', '.join(failures)}")

    write_csv(all_rows)
    write_xlsx(all_rows)
    write_json(all_rows, company_summaries=summaries)
    return all_rows


if __name__ == "__main__":
    run_pipeline()
