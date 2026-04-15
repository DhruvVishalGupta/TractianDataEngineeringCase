"""
Ollama end-to-end smoke test.
Calls classify_facility with three real location strings and asserts:
- Returns an OllamaFacilityResponse (not None)
- facility_type is one of the valid taxonomy values
- confidence is one of HIGH / MED / LOW / ESTIMATED
- facility_location is a non-empty string
Run from project root: python scripts/test_ollama.py
"""
import sys
sys.path.insert(0, ".")

from src.pipeline.ollama_client import classify_facility
from src.pipeline.schema import OllamaFacilityResponse

VALID_TYPES = {
    "Manufacturing Plant", "Packaging Plant", "Processing Plant",
    "Distribution Center", "Corporate HQ", "R&D Center", "Sales Office",
    "Refinery", "Mine and Extraction Site", "Power Plant", "Unknown",
}
VALID_CONFIDENCE = {"HIGH", "MED", "LOW", "ESTIMATED"}

TEST_CASES = [
    {
        "company": "Dow Chemical",
        "location": "Freeport, Texas - Dow Chemical manufacturing complex",
        "context": "Dow's largest integrated manufacturing site, producing ethylene and polyethylene.",
        "source_type": "WEBSITE",
        "expect_type_hint": "Manufacturing Plant",
    },
    {
        "company": "Cargill",
        "location": "Wichita, Kansas - Cargill meatpacking and processing plant",
        "context": "Large-scale meat processing facility employing over 2,000 workers.",
        "source_type": "SEARCH",
        "expect_type_hint": "Processing Plant",
    },
    {
        "company": "Salesforce",
        "location": "San Francisco, California - Salesforce Tower headquarters",
        "context": "Global headquarters for Salesforce, a cloud CRM software company.",
        "source_type": "WEBSITE",
        "expect_type_hint": "Corporate HQ",
    },
]

passed = 0
failed = 0

for tc in TEST_CASES:
    result = classify_facility(
        company_name=tc["company"],
        location_text=tc["location"],
        context=tc["context"],
        source_type=tc["source_type"],
    )

    if result is None:
        print(f"  FAIL [{tc['company']}] — Ollama returned None (timeout or parse error)")
        failed += 1
        continue

    assert isinstance(result, OllamaFacilityResponse), "Result is not OllamaFacilityResponse"

    checks = [
        (result.facility_type in VALID_TYPES,
         f"facility_type '{result.facility_type}' not in valid taxonomy"),
        (result.confidence in VALID_CONFIDENCE,
         f"confidence '{result.confidence}' not in valid values"),
        (bool(result.facility_location.strip()),
         "facility_location is empty"),
        (bool(result.classification_basis.strip()),
         "classification_basis is empty"),
    ]

    case_passed = True
    for ok, msg in checks:
        if not ok:
            print(f"  FAIL [{tc['company']}] — {msg}")
            case_passed = False
            failed += 1
            break

    if case_passed:
        print(f"  PASS [{tc['company']}] — {result.facility_type} | {result.confidence} | {result.facility_location}")
        passed += 1

print(f"\nOllama smoke test: {passed}/{passed + failed} passed")
if failed > 0:
    sys.exit(1)
