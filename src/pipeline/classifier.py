"""
Classifier — takes raw location candidates and classifies them via Ollama.
Builds context from surrounding scraped text to improve classification quality.
"""
from __future__ import annotations
import re
from datetime import datetime
from .schema import ClassifiedFacility, OllamaFacilityResponse
from .ollama_client import batch_classify_facilities
from .raw_store import save_raw, load_raw, has_raw
from .logger import get_logger

log = get_logger("classifier")


def _build_context_for_candidate(candidate: dict, scraped_pages: list[dict]) -> str:
    """
    Find the surrounding text context for a location candidate
    from the scraped page content. Better context → better classification.
    """
    location_text = candidate.get("raw_text", "")
    source_url = candidate.get("source_url", "")

    # Find matching page
    for page in scraped_pages:
        if page.get("url", "") == source_url:
            text = page.get("text", "")
            # Find location in page text and extract surrounding context
            idx = text.lower().find(location_text.lower()[:20])
            if idx >= 0:
                start = max(0, idx - 200)
                end = min(len(text), idx + 300)
                return text[start:end].strip()

    return ""


def classify_company_locations(
    company_name: str,
    website: str,
    raw_candidates: list[dict],
    scraped_pages: list[dict],
    force_refresh: bool = False,
) -> list[dict]:
    """
    Classify all raw location candidates for a company using Ollama.
    Enriches each candidate with surrounding context before classification.
    Returns list of classified facility dicts.
    """
    cache_key = "classified_facilities"
    if not force_refresh and has_raw(company_name, cache_key):
        log.info(f"[{company_name}] Using cached classified facilities")
        return load_raw(company_name, cache_key)

    if not raw_candidates:
        log.info(f"[{company_name}] No candidates to classify")
        save_raw(company_name, cache_key, [])
        return []

    # Enrich candidates with context
    enriched = []
    for candidate in raw_candidates:
        enriched_candidate = dict(candidate)
        ctx = _build_context_for_candidate(candidate, scraped_pages)
        enriched_candidate["context"] = ctx
        enriched.append(enriched_candidate)

    # Batch classify via Ollama
    classifications: list[OllamaFacilityResponse] = batch_classify_facilities(
        company_name=company_name,
        candidates=enriched,
        max_candidates=40,
    )

    today = datetime.utcnow().strftime("%Y-%m-%d")
    results = []

    for i, (candidate, classification) in enumerate(zip(enriched, classifications)):
        if classification is None:
            continue

        # Build the facility dict
        facility = {
            "company_name": company_name,
            "website": website,
            "facility_location": classification.facility_location or candidate.get("raw_text", ""),
            "city": classification.city,
            "state_region": classification.state_region,
            "country": classification.country,
            "lat": classification.lat,
            "lon": classification.lon,
            "facility_type": classification.facility_type,
            "classification_basis": classification.classification_basis,
            "confidence": classification.confidence,
            "needs_verification": classification.confidence in ("LOW", "ESTIMATED"),
            "source_url": candidate.get("source_url", f"https://{website}"),
            "source_type": candidate.get("source_type", "UNKNOWN"),
            "source_count": 1,
            "all_source_urls": [candidate.get("source_url", "")],
            "date_collected": today,
        }
        results.append(facility)

    log.info(f"[{company_name}] Classified {len(results)} facilities")
    save_raw(company_name, cache_key, results)
    return results
