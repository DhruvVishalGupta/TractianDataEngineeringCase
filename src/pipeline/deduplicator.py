"""
Deduplication module — merges location candidates by fuzzy city+country match.
Tracks source URLs and source counts per unique location.
"""
from __future__ import annotations
from typing import Optional
from rapidfuzz import fuzz
from .logger import get_logger

log = get_logger("deduplicator")

SIMILARITY_THRESHOLD = 85  # % similarity for fuzzy match


def normalize_city(city: str) -> str:
    """Normalize city name for comparison."""
    if not city:
        return ""
    city = city.strip().lower()
    # Common abbreviations
    replacements = {
        "st.": "saint",
        "st ": "saint ",
        "ft.": "fort",
        "ft ": "fort ",
        "mt.": "mount",
        "mt ": "mount ",
    }
    for old, new in replacements.items():
        city = city.replace(old, new)
    return city


def normalize_country(country: str) -> str:
    """Normalize country name for comparison."""
    if not country:
        return ""
    country = country.strip().lower()
    # Common variations
    aliases = {
        "usa": "united states",
        "us": "united states",
        "u.s.": "united states",
        "u.s.a.": "united states",
        "uk": "united kingdom",
        "u.k.": "united kingdom",
        "great britain": "united kingdom",
    }
    return aliases.get(country, country)


def location_key(city: Optional[str], country: Optional[str]) -> str:
    """Generate a normalized key for deduplication."""
    city_norm = normalize_city(city or "")
    country_norm = normalize_country(country or "")
    return f"{city_norm}|{country_norm}"


def are_same_location(
    city1: Optional[str],
    country1: Optional[str],
    city2: Optional[str],
    country2: Optional[str],
) -> bool:
    """Check if two locations refer to the same place using fuzzy matching."""
    if not city1 and not city2:
        return False  # Both unknown — don't merge

    key1 = location_key(city1, country1)
    key2 = location_key(city2, country2)

    if not key1 or not key2:
        return False

    # Exact match after normalization
    if key1 == key2:
        return True

    # Fuzzy match
    similarity = fuzz.ratio(key1, key2)
    return similarity >= SIMILARITY_THRESHOLD


def deduplicate_facilities(facilities: list[dict]) -> list[dict]:
    """
    Merge duplicate facilities. A duplicate is defined as having the same
    city + country (fuzzy matched). Merge by keeping the higher-confidence
    entry and accumulating all source URLs.

    Input: list of dicts with keys: city, country, source_url, source_type,
           confidence, facility_type, classification_basis, facility_location, etc.
    Output: deduplicated list with source_count and all_source_urls fields.
    """
    merged = []

    for facility in facilities:
        city = facility.get("city")
        country = facility.get("country")
        source_url = facility.get("source_url", "")
        facility_copy = dict(facility)

        # Find existing match
        found_match = None
        for existing in merged:
            if are_same_location(city, country, existing.get("city"), existing.get("country")):
                found_match = existing
                break

        if found_match:
            # Merge — accumulate sources
            existing_urls = found_match.get("all_source_urls", [found_match.get("source_url", "")])
            if source_url not in existing_urls:
                existing_urls.append(source_url)
            found_match["all_source_urls"] = existing_urls
            found_match["source_count"] = len([u for u in existing_urls if u])

            # Use MULTIPLE source type if more than one source
            if found_match["source_count"] > 1:
                source_types = set()
                for u in existing_urls:
                    st = facility.get("source_type", "UNKNOWN")
                    source_types.add(st)
                found_match["source_type"] = "MULTIPLE" if len(source_types) > 1 else found_match.get("source_type")
                found_match["source_url"] = existing_urls[0]  # Primary source

            # Upgrade confidence if new source adds corroboration
            confidence_rank = {"HIGH": 3, "MED": 2, "LOW": 1, "ESTIMATED": 0}
            current_conf = found_match.get("confidence", "LOW")
            new_conf = facility_copy.get("confidence", "LOW")
            if confidence_rank.get(new_conf, 0) > confidence_rank.get(current_conf, 0):
                found_match["confidence"] = new_conf
                found_match["classification_basis"] = facility_copy.get("classification_basis", found_match.get("classification_basis"))

            # If multiple sources now corroborate, upgrade to HIGH
            if found_match["source_count"] >= 2 and found_match.get("confidence") in ["MED", "LOW"]:
                found_match["confidence"] = "HIGH"
                found_match["needs_verification"] = False

        else:
            # New unique location
            facility_copy["all_source_urls"] = [source_url] if source_url else []
            facility_copy["source_count"] = 1
            facility_copy.setdefault("needs_verification", True)
            merged.append(facility_copy)

    log.debug(f"Deduplicated {len(facilities)} → {len(merged)} unique facilities")
    return merged
