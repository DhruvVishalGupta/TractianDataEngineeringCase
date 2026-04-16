"""
Geocoder — resolves city/state/country strings to (lat, lon) using OpenStreetMap's
Nominatim service. Free, no API key, but requires:
  - User-Agent identifying the app
  - ≤1 request/sec rate limit
  - Aggressive caching (we cache by normalized location string in data/raw/_geocode/)

If Nominatim is unavailable (offline, rate-limited), the geocoder fails open —
returns None and the row simply has no lat/lon.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from typing import Optional
import requests

from .config import DATA_RAW_DIR
from .logger import get_logger

log = get_logger("geocoder")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {
    "User-Agent": "TractianCaseStudy/1.0 research@tractian-case.com",
    "Accept": "application/json",
}
TIMEOUT = 15
RATE_LIMIT_S = 1.1  # be a polite citizen

CACHE_DIR = DATA_RAW_DIR / "_geocode"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = CACHE_DIR / "cache.json"

_cache: dict[str, dict] | None = None
_last_request_t = 0.0


def _load_cache() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    if CACHE_FILE.exists():
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    else:
        _cache = {}
    return _cache


def _flush_cache() -> None:
    if _cache is None:
        return
    CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_key(city: str, state: str, country: str) -> str:
    parts = [p.strip() for p in (city, state, country) if p and p.strip()]
    key = ", ".join(parts).lower()
    return re.sub(r"\s+", " ", key)


def geocode(city: str, state: str = "", country: str = "") -> Optional[dict]:
    """
    Resolve a place to {lat, lon, display_name}. Returns None on failure.
    Cached by normalized "city, state, country" key.
    """
    if not city or not city.strip():
        return None

    cache = _load_cache()
    key = _normalize_key(city, state, country)
    if key in cache:
        result = cache[key]
        return result if result else None

    # Build a polite query
    query_parts = [p.strip() for p in (city, state, country) if p and p.strip()]
    query = ", ".join(query_parts)

    global _last_request_t
    now = time.time()
    wait = RATE_LIMIT_S - (now - _last_request_t)
    if wait > 0:
        time.sleep(wait)

    try:
        resp = requests.get(
            NOMINATIM,
            params={"q": query, "format": "json", "limit": 1, "addressdetails": 0},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        _last_request_t = time.time()
        if resp.status_code != 200:
            log.debug(f"Nominatim HTTP {resp.status_code} for {query!r}")
            cache[key] = {}
            _flush_cache()
            return None

        data = resp.json()
        if not data:
            cache[key] = {}
            _flush_cache()
            return None

        first = data[0]
        result = {
            "lat": float(first.get("lat")),
            "lon": float(first.get("lon")),
            "display_name": first.get("display_name", ""),
        }
        cache[key] = result
        _flush_cache()
        return result
    except Exception as e:
        log.debug(f"Geocode failure for {query!r}: {e}")
        cache[key] = {}
        _flush_cache()
        return None


def geocode_facility(facility: dict) -> dict:
    """Convenience: geocode a facility dict in-place; returns same dict."""
    if facility.get("lat") is not None and facility.get("lon") is not None:
        return facility
    res = geocode(
        facility.get("city", ""),
        facility.get("state_region", "") or "",
        facility.get("country", "") or "",
    )
    if res:
        facility["lat"] = res["lat"]
        facility["lon"] = res["lon"]
    return facility
