"""
ICP Scoring Engine — implements the full 4-dimension scoring rubric.

All inputs are discovered at runtime through the data collection layer.
No hardcoded per-company data anywhere in this file.

Dimensions:
  Industry Fit        0-4 pts  (most important)
  Operational Scale   0-3 pts
  Physical Footprint  0-2 pts
  Equipment Dependency 0-1 pt
  Total: 0-10 pts capped
"""
from __future__ import annotations
from typing import Optional
from .schema import ICPScore, ScoreDimension
from .logger import get_logger

log = get_logger("icp_scorer")

# ── Industry fit keyword map (from brief rubric) ───────────────────────────────
# These are RUBRIC PARAMETERS from the case brief, not per-company data.
# Score is determined by matching discovered industry keywords against these tiers.
INDUSTRY_FIT_TIERS: list[tuple[int, list[str]]] = [
    (4, [
        "food", "beverage", "brewing", "distill", "dairy", "meat processing",
        "poultry", "grain", "flour", "sugar", "edible oil", "vegetable oil",
        "chemical", "petrochemical", "polymer", "resin", "fertilizer", "phosphate",
        "ammonia", "ethylene", "specialty chemical", "agrochem",
        "pulp", "paper", "paperboard", "containerboard",
        "mining", "mineral", "phosphate mining", "potash", "iron ore", "coal mining",
        "steel", "metal", "aluminum", "copper", "zinc", "iron", "smelting",
        "casting", "forging", "rolling mill",
        "cement", "concrete", "aggregates",
        "automotive", "automobile", "vehicle manufacturing",
        "oil and gas", "oil refin", "gas refin", "petroleum refin",
        "agriculture processing", "oilseed", "milling",
    ]),
    (3, [
        "pharmaceutical", "pharma", "biopharmaceutical", "drug manufacturing",
        "plastic", "rubber", "elastomer", "tire manufacturing",
        "water treatment", "wastewater", "water utility",
        "textile", "apparel manufacturing",
    ]),
    (2, [
        "general manufacturing", "industrial manufacturing",
        "logistics", "warehousing", "freight", "supply chain",
        "aerospace manufacturing", "defense manufacturing",
        "electronics manufacturing", "semiconductor fabrication",
        "packaging manufacturing", "container manufacturing",
    ]),
    (1, [
        "retail distribution", "wholesale distribution", "construction",
        "defense", "building materials",
    ]),
    (0, [
        "software", "saas", "cloud", "fintech", "financial technology",
        "payment processing", "media", "streaming", "social network",
        "consulting", "professional services", "hospitality", "hotel",
        "restaurant", "fast food", "food service", "travel", "marketplace",
        "e-commerce platform", "advertising technology", "insurance technology",
    ]),
]

# Equipment keywords that indicate Tractian-relevant rotating machinery
EQUIPMENT_KEYWORDS = [
    "motor", "pump", "compressor", "conveyor", "turbine", "mixer",
    "crusher", "centrifuge", "kiln", "blower", "fan", "gearbox",
    "agitator", "extruder", "press", "mill", "grinder", "dryer",
    "boiler", "heat exchanger", "reactor", "distillation", "fermentation",
    "rotating equipment", "vibration", "predictive maintenance",
    "condition monitoring", "bearing", "shaft", "impeller", "rotor",
    "reciprocating", "screw conveyor", "bucket elevator", "ball mill",
    "jaw crusher", "roller press", "blast furnace", "electric arc furnace",
    "paper machine", "recovery boiler", "digester",
]


def score_industry_fit(industry_text: str) -> ScoreDimension:
    """
    Score industry fit (0-4) based on discovered industry description text.
    Checks discovered text against rubric tiers — highest matching tier wins.
    """
    text_lower = industry_text.lower()
    best_score = 0
    best_evidence = "No matching industry keywords found in discovered data"

    for score, keywords in INDUSTRY_FIT_TIERS:
        for kw in keywords:
            if kw in text_lower:
                if score > best_score:
                    best_score = score
                    best_evidence = f"Discovered industry keyword: '{kw}' in company description/search results"

    confidence = "HIGH" if best_score > 0 else "MED" if industry_text.strip() else "LOW"
    return ScoreDimension(
        dimension="Industry Fit",
        score=best_score,
        max_score=4,
        evidence=best_evidence,
        confidence=confidence,
    )


def score_operational_scale(
    employees: Optional[int],
    revenue_billions: Optional[float],
    employee_text: str = "",
    revenue_text: str = "",
) -> ScoreDimension:
    """
    Score operational scale (0-3) from discovered firmographic data.
    - 3: ≥10,000 employees AND ≥$1B revenue
    - 2: 1,000–9,999 employees OR $100M–$999M revenue
    - 1: 100–999 employees OR $10M–$99M revenue
    - 0: <100 employees, <$10M revenue, or no data
    """
    if employees is None and revenue_billions is None:
        return ScoreDimension(
            dimension="Operational Scale",
            score=0,
            max_score=3,
            evidence="No employee count or revenue data discovered after exhaustive search of company website, Wikipedia, and financial sources",
            confidence="LOW",
        )

    emp = employees or 0
    rev = revenue_billions or 0.0

    emp_display = employee_text or f"{emp:,}"
    rev_display = revenue_text or f"${rev:.1f}B"

    if emp >= 10_000 and rev >= 1.0:
        score = 3
        evidence = (
            f"{emp_display} employees and {rev_display} annual revenue (discovered from public sources). "
            "Qualifies for dedicated maintenance engineering teams and formal PdM budget allocation."
        )
    elif emp >= 1_000 or rev >= 0.1:
        score = 2
        evidence = (
            f"{emp_display} employees and {rev_display} revenue (discovered from public sources). "
            "Mid-market scale with likely dedicated maintenance function."
        )
    elif emp >= 100 or rev >= 0.01:
        score = 1
        evidence = (
            f"{emp_display} employees and {rev_display} revenue (discovered from public sources). "
            "Smaller organization — maintenance budget likely limited."
        )
    else:
        score = 0
        evidence = (
            f"{emp_display} employees and {rev_display} revenue. "
            "Below threshold for predictive maintenance investment."
        )

    confidence = "HIGH" if (employees is not None and revenue_billions is not None) else "MED"
    return ScoreDimension(
        dimension="Operational Scale",
        score=score,
        max_score=3,
        evidence=evidence,
        confidence=confidence,
    )


def score_physical_footprint(confirmed_facility_count: int) -> ScoreDimension:
    """
    Score physical footprint (0-2) based on facilities discovered at runtime.
    - 2: ≥5 confirmed manufacturing/processing/packaging/refining facilities
    - 1: 2–4 confirmed facilities, or strong evidence of industrial concentration
    - 0: single location or all corporate offices
    """
    if confirmed_facility_count >= 5:
        score = 2
        evidence = (
            f"{confirmed_facility_count} confirmed manufacturing/processing/packaging/refining facilities "
            "discovered across website, SEC filings, and search sources. High expansion potential for Tractian sensors."
        )
        confidence = "HIGH"
    elif confirmed_facility_count >= 2:
        score = 1
        evidence = (
            f"{confirmed_facility_count} confirmed facilities discovered. "
            "Moderate footprint — some sensor expansion potential."
        )
        confidence = "MED"
    elif confirmed_facility_count == 1:
        score = 0
        evidence = "Only one facility discovered — single-site operation or insufficient data for multi-site confirmation."
        confidence = "LOW"
    else:
        score = 0
        evidence = "No confirmed production facilities discovered after exhausting all available sources."
        confidence = "LOW"

    return ScoreDimension(
        dimension="Physical Footprint",
        score=score,
        max_score=2,
        evidence=evidence,
        confidence=confidence,
    )


def score_equipment_dependency(equipment_evidence_text: str) -> ScoreDimension:
    """
    Score equipment dependency signal (0-1) from discovered content.
    Looks for evidence of specific rotating machinery Tractian sensors target.
    Input is concatenated text from job postings, press releases, descriptions, etc.
    """
    text_lower = equipment_evidence_text.lower()
    found_keywords = [kw for kw in EQUIPMENT_KEYWORDS if kw in text_lower]

    if found_keywords:
        # Take up to 5 most specific keywords for evidence
        display = found_keywords[:5]
        return ScoreDimension(
            dimension="Equipment Dependency",
            score=1,
            max_score=1,
            evidence=(
                f"Evidence of rotating machinery found in discovered content: "
                f"{', '.join(display)}. "
                "These are the specific asset types Tractian's vibration sensors are designed to monitor."
            ),
            confidence="HIGH" if len(found_keywords) >= 3 else "MED",
        )

    if equipment_evidence_text.strip():
        return ScoreDimension(
            dimension="Equipment Dependency",
            score=0,
            max_score=1,
            evidence="No evidence of heavy industrial rotating machinery found in scraped content, job postings, or press releases",
            confidence="MED",
        )

    return ScoreDimension(
        dimension="Equipment Dependency",
        score=0,
        max_score=1,
        evidence="Insufficient content discovered to assess equipment dependency",
        confidence="LOW",
    )


def compute_score_confidence(dimensions: list[ScoreDimension]) -> str:
    """Overall score confidence based on how many dimensions had good data."""
    high_count = sum(1 for d in dimensions if d.confidence == "HIGH")
    med_count = sum(1 for d in dimensions if d.confidence in ("HIGH", "MED"))
    if high_count >= 3:
        return "HIGH"
    elif med_count >= 2:
        return "MED"
    else:
        return "LOW"


def build_plain_english(
    company_name: str,
    total: int,
    industry: ScoreDimension,
    scale: ScoreDimension,
    footprint: ScoreDimension,
    equipment: ScoreDimension,
) -> str:
    """Generate a salesperson-readable score summary."""
    parts = [
        f"{company_name} scored {total}/10 on Tractian's ICP rubric.",
        f"Industry Fit {industry.score}/4: {industry.evidence}",
        f"Operational Scale {scale.score}/3: {scale.evidence}",
        f"Physical Footprint {footprint.score}/2: {footprint.evidence}",
        f"Equipment Dependency {equipment.score}/1: {equipment.evidence}",
    ]

    if total >= 8:
        parts.append("RECOMMENDATION: High-priority target — assign to senior AE immediately.")
    elif total >= 5:
        parts.append("RECOMMENDATION: Mid-priority — qualify further with a discovery call.")
    else:
        parts.append("RECOMMENDATION: Low priority — deprioritize unless a specific opportunity arises.")

    return " | ".join(parts)


def calculate_icp_score(
    company_name: str,
    industry_text: str,
    employees: Optional[int],
    revenue_billions: Optional[float],
    confirmed_facility_count: int,
    equipment_evidence_text: str,
    employee_text: str = "",
    revenue_text: str = "",
) -> ICPScore:
    """
    Main entry point. All inputs are discovered at runtime — never hardcoded.

    Args:
        company_name: company name (for logging only)
        industry_text: concatenated text describing the company's industry
                       (from Wikipedia, About page, search snippets, SIC description)
        employees: discovered employee count or None
        revenue_billions: discovered revenue in $B or None
        confirmed_facility_count: count of non-office facilities discovered
        equipment_evidence_text: text containing machinery mentions
                                 (job postings, press releases, product pages)
        employee_text: raw text form of employee count (e.g. "155,000")
        revenue_text: raw text form of revenue (e.g. "$177B")
    """
    industry = score_industry_fit(industry_text)
    scale = score_operational_scale(employees, revenue_billions, employee_text, revenue_text)
    footprint = score_physical_footprint(confirmed_facility_count)
    equipment = score_equipment_dependency(equipment_evidence_text)

    total = min(10, industry.score + scale.score + footprint.score + equipment.score)
    confidence = compute_score_confidence([industry, scale, footprint, equipment])
    summary = build_plain_english(company_name, total, industry, scale, footprint, equipment)

    log.info(f"[{company_name}] ICP Score: {total}/10 (confidence: {confidence})")

    return ICPScore(
        total=total,
        industry_fit=industry,
        operational_scale=scale,
        physical_footprint=footprint,
        equipment_dependency=equipment,
        score_confidence=confidence,
        plain_english=summary,
    )
