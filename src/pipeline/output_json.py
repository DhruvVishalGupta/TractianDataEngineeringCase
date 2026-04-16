"""
JSON output module — writes tractian_leads.json for dashboard consumption.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, UTC
from .config import OUTPUTS_DIR
from .logger import get_logger

log = get_logger("output_json")


def write_json(
    rows: list[dict],
    path: Path | None = None,
    company_summaries: list[dict] | None = None,
) -> Path:
    """Write final rows to JSON with nested structure for dashboard."""
    path = path or (OUTPUTS_DIR / "tractian_leads.json")

    if company_summaries is None:
        # Build company-grouped structure from rows (legacy behavior).
        companies = {}
        for row in rows:
            cn = row.get("company_name", "Unknown")
            if cn not in companies:
                breakdown = row.get("score_breakdown", {})
                if isinstance(breakdown, str):
                    try:
                        breakdown = json.loads(breakdown)
                    except Exception:
                        breakdown = {}
                companies[cn] = {
                    "company_name": cn,
                    "website": row.get("website", ""),
                    "icp_score": row.get("icp_score", 0),
                    "score_breakdown": breakdown,
                    "facilities": [],
                }
            companies[cn]["facilities"].append({
                "facility_location": row.get("facility_location", ""),
                "city": row.get("city"),
                "state_region": row.get("state_region"),
                "country": row.get("country"),
                "lat": row.get("lat"),
                "lon": row.get("lon"),
                "facility_type": row.get("facility_type", "Unknown"),
                "classification_basis": row.get("classification_basis", ""),
                "confidence": row.get("confidence", "LOW"),
                "needs_verification": row.get("needs_verification", True),
                "source_url": row.get("source_url", ""),
                "source_type": row.get("source_type", ""),
                "source_count": row.get("source_count", 0),
                "date_collected": row.get("date_collected", ""),
            })
        companies_list = list(companies.values())
    else:
        companies_list = company_summaries

    output = {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_companies": len(companies_list),
            "total_facilities": len(rows),
            "pipeline_version": "1.0",
        },
        "companies": companies_list,
        "flat_rows": rows,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    log.info(f"JSON written: {path} ({len(rows)} rows, {len(companies_list)} companies)")
    return path
