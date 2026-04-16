"""
Facility-type post-classifier.

Even with a tightened LLM prompt, models tend to default to "Manufacturing Plant"
when the surrounding text contains weaker signals. This module applies a small set
of deterministic, evidence-grounded rules to refine the type *after* extraction.

Rules fire only when the text-level evidence is unambiguous, so they cannot
hallucinate a type — they can only correct a too-generic one.
"""
from __future__ import annotations
import re
from .logger import get_logger

log = get_logger("reclassifier")


# Patterns ordered by specificity. First match wins. Whole-word boundaries.
RULES: list[tuple[str, str]] = [
    # ── Refining / petrochemicals ────────────────────────────────────────────
    ("Refinery", r"\b(refinery|refineries|refining complex|cracker|ethylene|propylene|"
                  r"polyethylene|polypropylene|polymer plant|petrochemical complex|"
                  r"styrene|aromatics)\b"),
    # ── Mining & extraction ──────────────────────────────────────────────────
    ("Mine and Extraction Site",  # canonical casing
        r"\b(mine|mines|mining operation|quarry|quarries|pit|open[- ]pit|"
        r"phosphate (?:rock )?mine|potash mine|iron ore mine|coal mine|"
        r"underground mine|extraction site|wellfield)\b"),
    # ── Power generation ─────────────────────────────────────────────────────
    ("Power Plant",
        r"\b(power plant|power station|generating station|wind farm|solar farm|"
        r"hydroelectric|hydropower|gas[- ]fired|coal[- ]fired|nuclear plant|"
        r"cogeneration plant)\b"),
    # ── Packaging & bottling (incl. breweries) ───────────────────────────────
    ("Packaging Plant",
        r"\b(brewery|breweries|bottling plant|bottler|cannery|canning plant|"
        r"packaging plant|packaging facility|packaging operations|"
        r"corrugated plant|container plant|carton plant|"
        r"flexible packaging plant|protective packaging plant)\b"),
    # ── Processing (commodity transformation) ────────────────────────────────
    ("Processing Plant",
        r"\b(processing plant|processing facility|processing complex|"
        r"meatpack|meat processing|beef processing|pork processing|poultry processing|"
        r"flour mill|grain mill|sugar mill|rice mill|"
        r"oilseed (?:crushing|crush)|soybean (?:crushing|crush)|crushing plant|"
        r"sugar refinery|smelter|smelting plant|"
        r"steel mill|rolling mill|paper mill|pulp mill|cement plant|"
        r"dairy processing|cheese plant|fertilizer plant|ammonia plant)\b"),
    # ── Distribution / fulfillment ───────────────────────────────────────────
    ("Distribution Center",
        r"\b(distribution center|distribution centre|fulfillment center|"
        r"fulfilment center|logistics center|logistics hub|warehouse|"
        r"depot|cross[- ]?dock|dark store|sortation center)\b"),
    # ── R&D ──────────────────────────────────────────────────────────────────
    ("R&D Center",
        r"\b(r\s*&\s*d (?:center|centre|facility)|research (?:center|centre|lab)|"
        r"technology center|innovation center|design studio|test (?:center|range)|"
        r"launch (?:site|complex)|engineering center)\b"),
    # ── HQ ───────────────────────────────────────────────────────────────────
    ("Corporate HQ",
        r"\b(global headquarters|world headquarters|corporate headquarters|"
        r"corporate office|head office|hq\b|headquarter[a-z]*|"
        r"global head office)\b"),
]

# Industry-default fallback: when a row is "Manufacturing Plant" or "Unknown" but the
# company's overall industry strongly implies a more specific type, nudge it.
INDUSTRY_DEFAULTS: list[tuple[str, str]] = [
    ("Mine and Extraction Site",  # canonical casing
        r"\b(mining|phosphate|potash|iron ore|coal mining|gold mining|copper mining)\b"),
    ("Refinery",
        r"\b(petrochemical|chemical company|specialty chemical|polymer)\b"),
    ("Packaging Plant",
        r"\b(brewing|brewery|beverage manufactur|bottling|packaging materials)\b"),
    ("Processing Plant",
        r"\b(meat processing|food processing|grain milling|oilseed|sugar)\b"),
]


def reclassify_facility(facility: dict, industry_text: str = "") -> dict:
    """
    Apply deterministic reclassification rules to a single facility dict.
    Mutates and returns the input facility.
    """
    raw = (facility.get("raw_text_extracted") or "").lower()
    basis = (facility.get("classification_basis") or "").lower()
    blob = f"{raw} {basis}"
    current = facility.get("facility_type") or "Unknown"

    # 0. Regional-HQ guard runs FIRST so it still fires when Claude already tagged
    # the row as Corporate HQ (in which case the RULES loop would short-circuit on
    # same-type and skip the guard entirely).
    if current == "Corporate HQ":
        regional = re.search(
            r"\b(india|brazil|china|mexico|canada|asia|europe|africa|oceania|"
            r"asia[- ]pacific|emea|north america|south america|latin america|"
            r"regional|country|north[- ]american|mexican|brazilian|chinese|"
            r"indian|canadian|european) (?:headquarters|hq|head office)\b",
            blob, re.IGNORECASE,
        )
        global_anchor = re.search(
            r"\b(global|world|corporate|world[- ]?wide) (?:headquarters|hq|head office)\b",
            blob, re.IGNORECASE,
        )
        if regional and not global_anchor:
            facility["facility_type"] = "Sales Office"
            facility["reclassification_note"] = "Downgraded Corporate HQ→Sales Office (regional HQ wording, no global anchor)"
            return facility

    # 1. Direct text rules — fire whenever the raw evidence clearly says so.
    # Skip Corporate HQ reclassification when the text ALSO has plant/manufacturing
    # wording (avoids "head office" mention promoting a steel mill to HQ).
    has_plant_words = re.search(
        r"\b(plant|facility|manufactur|production|mill|refinery|smelter|operation)\w*\b",
        blob, re.IGNORECASE,
    )
    for new_type, pattern in RULES:
        if re.search(pattern, blob, re.IGNORECASE):
            if current == new_type:
                return facility
            if new_type == "Corporate HQ" and has_plant_words and current in {
                "Manufacturing Plant", "Processing Plant", "Packaging Plant",
                "Refinery", "Mine and Extraction Site", "Power Plant",
            }:
                # Don't promote an industrial site to HQ just because text mentions "head office".
                continue
            facility["facility_type"] = new_type
            facility["reclassification_note"] = f"Reclassified {current}→{new_type} from raw evidence"
            log.debug(f"Reclassified {current}→{new_type} via raw text")
            return facility

    # NOTE: industry-default rules removed in favor of trusting the LLM. The previous
    # rule wrongly converted ArcelorMittal Silao steel-blanks plant → Mine just because
    # ArcelorMittal's Wikipedia industry contains "iron ore". Vertically-integrated
    # companies have a mix of facility types and the LLM's text-grounded classification
    # is more reliable than industry-broadcast defaults.
    return facility


def reclassify_all(facilities: list[dict], industry_text: str = "") -> list[dict]:
    """Apply reclassify_facility to every entry; preserves input order."""
    return [reclassify_facility(f, industry_text) for f in facilities]
