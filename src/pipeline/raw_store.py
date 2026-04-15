"""
Raw data store — per-company JSON files so the intelligence layer
can be re-run without re-scraping.
"""
import json
import re
from pathlib import Path
from typing import Any

from .config import DATA_RAW_DIR
from .logger import get_logger

log = get_logger("raw_store")


def company_slug(name: str) -> str:
    """Convert company name to filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def get_company_dir(name: str) -> Path:
    slug = company_slug(name)
    d = DATA_RAW_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_raw(company_name: str, key: str, data: Any) -> Path:
    """Save raw data under data/raw/{slug}/{key}.json"""
    p = get_company_dir(company_name) / f"{key}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.debug(f"[{company_name}] Saved raw data → {p.name}")
    return p


def load_raw(company_name: str, key: str) -> Any | None:
    """Load raw data; returns None if not found."""
    p = get_company_dir(company_name) / f"{key}.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def has_raw(company_name: str, key: str) -> bool:
    p = get_company_dir(company_name) / f"{key}.json"
    return p.exists()
