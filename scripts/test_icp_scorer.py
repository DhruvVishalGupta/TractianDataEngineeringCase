"""
ICP scorer inline unit tests.
Tests known-answer cases for each scoring dimension and the combined scorer.
Run from project root: python scripts/test_icp_scorer.py
"""
import sys
sys.path.insert(0, ".")

from src.pipeline.icp_scorer import (
    score_industry_fit,
    score_operational_scale,
    score_physical_footprint,
    score_equipment_dependency,
    calculate_icp_score,
)

passed = 0
failed = 0


def check(name: str, got, expected, field: str = "score"):
    global passed, failed
    actual = getattr(got, field) if hasattr(got, field) else got
    if actual == expected:
        print(f"  PASS {name}")
        passed += 1
    else:
        print(f"  FAIL {name} — expected {field}={expected!r}, got {actual!r}")
        failed += 1


# ── Industry fit ──────────────────────────────────────────────────────────────
# Top-tier: food & beverage keywords → score 4
check("industry_fit: food processing",
      score_industry_fit("meat processing and poultry plant operations"),
      4)

# Top-tier: chemical → score 4
check("industry_fit: petrochemical",
      score_industry_fit("petrochemical polymer and resin manufacturing"),
      4)

# Mid-tier: pharma → score 3
check("industry_fit: pharmaceutical",
      score_industry_fit("pharmaceutical drug manufacturing and biopharmaceutical R&D"),
      3)

# Low-tier: SaaS → score 0
check("industry_fit: saas",
      score_industry_fit("cloud saas software platform fintech payment processing"),
      0)

# Empty text → score 0
check("industry_fit: empty",
      score_industry_fit(""),
      0)

# ── Operational scale ────────────────────────────────────────────────────────
# Large enterprise: ≥10k employees AND ≥$1B revenue → score 3
check("op_scale: large enterprise",
      score_operational_scale(155000, 177.0),
      3)

# Mid-market: ≥1k employees → score 2
check("op_scale: mid-market employees",
      score_operational_scale(5000, 0.05),
      2)

# Small: ≥100 employees → score 1
check("op_scale: small",
      score_operational_scale(200, 0.005),
      1)

# No data → score 0
check("op_scale: no data",
      score_operational_scale(None, None),
      0)

# ── Physical footprint ───────────────────────────────────────────────────────
# ≥5 facilities → score 2
check("footprint: 10 facilities",
      score_physical_footprint(10),
      2)

# 2–4 → score 1
check("footprint: 3 facilities",
      score_physical_footprint(3),
      1)

# 0 → score 0
check("footprint: 0 facilities",
      score_physical_footprint(0),
      0)

# ── Equipment dependency ─────────────────────────────────────────────────────
# Matching keywords → score 1
check("equipment: motor and pump found",
      score_equipment_dependency("The plant uses high-speed motors, centrifugal pumps, and compressors."),
      1)

# No matching keywords → score 0
check("equipment: no keywords",
      score_equipment_dependency("This is a software company with no industrial equipment."),
      0)

# ── Combined scorer ──────────────────────────────────────────────────────────
# Dow Chemical-like profile → expect score 10 (capped)
dow_score = calculate_icp_score(
    company_name="TestCo Chemical",
    industry_text="petrochemical polymer resin manufacturing ethylene",
    employees=37000,
    revenue_billions=55.0,
    confirmed_facility_count=12,
    equipment_evidence_text="pumps compressors turbines rotating equipment motors boilers",
)
check("combined: high ICP (chemical giant)", dow_score, 10, "total")

# Salesforce-like profile → expect score 0
sfdc_score = calculate_icp_score(
    company_name="TestCo SaaS",
    industry_text="cloud saas crm software platform",
    employees=80000,
    revenue_billions=35.0,
    confirmed_facility_count=1,
    equipment_evidence_text="",
)
# Industry fit = 0, footprint = 0, equipment = 0, scale = 3 → total = 3
check("combined: low ICP (saas)", sfdc_score, 3, "total")

# Verify plain_english is non-empty
assert dow_score.plain_english.strip(), "plain_english is empty for high-ICP case"
print("  PASS combined: plain_english non-empty")
passed += 1

print(f"\nICP scorer tests: {passed}/{passed + failed} passed")
if failed > 0:
    sys.exit(1)
