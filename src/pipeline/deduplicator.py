"""
Deduplicator module.
Merges likely duplicate candidate objects while preserving distinct same-city facilities.
Applies cross-source corroboration: facilities found in multiple independent sources
(e.g. EDGAR + website) get a confidence boost.
"""
from typing import List, Dict

CONFIDENCE_RANK = {"HIGH": 4, "MED": 3, "LOW": 2, "ESTIMATED": 1}


def _boost_confidence(current: str, source_count: int) -> str:
    """
    Promote confidence when a facility is corroborated by multiple independent sources.
    """
    rank = CONFIDENCE_RANK.get(current, 1)
    if source_count >= 3:
        rank = max(rank, 4)  # → HIGH
    elif source_count >= 2:
        rank = min(rank + 1, 4)  # one tier up
    for label, r in CONFIDENCE_RANK.items():
        if r == rank:
            return label
    return current


def deduplicate_facilities(facilities: List[Dict]) -> List[Dict]:
    """
    Remove duplicate facilities extracted by Claude without over-collapsing.
    We use city+country+facility_type as the primary key and then fold entries
    with identical or near-identical raw location strings within that bucket.

    Cross-source corroboration: when the same facility appears from multiple
    independent source URLs, confidence is boosted.
    """
    unique_map: Dict[str, Dict] = {}

    for f in facilities:
        city = str(f.get("city", "")).strip().lower()
        country = str(f.get("country", "")).strip().lower()
        ftype = str(f.get("facility_type", "Unknown")).strip().lower()
        location = str(f.get("facility_location", "")).strip().lower()
        location_norm = " ".join(
            location.replace(",", " ").replace("-", " ").replace("/", " ").split()
        )

        key = f"{city}|{country}|{ftype}|{location_norm}"
        loose_key = f"{city}|{country}|{ftype}|"

        existing_key = None
        for k in unique_map.keys():
            if not k.startswith(loose_key):
                continue
            existing_loc = k.split("|", 3)[-1]
            if not existing_loc or not location_norm:
                existing_key = k
                break
            if location_norm in existing_loc or existing_loc in location_norm:
                existing_key = k
                break

        if existing_key:
            existing = unique_map[existing_key]
            existing_basis = str(existing.get("classification_basis", "")).strip()
            new_basis = str(f.get("classification_basis", "")).strip()
            if new_basis and new_basis not in existing_basis:
                existing["classification_basis"] = (
                    f"{existing_basis}; {new_basis}" if existing_basis else new_basis
                )

            all_urls = set(existing.get("all_source_urls", []))
            new_url = str(f.get("source_url", "")).strip()
            if new_url:
                all_urls.add(new_url)
            existing_url = str(existing.get("source_url", "")).strip()
            if existing_url:
                all_urls.add(existing_url)
            all_urls.discard("")

            existing["all_source_urls"] = sorted(all_urls)
            existing["source_count"] = len(all_urls)

            # Keep the higher-confidence entry's base fields
            if CONFIDENCE_RANK.get(f.get("confidence", ""), 0) > CONFIDENCE_RANK.get(existing.get("confidence", ""), 0):
                existing["confidence"] = f["confidence"]
                existing["source_url"] = f.get("source_url", existing.get("source_url", ""))
        else:
            new_url = str(f.get("source_url", "")).strip()
            f["all_source_urls"] = [new_url] if new_url else []
            f["source_count"] = 1
            unique_map[key] = f

    # Apply cross-source corroboration boost (silently — keep basis clean)
    for entry in unique_map.values():
        src_count = entry.get("source_count", 1)
        if src_count >= 2:
            old_conf = entry.get("confidence", "ESTIMATED")
            new_conf = _boost_confidence(old_conf, src_count)
            if old_conf != new_conf:
                entry["confidence"] = new_conf
                entry["confidence_boost_reason"] = f"{src_count} independent sources"

    return list(unique_map.values())
