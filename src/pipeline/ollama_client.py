"""
Ollama client — structured facility classification using qwen2.5:7b.
Uses Pydantic schemas for deterministic output. Temperature 0.
Retries once on malformed output.
"""
from __future__ import annotations
import json
import re
import time
import requests
from typing import Optional
from .config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TEMPERATURE, OLLAMA_TIMEOUT
from .schema import OllamaFacilityResponse
from .logger import get_logger, log_failure

log = get_logger("ollama")

FACILITY_TYPES = [
    "Manufacturing Plant", "Packaging Plant", "Processing Plant",
    "Distribution Center", "Corporate HQ", "R&D Center", "Sales Office",
    "Refinery", "Mine and Extraction Site", "Power Plant", "Unknown"
]

CONFIDENCE_VALUES = ["HIGH", "MED", "LOW", "ESTIMATED"]


def _build_classification_prompt(
    company_name: str,
    location_text: str,
    context: str,
    source_type: str,
) -> str:
    types_str = "\n".join(f"  - {t}" for t in FACILITY_TYPES)
    return f"""You are a facility classification expert for a B2B sales intelligence system.
Classify this location for {company_name} and return ONLY valid JSON.

Location text: "{location_text}"
Source type: {source_type}
Context: "{context[:500]}"

Return a JSON object with EXACTLY these fields (no extra fields, no markdown):
{{
  "facility_location": "city, state/region, country (fill in what you know)",
  "city": "city name or null",
  "state_region": "state or region or null",
  "country": "country name or null",
  "lat": latitude_as_float_or_null,
  "lon": longitude_as_float_or_null,
  "facility_type": "one of: {' | '.join(FACILITY_TYPES)}",
  "classification_basis": "specific evidence from the source text explaining why this type was chosen",
  "confidence": "one of: HIGH | MED | LOW | ESTIMATED"
}}

Confidence rules:
- HIGH: facility type explicitly labeled in the source (e.g. "packaging plant", "corporate headquarters")
- MED: inferred from strong context (e.g. job postings mentioning manufacturing, press releases about operations)
- LOW: guessed from location name or minimal context
- ESTIMATED: best guess with no supporting context

For lat/lon: provide approximate coordinates for well-known cities. Use null for unknown locations.
Classification_basis must be SPECIFIC — cite actual evidence, not generic phrases.

Return ONLY the JSON object, no explanation, no markdown code blocks."""


def classify_facility(
    company_name: str,
    location_text: str,
    context: str = "",
    source_type: str = "UNKNOWN",
) -> Optional[OllamaFacilityResponse]:
    """
    Classify a single facility using Ollama.
    Returns OllamaFacilityResponse or None on failure.
    """
    prompt = _build_classification_prompt(company_name, location_text, context, source_type)

    for attempt in range(2):
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt if attempt == 0 else prompt + "\n\nIMPORTANT: Return ONLY the JSON object. Nothing else.",
                    "stream": False,
                    "options": {"temperature": OLLAMA_TEMPERATURE},
                },
                timeout=OLLAMA_TIMEOUT,
            )

            if resp.status_code != 200:
                log.warning(f"[{company_name}] Ollama returned {resp.status_code}")
                continue

            raw_response = resp.json().get("response", "")
            parsed = _parse_ollama_json(raw_response, company_name)

            if parsed:
                return parsed

            if attempt == 0:
                log.debug(f"[{company_name}] Retrying with stricter prompt...")
                time.sleep(0.5)

        except requests.exceptions.Timeout:
            log.warning(f"[{company_name}] Ollama timeout on attempt {attempt + 1}")
        except Exception as e:
            log.warning(f"[{company_name}] Ollama error: {e}")

    log.error(f"[{company_name}] Ollama classification failed for: {location_text[:60]}")
    log_failure(company_name, "ollama_classify", f"Failed to classify: {location_text[:60]}")
    return None


def _parse_ollama_json(raw: str, company_name: str) -> Optional[OllamaFacilityResponse]:
    """Parse JSON from Ollama response, handling common formatting issues."""
    # Strip markdown code blocks if present
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip()
    raw = raw.strip('`').strip()

    # Find the JSON object
    json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if not json_match:
        log.debug(f"[{company_name}] No JSON object found in: {raw[:100]}")
        return None

    try:
        data = json.loads(json_match.group())

        # Validate and normalize facility_type
        ft = data.get("facility_type", "Unknown")
        if ft not in FACILITY_TYPES:
            # Try fuzzy match
            ft_lower = ft.lower()
            matched = None
            for valid_type in FACILITY_TYPES:
                if valid_type.lower() in ft_lower or ft_lower in valid_type.lower():
                    matched = valid_type
                    break
            data["facility_type"] = matched or "Unknown"

        # Normalize confidence
        conf = data.get("confidence", "LOW").upper()
        if conf not in CONFIDENCE_VALUES:
            conf = "LOW"
        data["confidence"] = conf

        # Ensure classification_basis is specific
        basis = data.get("classification_basis", "")
        if len(basis) < 10:
            data["classification_basis"] = f"Classified from source text: {data.get('facility_location', 'unknown location')}"

        # Validate lat/lon
        for coord in ["lat", "lon"]:
            val = data.get(coord)
            if val is not None:
                try:
                    data[coord] = float(val)
                    if coord == "lat" and not (-90 <= data[coord] <= 90):
                        data[coord] = None
                    elif coord == "lon" and not (-180 <= data[coord] <= 180):
                        data[coord] = None
                except (TypeError, ValueError):
                    data[coord] = None

        return OllamaFacilityResponse(**data)

    except (json.JSONDecodeError, Exception) as e:
        log.debug(f"[{company_name}] JSON parse error: {e} | Raw: {raw[:100]}")
        return None


def batch_classify_facilities(
    company_name: str,
    candidates: list[dict],
    max_candidates: int = 30,
) -> list[OllamaFacilityResponse]:
    """
    Classify multiple facility candidates for a company.
    Returns list of successful classifications.
    """
    results = []
    to_process = candidates[:max_candidates]

    log.info(f"[{company_name}] Classifying {len(to_process)} facility candidates via Ollama...")

    for i, candidate in enumerate(to_process):
        location_text = candidate.get("raw_text", "")
        context = candidate.get("context", "")
        source_type = candidate.get("source_type", "UNKNOWN")

        classified = classify_facility(company_name, location_text, context, source_type)
        if classified:
            results.append(classified)

        # Small delay to not overwhelm local Ollama
        if i % 5 == 4:
            time.sleep(0.2)

    log.info(f"[{company_name}] Successfully classified {len(results)}/{len(to_process)} facilities")
    return results
