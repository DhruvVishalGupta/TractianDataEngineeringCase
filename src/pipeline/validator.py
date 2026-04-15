"""
Validator — cross-references each facility via Brave Search to verify existence
and upgrade/downgrade confidence accordingly.

A facility with zero independent corroboration gets needs_verification=True.
A facility confirmed by 2+ independent sources gets confidence upgraded to HIGH.
"""
from __future__ import annotations
import time
from .logger import get_logger

log = get_logger("validator")

# These are filled in by the orchestrator's MCP search calls
# The validator receives search results, not raw queries


def validate_facility_with_search_results(
    facility: dict,
    search_results: list[dict],
) -> dict:
    """
    Given a facility dict and search results for "{company} {city}",
    update confidence and needs_verification based on corroboration found.

    Args:
        facility: facility dict from classifier
        search_results: list of Brave Search result dicts (title, url, description)

    Returns updated facility dict.
    """
    facility = dict(facility)
    company = facility.get("company_name", "")
    city = facility.get("city", "")
    country = facility.get("country", "")

    # Count independent corroborating sources
    corroborating_urls = []

    location_terms = [t.lower() for t in [city, country] if t]
    company_lower = company.lower().split()[0]  # First word for matching

    for result in search_results:
        url = result.get("url", "")
        title = (result.get("title", "") or "").lower()
        desc = (result.get("description", "") or "").lower()
        combined = f"{title} {desc}"

        # Skip the company's own website as "independent" corroboration
        website = facility.get("website", "")
        if website and website.replace("https://", "").replace("http://", "").split("/")[0] in url:
            continue

        # Check if result mentions the company AND location
        mentions_company = company_lower in combined
        mentions_location = any(term in combined for term in location_terms if len(term) > 2)

        if mentions_company and mentions_location:
            corroborating_urls.append(url)

    # Update facility
    existing_urls = facility.get("all_source_urls", [])
    for u in corroborating_urls:
        if u not in existing_urls:
            existing_urls.append(u)

    facility["all_source_urls"] = existing_urls
    facility["source_count"] = len([u for u in existing_urls if u])

    if facility["source_count"] > 1:
        facility["source_type"] = "MULTIPLE"

    # Confidence upgrade/downgrade rules
    current_confidence = facility.get("confidence", "LOW")

    if len(corroborating_urls) >= 2:
        # Multiple independent sources → HIGH
        facility["confidence"] = "HIGH"
        facility["needs_verification"] = False
        log.debug(
            f"[{company}] {city}: confidence upgraded to HIGH "
            f"({len(corroborating_urls)} corroborating sources)"
        )
    elif len(corroborating_urls) == 1:
        # One independent source → upgrade one level if not already HIGH
        upgrades = {"ESTIMATED": "LOW", "LOW": "MED", "MED": "HIGH", "HIGH": "HIGH"}
        facility["confidence"] = upgrades.get(current_confidence, current_confidence)
        facility["needs_verification"] = facility["confidence"] in ("LOW", "ESTIMATED")
        log.debug(f"[{company}] {city}: confidence upgraded from {current_confidence} → {facility['confidence']}")
    elif len(corroborating_urls) == 0 and current_confidence not in ("HIGH",):
        # No independent corroboration → needs_verification
        facility["needs_verification"] = True
        log.debug(f"[{company}] {city}: no corroboration — needs_verification=True")

    return facility


def build_validation_query(company_name: str, facility: dict) -> str:
    """Build a Brave Search query for validating a specific facility."""
    city = facility.get("city", "")
    country = facility.get("country", "")
    facility_type = facility.get("facility_type", "")

    parts = [company_name]
    if city:
        parts.append(city)
    if country and country != city:
        parts.append(country)
    if facility_type and facility_type not in ("Unknown", "Corporate HQ", "Sales Office"):
        parts.append(facility_type.lower())

    return " ".join(parts)
