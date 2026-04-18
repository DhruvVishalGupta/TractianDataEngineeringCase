"""
ICP Scoring Engine — implements the 4-dimension scoring rubric.

Scores must spread 1-10 in line with the case sample (Kalshi 1, McD 3, Apple 5,
SpaceX 7, Cargill/Dow 10). The prior version saturated everything at 10/10
because (a) industry-fit tier 4 was over-inclusive, (b) footprint hit 2/2 with
just 5 facilities, and (c) market_research added an unconditional +1.

All inputs are discovered at runtime through the data collection layer.
No hardcoded per-company data anywhere in this file.

Dimensions:
  Industry Fit         0-4 pts  (most important)
  Operational Scale    0-3 pts
  Physical Footprint   0-2 pts
  Equipment Dependency 0-1 pt
  Market modifier      -1 / 0 / +1  (only when signals are clear-cut)
  Total: 0-10 pts (clamped)
"""
from __future__ import annotations
from typing import Optional
import re
from .schema import ICPScore, ScoreDimension
from .logger import get_logger

log = get_logger("icp_scorer")


def _sanitize_display(text: str) -> str:
    """Strip residual wikitext/HTML noise from firmographic display text."""
    if not text:
        return ""
    s = re.sub(r"\{\{[^}]*\}\}", "", text)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\|[a-z_]+=\S*", "", s)
    s = re.sub(r"\b(first|last|date|url|title|access[-_]?date)=\S*", "", s)
    s = s.replace("}}", "").replace("{{", "")
    # Pipes are wikitext field separators — any that survive the targeted regexes
    # above are leftover noise. Drop them so downstream renderers can safely
    # treat `|` as a structural separator.
    s = s.replace("|", " ")
    s = re.sub(r"\s+", " ", s).strip().strip("|").strip()
    return s if s else ""


# ── Industry fit keyword map ────────────────────────────────────────────────
# Tier 4 — heavy process industries with massive rotating-equipment exposure.
# These are Tractian's bullseye: refining, mining, steel, cement, chemicals,
# pulp/paper, food/beverage processing.
TIER_4_KEYWORDS = [
    # Chemicals / petrochemicals
    "petrochemical", "chemical company", "specialty chemical", "polymer",
    "polyethylene", "polypropylene", "ethylene", "resin manufactur",
    "agrochem", "fertilizer", "ammonia",
    # Refining & oil-gas
    "oil refin", "petroleum refin", "refinery", "natural gas processing",
    "lng", "liquefied natural gas",
    # Mining & metals
    "mining", "mineral", "phosphate", "potash", "iron ore", "coal mining",
    "steel manufactur", "steel mill", "steelmaker", "smelting", "smelter",
    "aluminum smelt", "copper smelt", "rolling mill", "blast furnace",
    "iron and steel",
    # Pulp & paper
    "pulp and paper", "paper mill", "containerboard", "corrugated packaging",
    "paperboard", "kraft paper", "paper products", "pulp manufactur",
    "paper manufactur",
    # Cement
    "cement manufactur", "cement plant", "concrete production",
    # Food & beverage processing (capital-intensive lines).
    # NOTE: "food" alone is intentionally absent — it would match McDonald's "Fast food"
    # and inflate restaurants. We require either compound food terms (food processing,
    # food manufacturing, consumer foods, packaged food, etc.) or specific product
    # categories (meat, dairy, snack, etc.).
    "beverage", "beverages", "brewing", "brewery", "beer",
    "meat processing", "meatpacker", "poultry processing",
    "beef processing", "pork processing",
    "meat products", "poultry products", "dairy products",
    "frozen meat", "fresh meat", "meatpacking",
    "grain milling", "flour milling", "sugar refin", "sugar mill",
    "edible oil", "vegetable oil", "oilseed crush", "soybean crush",
    "dairy processing", "distillery", "bottling plant",
    "beverage manufactur", "snack food", "snack", "confection", "confectionery",
    "biscuit", "chocolate", "cereal", "frozen food", "prepared food",
    "packaged food", "specialty food", "consumer foods", "consumer food",
    "food processing", "food and beverage", "food and beverage manufactur",
    "food manufactur", "food company", "global food",
    "meat company", "meat production", "protein company",
    "chicken processor", "chicken processing", "processing plants",
    "processing facility", "processing facilities",
    # Chemicals (added "chemical" / "chemicals" to catch Wikipedia "Chemicals" string)
    "chemical", "chemicals", "industrial chemical",
    # Heavy equipment & engines (Caterpillar, Cummins style)
    "heavy equipment", "heavy equipment manufactur", "heavy machinery",
    "construction equipment manufactur", "construction machinery",
    "engine manufactur", "engines", "turbine manufactur", "industrial machinery",
    "earth moving", "earthmoving", "mining equipment",
    # Automotive (final assembly is rotating-equipment dense)
    "automotive manufactur", "automobile manufactur", "vehicle assembly",
    "auto parts manufactur",
    # Industrial packaging materials
    "packaging materials", "protective packaging", "food packaging",
    "cryovac",
]

# Tier 3 — strong industrial fit but lighter rotating-equipment density,
# OR FMCG conglomerates whose plants are mostly bottling/packaging-focused.
TIER_3_KEYWORDS = [
    "consumer packaged goods", "fmcg", "fast-moving consumer goods",
    "consumer goods", "household products", "personal care",
    "home care", "hygiene", "diaper", "tissue", "oral care",
    "soap", "shampoo", "detergent", "cleaning products",
    "pharmaceutical manufactur", "biopharmaceutical", "drug manufactur",
    "tire manufactur", "rubber manufactur", "plastic manufactur",
    "glass manufactur", "bottle manufactur",
    "water treatment", "wastewater",
    "textile manufactur", "apparel manufactur",
]

# Tier 2 — generic manufacturing, aerospace, logistics, semiconductors.
TIER_2_KEYWORDS = [
    "general manufactur", "industrial manufactur",
    "aerospace", "space launch", "rocket", "defense manufactur",
    "semiconductor fabrication", "electronics manufactur",
    "logistics", "warehousing", "freight", "supply chain",
    "shipping", "transportation",
    "diversified manufactur", "industrial conglomerate",
]

# Tier 1 — companies with physical operations but where Tractian's vibration
# sensors are a marginal fit (retail back-of-house, restaurants, building
# materials wholesale, small-batch food prep).
TIER_1_KEYWORDS = [
    "retail", "wholesale", "supermarket", "grocery store", "department store",
    "construction services", "building materials wholesale",
    "fast food", "quick service restaurant", "qsr", "restaurant chain",
    "food service",
]

# Tier 0 — pure software, marketplace, or services. No industrial assets.
TIER_0_KEYWORDS = [
    "software", "saas", "cloud computing", "enterprise software",
    "fintech", "payment processor", "financial services",
    "media streaming", "audio streaming", "podcasting", "video streaming",
    "social network", "social media",
    "marketplace", "vacation rental", "home sharing", "lodging marketplace",
    "consulting", "professional services",
    "advertising technology", "e-commerce platform",
    "mobile app", "internet platform",
]

INDUSTRY_FIT_TIERS: list[tuple[int, list[str]]] = [
    (4, TIER_4_KEYWORDS),
    (3, TIER_3_KEYWORDS),
    (2, TIER_2_KEYWORDS),
    (1, TIER_1_KEYWORDS),
    (0, TIER_0_KEYWORDS),
]

# Equipment keywords that indicate Tractian-relevant rotating machinery.
# Each keyword must be specific enough not to match marketing/news copy:
# - "press" alone matches "press release"; we use "stamping press" / "hydraulic press" / "roller press"
# - "fan" alone matches "fans of the brand"; we use "industrial fan" / "cooling fan"
# - "shaft" alone matches "drive shaft" but also "shaft of light"; we keep but require industrial co-evidence (handled below)
EQUIPMENT_KEYWORDS = [
    "motor", "pump", "compressor", "conveyor", "turbine", "mixer",
    "crusher", "centrifuge", "kiln", "blower", "gearbox",
    "agitator", "extruder", "grinder", "dryer",
    "boiler", "heat exchanger", "reactor", "distillation", "fermentation",
    "rotating equipment", "vibration", "predictive maintenance",
    "condition monitoring", "bearing", "impeller", "rotor",
    "reciprocating", "screw conveyor", "bucket elevator", "ball mill",
    "jaw crusher", "roller press", "blast furnace", "electric arc furnace",
    "paper machine", "recovery boiler", "digester",
    # Specific compound terms safer than ambiguous singletons:
    "stamping press", "hydraulic press", "industrial fan", "cooling fan",
    "drive shaft",
]

MARKET_POSITIVE_SIGNALS = [
    "predictive maintenance", "condition monitoring", "downtime reduction",
    "asset performance management", "reliability engineering",
    "rotating equipment", "vibration analysis",
    "industry 4.0", "smart factory", "smart manufacturing",
    "industrial iot", "iiot",
    "total productive maintenance", "tpm",
    "overall equipment effectiveness", "oee",
    "mean time between failure", "mtbf",
    "cmms", "enterprise asset management", "eam",
]

MARKET_NEGATIVE_SIGNALS = [
    "pure software", "no manufacturing", "no physical operations",
    "asset-light", "fully remote", "platform-only business",
    "digital marketplace only",
]


def score_industry_fit(industry_text: str) -> ScoreDimension:
    """
    Score industry fit (0-4). Highest matching tier wins, but tier-0 keywords
    *cap* the score at 1 because pure-SaaS / marketplace signals are dispositive.
    """
    text_lower = (industry_text or "").lower()

    if not text_lower.strip():
        return ScoreDimension(
            dimension="Industry Fit",
            score=0,
            max_score=4,
            evidence="No industry keywords discovered",
            confidence="LOW",
        )

    matches_per_tier: dict[int, list[str]] = {}
    for tier, keywords in INDUSTRY_FIT_TIERS:
        for kw in keywords:
            pattern = r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])"
            if re.search(pattern, text_lower):
                matches_per_tier.setdefault(tier, []).append(kw)

    # Tier-0 dominance only fires when tier-0 evidence overwhelms industrial signals.
    # Caterpillar (heavy machinery + financial services) used to get capped at 1 because
    # a single "financial services" hit beat zero matched industrial keywords; now we
    # require tier-0 to truly dominate.
    industrial_hits = sum(len(matches_per_tier.get(t, [])) for t in (4, 3, 2))
    tier_0_hits = len(matches_per_tier.get(0, []))
    if tier_0_hits >= 2 and industrial_hits == 0:
        evidence = f"Tier-0 indicators dominate: {', '.join(matches_per_tier[0][:3])}"
        return ScoreDimension(
            dimension="Industry Fit",
            score=0,
            max_score=4,
            evidence=evidence,
            confidence="HIGH",
        )
    if tier_0_hits >= 1 and industrial_hits == 0:
        # Single tier-0 signal with no industrial evidence: pure SaaS/marketplace.
        return ScoreDimension(
            dimension="Industry Fit",
            score=1,
            max_score=4,
            evidence=f"Single tier-0 indicator with no industrial signals: {matches_per_tier[0][0]}",
            confidence="MED",
        )

    # Tier 4 requires either a direct tier-4 keyword OR ≥2 tier-3 keywords (FMCG with
    # multiple manufacturing signals like P&G).
    if matches_per_tier.get(4):
        score = 4
        evidence = f"Tier-4 process industry: {', '.join(matches_per_tier[4][:4])}"
    elif len(matches_per_tier.get(3, [])) >= 3:
        score = 4
        evidence = f"Multiple tier-3 manufacturing signals (treated as tier-4): {', '.join(matches_per_tier[3][:4])}"
    elif matches_per_tier.get(3):
        score = 3
        evidence = f"Tier-3 industrial fit: {', '.join(matches_per_tier[3][:3])}"
    elif matches_per_tier.get(2):
        score = 2
        evidence = f"Tier-2 industrial fit: {', '.join(matches_per_tier[2][:3])}"
    elif matches_per_tier.get(1):
        score = 1
        evidence = f"Tier-1 (retail/restaurant/services) match: {', '.join(matches_per_tier[1][:3])}"
    else:
        score = 0
        evidence = "No matching industry keywords in discovered text"

    return ScoreDimension(
        dimension="Industry Fit",
        score=score,
        max_score=4,
        evidence=evidence,
        confidence="HIGH" if score > 0 else "MED",
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
    - 2: ≥1,000 employees OR ≥$100M revenue
    - 1: ≥100 employees OR ≥$10M revenue
    - 0: smaller / no data
    """
    if employees is None and revenue_billions is None:
        return ScoreDimension(
            dimension="Operational Scale",
            score=0,
            max_score=3,
            evidence="No employee count or revenue discovered",
            confidence="LOW",
        )

    emp = employees or 0
    rev = revenue_billions or 0.0

    emp_display = _sanitize_display(employee_text) or (f"{emp:,}" if emp else "Unknown")
    rev_display = _sanitize_display(revenue_text) or (f"${rev:.1f}B" if rev else "Unknown")

    if emp >= 10_000 and rev >= 1.0:
        score = 3
        evidence = (
            f"{emp_display} employees, {rev_display} revenue — enterprise scale "
            "with dedicated maintenance/reliability function and capex for PdM."
        )
    elif emp >= 1_000 or rev >= 0.1:
        score = 2
        evidence = (
            f"{emp_display} employees, {rev_display} revenue — mid-market with "
            "likely maintenance budget."
        )
    elif emp >= 100 or rev >= 0.01:
        score = 1
        evidence = (
            f"{emp_display} employees, {rev_display} revenue — smaller scale, "
            "limited PdM budget."
        )
    else:
        score = 0
        evidence = f"{emp_display} employees, {rev_display} revenue — sub-scale."

    confidence = "HIGH" if (employees is not None and revenue_billions is not None) else "MED"
    return ScoreDimension(
        dimension="Operational Scale",
        score=score,
        max_score=3,
        evidence=evidence,
        confidence=confidence,
    )


def score_physical_footprint(industrial_count: int, total_count: int) -> ScoreDimension:
    """
    Score physical footprint (0-2). Higher bar than before:
      - 2: ≥10 industrial facilities (manufacturing/processing/refinery/mine/etc.)
      - 1:  3-9 industrial facilities, OR ≥5 total facilities (logistics-heavy)
      - 0:  <3 industrial AND <5 total
    Rewards real industrial footprint, not just any address row.
    """
    if industrial_count >= 10:
        score, evidence, conf = 2, (
            f"{industrial_count} industrial facilities discovered (plants/mines/refineries) — "
            "deep footprint, large sensor expansion potential."
        ), "HIGH"
    elif industrial_count >= 3:
        score, evidence, conf = 1, (
            f"{industrial_count} industrial facilities discovered — moderate footprint."
        ), "MED"
    elif total_count >= 5:
        score, evidence, conf = 1, (
            f"{total_count} facilities discovered (logistics/distribution-heavy footprint)."
        ), "MED"
    elif total_count >= 1:
        score, evidence, conf = 0, (
            f"Only {total_count} facility(ies) discovered — single/small footprint."
        ), "LOW"
    else:
        score, evidence, conf = 0, (
            "No facilities discovered after exhausting all sources."
        ), "LOW"

    return ScoreDimension(
        dimension="Physical Footprint",
        score=score,
        max_score=2,
        evidence=evidence,
        confidence=conf,
    )


def score_equipment_dependency(equipment_evidence_text: str) -> ScoreDimension:
    """Score equipment dependency (0-1) by detecting Tractian-relevant rotating machinery in text."""
    text_lower = (equipment_evidence_text or "").lower()
    if not text_lower.strip():
        return ScoreDimension(
            dimension="Equipment Dependency",
            score=0,
            max_score=1,
            evidence="No equipment evidence discovered",
            confidence="LOW",
        )

    found: list[str] = []
    for kw in EQUIPMENT_KEYWORDS:
        kw_lower = kw.lower()
        if " " in kw_lower:
            pattern = r"\b" + re.escape(kw_lower) + r"\b"
        else:
            pattern = r"\b" + re.escape(kw_lower) + r"(?:s|es)?\b"
        if re.search(pattern, text_lower):
            found.append(kw)

    if found:
        return ScoreDimension(
            dimension="Equipment Dependency",
            score=1,
            max_score=1,
            evidence=(
                f"Rotating machinery indicators found: {', '.join(found[:5])}. "
                "These are exactly what Tractian sensors monitor."
            ),
            confidence="HIGH" if len(found) >= 3 else "MED",
        )

    return ScoreDimension(
        dimension="Equipment Dependency",
        score=0,
        max_score=1,
        evidence="No rotating-machinery keywords found in discovered text",
        confidence="MED",
    )


def compute_score_confidence(dimensions: list[ScoreDimension]) -> str:
    """Overall score confidence based on per-dimension confidence."""
    high_count = sum(1 for d in dimensions if d.confidence == "HIGH")
    med_count = sum(1 for d in dimensions if d.confidence in ("HIGH", "MED"))
    if high_count >= 3:
        return "HIGH"
    elif med_count >= 2:
        return "MED"
    return "LOW"


def infer_market_relevance(market_research_text: str, base_total: int) -> tuple[int, str]:
    """
    Compute a -1 / 0 / +1 modifier from market signals, but ONLY when the base score
    is non-saturated (would otherwise risk pushing every industrial company to 10).

    Old behavior auto-added +1 to anyone with a single positive hit, which produced
    universal saturation. New rules:
      +1 only when base ≤ 8 AND ≥3 distinct positive signals AND no negative signals
      -1 only when base ≥ 5 AND ≥2 distinct negative signals
    """
    text = (market_research_text or "").lower()
    if not text.strip():
        return 0, "No market-research evidence — no adjustment."

    pos = sorted({s for s in MARKET_POSITIVE_SIGNALS if s in text})
    neg = sorted({s for s in MARKET_NEGATIVE_SIGNALS if s in text})

    if len(neg) >= 2 and base_total >= 5:
        return -1, f"Strong negative signals ({len(neg)}): {', '.join(neg[:3])}"
    if len(pos) >= 3 and len(neg) == 0 and base_total <= 8:
        return +1, f"Strong PdM signals ({len(pos)}): {', '.join(pos[:4])}"
    if pos:
        return 0, f"Positive signals present ({len(pos)}) but not enough to adjust: {', '.join(pos[:3])}"
    return 0, "Mixed/weak market signals — no adjustment."


def build_plain_english(
    company_name: str,
    total: int,
    industry: ScoreDimension,
    scale: ScoreDimension,
    footprint: ScoreDimension,
    equipment: ScoreDimension,
    market_note: str = "",
    market_adjustment: int = 0,
) -> str:
    parts = [
        f"{company_name} scored {total}/10 on Tractian's ICP rubric.",
        f"Industry Fit {industry.score}/4: {industry.evidence}",
        f"Operational Scale {scale.score}/3: {scale.evidence}",
        f"Physical Footprint {footprint.score}/2: {footprint.evidence}",
        f"Equipment Dependency {equipment.score}/1: {equipment.evidence}",
    ]
    if market_note and market_adjustment != 0:
        sign = f"+{market_adjustment}" if market_adjustment > 0 else str(market_adjustment)
        parts.append(f"Market Adjustment {sign}: {market_note}")

    if total >= 8:
        parts.append("RECOMMENDATION: High-priority target.")
    elif total >= 5:
        parts.append("RECOMMENDATION: Mid-priority — qualify further with a discovery call.")
    elif total >= 3:
        parts.append("RECOMMENDATION: Low priority — keep on watch list.")
    else:
        parts.append("RECOMMENDATION: Disqualify — outside Tractian's ICP.")

    return "\n".join(parts)


def calculate_icp_score(
    company_name: str,
    industry_text: str,
    employees: Optional[int],
    revenue_billions: Optional[float],
    confirmed_industrial_count: int,
    confirmed_total_count: int,
    equipment_evidence_text: str,
    market_research_text: str = "",
    employee_text: str = "",
    revenue_text: str = "",
) -> ICPScore:
    """
    Main entry point. All inputs discovered at runtime.
    """
    industry = score_industry_fit(industry_text)
    scale = score_operational_scale(employees, revenue_billions, employee_text, revenue_text)
    footprint = score_physical_footprint(confirmed_industrial_count, confirmed_total_count)
    equipment = score_equipment_dependency(equipment_evidence_text)

    base_total = industry.score + scale.score + footprint.score + equipment.score

    # Floor for low-fit companies: even Salesforce (industry 0, scale 3, footprint 0, equip 0 = 3)
    # gets a meaningful "Disqualify" score. No need for additional floors here — the model
    # naturally produces 0-10 spread.

    market_adjustment, market_note = infer_market_relevance(market_research_text, base_total)
    total = max(0, min(10, base_total + market_adjustment))

    confidence = compute_score_confidence([industry, scale, footprint, equipment])
    summary = build_plain_english(
        company_name, total, industry, scale, footprint, equipment,
        market_note=market_note, market_adjustment=market_adjustment,
    )

    log.info(
        f"[{company_name}] ICP {total}/10 "
        f"(I={industry.score} S={scale.score} F={footprint.score} E={equipment.score} "
        f"M={market_adjustment:+d}) confidence={confidence}"
    )

    return ICPScore(
        total=total,
        industry_fit=industry,
        operational_scale=scale,
        physical_footprint=footprint,
        equipment_dependency=equipment,
        score_confidence=confidence,
        plain_english=summary,
    )
