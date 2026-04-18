"""
FastAPI backend — serves tractian_leads.json as REST API,
plus a /demo endpoint that runs the pipeline live for a single user-supplied
company so the dashboard can demo the pipeline end-to-end in-browser.

Usage:
    uvicorn src.api.main:app --reload --port 8000
"""
from __future__ import annotations
import json
import re
import threading
import traceback
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

app = FastAPI(
    title="Tractian GTM Sales Intelligence API",
    description="REST API for the Tractian facility and ICP scoring pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT = Path(__file__).parent.parent.parent
DATA_PATH = ROOT / "outputs" / "tractian_leads.json"

_data_cache: dict | None = None
_data_cache_mtime: float | None = None


def _load_data() -> dict:
    global _data_cache, _data_cache_mtime
    current_mtime = DATA_PATH.stat().st_mtime if DATA_PATH.exists() else None
    cache_stale = _data_cache is None or _data_cache_mtime != current_mtime

    if cache_stale:
        if DATA_PATH.exists():
            try:
                with open(DATA_PATH, encoding="utf-8") as f:
                    _data_cache = json.load(f)
                _data_cache_mtime = current_mtime
            except json.JSONDecodeError:
                # File was mid-write (race condition); serve stale cache if available
                if _data_cache is None:
                    _data_cache = {"metadata": {}, "companies": [], "flat_rows": []}
        else:
            _data_cache = {"metadata": {}, "companies": [], "flat_rows": []}
            _data_cache_mtime = None
    return _data_cache


def _persist_data(data: dict) -> None:
    """Write to a temp file then atomically replace, so readers never see a partial write."""
    global _data_cache, _data_cache_mtime
    tmp = DATA_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    tmp.replace(DATA_PATH)  # atomic on both POSIX and Windows
    _data_cache = data
    _data_cache_mtime = DATA_PATH.stat().st_mtime


# ── Standard read endpoints ──────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "api": "Tractian GTM Sales Intelligence", "version": "1.0"}


@app.get("/leads")
def get_leads(
    score_min: Optional[int] = Query(None, ge=0, le=10),
    score_max: Optional[int] = Query(None, ge=0, le=10),
    facility_type: Optional[str] = None,
    country: Optional[str] = None,
    confidence: Optional[str] = None,
    company: Optional[str] = None,
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    data = _load_data()
    rows = data.get("flat_rows", [])

    if score_min is not None:
        rows = [r for r in rows if r.get("icp_score", 0) >= score_min]
    if score_max is not None:
        rows = [r for r in rows if r.get("icp_score", 0) <= score_max]
    if facility_type:
        rows = [r for r in rows if r.get("facility_type", "").lower() == facility_type.lower()]
    if country:
        rows = [r for r in rows if country.lower() in (r.get("country") or "").lower()]
    if confidence:
        rows = [r for r in rows if r.get("confidence", "").upper() == confidence.upper()]
    if company:
        rows = [r for r in rows if company.lower() in r.get("company_name", "").lower()]

    total = len(rows)
    paginated = rows[offset:offset + limit]
    return {"total": total, "limit": limit, "offset": offset, "leads": paginated}


@app.get("/companies")
def get_companies():
    data = _load_data()
    return sorted(
        [
            {
                "company_name": c["company_name"],
                "website": c.get("website", ""),
                "icp_score": c.get("icp_score", 0),
                "facility_count": len(c.get("facilities", [])),
                "score_breakdown": c.get("score_breakdown", {}),
            }
            for c in data.get("companies", [])
        ],
        key=lambda x: x["icp_score"],
        reverse=True,
    )


@app.get("/companies/{name}")
def get_company(name: str):
    data = _load_data()
    target = name.lower().replace(" ", "-")
    for c in data.get("companies", []):
        if c["company_name"].lower().replace(" ", "-") == target:
            return c
    return {"error": f"Company '{name}' not found"}


@app.get("/stats")
def get_stats():
    data = _load_data()
    rows = data.get("flat_rows", [])
    companies = data.get("companies", [])
    if not rows:
        return {"total_companies": 0, "total_facilities": 0}
    scores = [r.get("icp_score", 0) for r in rows]
    return {
        "total_companies": len(companies),
        "total_facilities": len(rows),
        "avg_icp_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "high_value_targets": len([c for c in companies if c.get("icp_score", 0) >= 8]),
        "countries": len(set(r.get("country", "") for r in rows if r.get("country"))),
        "confidence_breakdown": {
            "HIGH": len([r for r in rows if r.get("confidence") == "HIGH"]),
            "MED": len([r for r in rows if r.get("confidence") == "MED"]),
            "LOW": len([r for r in rows if r.get("confidence") == "LOW"]),
            "ESTIMATED": len([r for r in rows if r.get("confidence") == "ESTIMATED"]),
        },
    }


@app.get("/download/csv")
def download_csv():
    csv_path = ROOT / "outputs" / "tractian_leads.csv"
    if not csv_path.exists():
        return Response(content="CSV not generated yet", status_code=404)
    return FileResponse(csv_path, media_type="text/csv", filename="tractian_leads.csv")


@app.get("/download/xlsx")
def download_xlsx():
    xlsx_path = ROOT / "outputs" / "tractian_leads.xlsx"
    if not xlsx_path.exists():
        return Response(content="XLSX not generated yet", status_code=404)
    return FileResponse(
        xlsx_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="tractian_leads.xlsx",
    )


@app.get("/distributions")
def get_distributions():
    data = _load_data()
    rows = data.get("flat_rows", [])
    facility_types, confidence_dist, country_dist = {}, {}, {}
    for r in rows:
        ft = r.get("facility_type", "Unknown")
        facility_types[ft] = facility_types.get(ft, 0) + 1
        conf = r.get("confidence", "LOW")
        confidence_dist[conf] = confidence_dist.get(conf, 0) + 1
        country = r.get("country") or "Unknown"
        country_dist[country] = country_dist.get(country, 0) + 1
    return {
        "facility_types": sorted(facility_types.items(), key=lambda x: x[1], reverse=True),
        "confidence": confidence_dist,
        "countries": sorted(country_dist.items(), key=lambda x: x[1], reverse=True)[:20],
    }


# ── Live-demo endpoints ─────────────────────────────────────────────
# In-memory job registry. For a demo this is fine; a real deploy would use Redis.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


class ProcessRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)


STAGE_ORDER = [
    "queued", "discovery", "edgar", "scrape", "extract",
    "firmographics", "validate", "geocode", "score", "persist", "done",
]


def _update_job(job_id: str, **patch):
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(patch)
            history = _jobs[job_id].setdefault("history", [])
            history.append({
                "t": datetime.now(UTC).isoformat(),
                "stage": patch.get("stage", _jobs[job_id].get("stage")),
                "detail": patch.get("detail", ""),
            })


def _run_live_pipeline(job_id: str, req: ProcessRequest):
    """Executed in a background thread by the /demo/process endpoint."""
    try:
        # Late imports so the API can start without the pipeline deps available.
        from src.pipeline.companies import Company
        from src.pipeline.orchestrator import process_company

        from src.pipeline.searcher import discover_company_website

        slug = re.sub(r"[^a-z0-9]+", "_", req.name.lower()).strip("_") or f"demo-{job_id}"

        _update_job(job_id, stage="discovery", detail="Discovering website…", status="running")
        website = discover_company_website(req.name.strip())

        _update_job(job_id, stage="discovery", detail="Starting pipeline", status="running")

        company = Company(
            name=req.name.strip(),
            slug=slug,
            website=website,
        )

        def on_progress(stage: str, detail: str = ""):
            _update_job(job_id, stage=stage, detail=detail)

        rows, summary = process_company(company, on_progress=on_progress)

        _update_job(job_id, stage="persist", detail=f"Saving {len(rows)} row(s) to disk")

        # Append to outputs/tractian_leads.json (overwriting any prior entry with same name).
        data = _load_data()
        companies = [c for c in data.get("companies", []) if c.get("company_name") != req.name]
        flat = [r for r in data.get("flat_rows", []) if r.get("company_name") != req.name]
        companies.append(summary)
        flat.extend(rows)
        data["companies"] = companies
        data["flat_rows"] = flat
        data["metadata"] = data.get("metadata", {}) | {
            "total_companies": len(companies),
            "total_facilities": len(flat),
            "last_live_demo": {
                "company": req.name,
                "at": datetime.now(UTC).isoformat(),
                "rows_added": len(rows),
            },
        }
        _persist_data(data)

        _update_job(
            job_id,
            status="complete",
            stage="done",
            detail=f"Emitted {len(rows)} row(s), ICP {summary['icp_score']}/10",
            result={"rows": rows, "summary": summary},
        )

    except Exception as e:
        tb = traceback.format_exc()
        _update_job(job_id, status="failed", stage="error", detail=str(e), error=tb[:2000])


@app.post("/demo/process")
def demo_process(req: ProcessRequest):
    """
    Kick off the full pipeline for a single user-supplied company.

    Returns a job_id that the client polls via GET /demo/status/{job_id} to see
    per-stage progress. Once the job's status flips to "complete", the new
    company and its facilities are already merged into outputs/tractian_leads.json
    — the dashboard will see them on its next refresh.
    """
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="name is required")

    job_id = uuid.uuid4().hex[:10]
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "detail": "",
            "company_name": req.name,
            "created_at": datetime.now(UTC).isoformat(),
            "history": [],
            "result": None,
            "error": None,
        }

    threading.Thread(target=_run_live_pipeline, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "status": "queued", "stages": STAGE_ORDER}


@app.get("/demo/status/{job_id}")
def demo_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@app.delete("/companies/{name}")
def delete_company(name: str):
    data = _load_data()
    orig_companies = data.get("companies", [])
    orig_rows = data.get("flat_rows", [])
    new_companies = [c for c in orig_companies if c.get("company_name") != name]
    new_rows = [r for r in orig_rows if r.get("company_name") != name]
    if len(new_companies) == len(orig_companies):
        raise HTTPException(status_code=404, detail=f"Company '{name}' not found")
    data["companies"] = new_companies
    data["flat_rows"] = new_rows
    data["metadata"] = data.get("metadata", {}) | {
        "total_companies": len(new_companies),
        "total_facilities": len(new_rows),
    }
    _persist_data(data)
    return {"deleted": name, "companies_remaining": len(new_companies)}
