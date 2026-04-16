"""
CSV output module — writes tractian_leads.csv.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from .config import OUTPUTS_DIR
from .logger import get_logger

log = get_logger("output_csv")

CSV_COLUMNS = [
    # ── PDF sample columns, in PDF order, for direct CRM/map import ──
    "company_name", "website", "icp_score", "facility_location", "facility_type",
    # ── Location breakdown (map-ready) ──
    "city", "state_region", "country", "lat", "lon",
    # ── Confidence + provenance ──
    "classification_basis", "confidence", "needs_verification",
    "source_url", "source_type", "source_count",
    "osint_corroboration", "primary_source_tier",
    # ── Extra context ──
    "reclassification_note", "confidence_boost_reason",
    "score_breakdown", "date_collected",
]


def write_csv(rows: list[dict], path: Path | None = None) -> Path:
    """Write final rows to CSV. Returns path to written file."""
    path = path or (OUTPUTS_DIR / "tractian_leads.csv")

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for row in rows:
            # Convert score_breakdown dict to JSON string for CSV
            row_copy = dict(row)
            if isinstance(row_copy.get("score_breakdown"), dict):
                row_copy["score_breakdown"] = json.dumps(row_copy["score_breakdown"])
            # Convert needs_verification to string
            if isinstance(row_copy.get("needs_verification"), bool):
                row_copy["needs_verification"] = str(row_copy["needs_verification"])
            writer.writerow(row_copy)

    log.info(f"CSV written: {path} ({len(rows)} rows)")
    return path
