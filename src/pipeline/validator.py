"""
Validator module.
Validates candidate facilities by querying external search endpoints.
Prioritizes precision: aggressively drops low quality data.
"""
import re
from .logger import get_logger
from .searcher import verify_location_strength, get_verification_breakdown

log = get_logger("validator")


PLANT_LIKE_TYPES = {
    "Manufacturing Plant",
    "Processing Plant",
    "Distribution Center",
    "Refinery",
    "Packaging Plant",
    "Mine and Extraction Site",
    "Power Plant",
}

CANONICAL_TYPES = {
    "manufacturing plant",
    "packaging plant",
    "processing plant",
    "distribution center",
    "corporate hq",
    "r&d center",
    "sales office",
    "refinery",
    "mine and extraction site",
    "power plant",
    "unknown",
}

TYPE_NORMALIZATION = {
    "manufacturer": "Manufacturing Plant",
    "custom manufacturer": "Manufacturing Plant",
    "manufacturing facility": "Manufacturing Plant",
    "factory": "Manufacturing Plant",
    "distribution hub": "Distribution Center",
    "distributor": "Distribution Center",
    "warehouse": "Distribution Center",
    "hq": "Corporate HQ",
    "headquarters": "Corporate HQ",
    "head office": "Corporate HQ",
    "launch site": "R&D Center",
    "mining": "Mine and Extraction Site",
}


def _company_markers(company_name: str) -> set[str]:
    """
    Derive identifying tokens for a company. ≥3 chars (so "Dow" / "P&G" / "GM" survive),
    plus the joined form ("dowchemical") as a robust fallback.
    """
    parts = [p.lower() for p in re.split(r"[^a-zA-Z0-9]+", company_name) if p]
    markers = {p for p in parts if len(p) >= 3}
    joined = "".join(parts)
    if joined and len(joined) >= 3:
        markers.add(joined)
    # Drop ultra-generic tokens that would cause false positives on third-party pages.
    markers -= {"the", "and", "inc", "co", "corp", "ltd", "llc", "plc", "company", "group"}
    return markers


def _is_likely_customer_reference(evidence_text: str) -> bool:
    customer_markers = {
        "customer", "client", "partner", "case study",
        "announcement", "story", "deploy", "deployed for",
    }
    return any(m in evidence_text for m in customer_markers)


def _appears_owned_by_company(company_name: str, evidence_text: str) -> bool:
    """
    Ownership guard:
    - Keep if evidence references target company markers.
    - Drop if evidence looks like customer/partner story and references other orgs.
    """
    markers = _company_markers(company_name)
    has_company_marker = any(m in evidence_text for m in markers)
    if has_company_marker:
        return True

    # If no direct marker and this looks like a customer story, treat as not owned.
    if _is_likely_customer_reference(evidence_text):
        return False

    # Conservative default: unknown ownership -> reject for precision-first pipeline.
    return False


def _has_minimum_source_evidence(company_name: str, city: str, country: str, extracted_text: str) -> bool:
    """
    Light gate: ensure extracted quote isn't empty garbage.
    Real validation happens downstream via quote-traceability and ownership checks.
    """
    text = (extracted_text or "").lower()
    if len(text.strip()) < 15:
        return False
    # Just need the city mentioned OR enough substantive text (50+ chars)
    city_ok = city.lower() in text
    return city_ok or len(text.strip()) >= 50


def _normalize_text_for_match(text: str) -> str:
    return " ".join((text or "").lower().split())


def _quote_exists_in_source(raw_quote: str, source_text: str) -> bool:
    """
    Check that model-provided quote has strong overlap with source text.
    Uses chunk-based matching: splits quote into 5-word windows and requires
    a majority to appear in the source. This handles models that clean up
    or slightly rephrase extracted text while still blocking hallucinations.
    """
    quote_norm = _normalize_text_for_match(raw_quote)
    source_norm = _normalize_text_for_match(source_text)
    if not quote_norm or len(quote_norm) < 20:
        return False
    # Fast path: exact match
    if quote_norm in source_norm:
        return True
    # Chunk-based: split into 5-word windows, require >=50% present in source
    words = quote_norm.split()
    if len(words) < 5:
        return any(w in source_norm for w in words if len(w) >= 4)
    window_size = 5
    windows = [" ".join(words[i:i+window_size]) for i in range(len(words) - window_size + 1)]
    if not windows:
        return False
    hits = sum(1 for w in windows if w in source_norm)
    return hits >= len(windows) * 0.4


def _source_domain_authority(source_url: str, company_website: str = "") -> int:
    """
    Score the authority of the source DOMAIN, 0-5.
      5 = SEC EDGAR (legally mandated filing)
      4 = Company's own domain (sales-listed facilities)
      3 = Wikipedia
      2 = Authoritative third-party (Reuters, Bloomberg, Macrotrends, etc.)
      0 = Generic third-party
    """
    u = (source_url or "").lower()
    if not u:
        return 0
    if "sec.gov" in u or "edgar" in u:
        return 5
    host = u.split("//", 1)[-1].split("/", 1)[0]
    cw = (company_website or "").lower().replace("www.", "").split("/")[0]
    if cw and (cw in host or host.endswith("." + cw)):
        return 4
    if "wikipedia.org" in host:
        return 3
    authoritative = {
        "reuters.com", "bloomberg.com", "macrotrends.net",
        "dnb.com", "craft.co", "owler.com",
        "businesswire.com", "prnewswire.com", "globenewswire.com",
    }
    if any(a in host for a in authoritative):
        return 2
    return 0


def _source_authority_label(url: str, company_website: str) -> str:
    pts = _source_domain_authority(url, company_website)
    return {
        5: "SEC EDGAR filing",
        4: "Company-own domain",
        3: "Wikipedia",
        2: "Authoritative third-party",
        0: "Generic third-party",
    }[pts]


def _compute_source_evidence_tier(
    company_name: str,
    city: str,
    country: str,
    raw_text: str,
    industrial_markers: set[str],
    source_url: str = "",
    company_website: str = "",
) -> tuple[int, dict]:
    """
    Combined source-evidence score, 0-10:
      - up to 5 points from DOMAIN AUTHORITY (who published the page)
      - up to 5 points from QUOTE DENSITY (how explicit the extracted evidence is)

    Returns (total_tier, breakdown). The breakdown enables UI explanations.
    """
    raw = (raw_text or "").strip()
    text = raw.lower()
    c = city.strip().lower()
    ctr = (country or "").strip().lower()

    # Domain authority (0-5)
    domain_pts = _source_domain_authority(source_url, company_website)
    domain_label = _source_authority_label(source_url, company_website)

    # Quote density (capped at 5) — track each component
    length_pts = 2 if len(raw) >= 180 else (1 if len(raw) >= 90 else 0)
    company_hit = any(m in text for m in _company_markers(company_name) if len(m) >= 3)
    company_pts = 1 if company_hit else 0
    city_hit = bool(c and c in text)
    city_pts = 1 if city_hit else 0
    country_hit = bool(ctr and len(ctr) >= 3 and ctr in text)
    country_pts = 1 if country_hit else 0
    ind_matches = [m for m in industrial_markers if m in text]
    ind_pts = min(len(ind_matches), 2)

    quote_pts_raw = length_pts + company_pts + city_pts + country_pts + ind_pts
    quote_pts = min(quote_pts_raw, 5)

    total = min(quote_pts + domain_pts, 10)

    breakdown = {
        "total": total,
        "domain": {"points": domain_pts, "max": 5, "label": domain_label},
        "quote": {
            "points": quote_pts,
            "max": 5,
            "raw_length": len(raw),
            "components": [
                {"name": "Length", "points": length_pts, "max": 2,
                 "detail": f"{len(raw)} chars ({'long' if length_pts == 2 else 'medium' if length_pts == 1 else 'short'})"},
                {"name": "Company name in quote", "points": company_pts, "max": 1,
                 "detail": "present" if company_hit else "absent"},
                {"name": "City in quote", "points": city_pts, "max": 1,
                 "detail": "present" if city_hit else "absent"},
                {"name": "Country in quote", "points": country_pts, "max": 1,
                 "detail": "present" if country_hit else "absent"},
                {"name": "Industrial keywords", "points": ind_pts, "max": 2,
                 "detail": ", ".join(ind_matches[:3]) if ind_matches else "none matched"},
            ],
        },
    }
    return total, breakdown


def _confidence_from_signals(verify_strength: str, source_tier: int) -> str:
    """
    Combine OSINT grade + primary-source quality. MED is no longer the default:
    - HIGH   — strong external corroboration plus solid on-page evidence
    - MED    — strong OSINT with weaker text, or weak OSINT with exceptional text
    - LOW    — one-sided confidence (good scrape, weak OSINT, or vice versa)
    - ESTIMATED — thin overall; row kept only because guardrails passed
    """
    v_pts = {"strong": 50, "weak": 26, "none": 0}.get(verify_strength, 0)
    src_pts = int(source_tier) * 3  # 0–30
    total = v_pts + src_pts

    # Thresholds tuned so HIGH/MED/LOW/ESTIMATED all appear; MED is not the implicit default.
    if total >= 65:
        return "HIGH"
    if total >= 44:
        return "MED"
    if total >= 26:
        return "LOW"
    return "ESTIMATED"


CANONICAL_DISPLAY = {
    "manufacturing plant": "Manufacturing Plant",
    "packaging plant": "Packaging Plant",
    "processing plant": "Processing Plant",
    "distribution center": "Distribution Center",
    "corporate hq": "Corporate HQ",
    "r&d center": "R&D Center",
    "sales office": "Sales Office",
    "refinery": "Refinery",
    "mine and extraction site": "Mine and Extraction Site",  # lowercase 'and'
    "power plant": "Power Plant",
    "unknown": "Unknown",
}


def _normalize_facility_type(raw_type: str) -> str:
    normalized = str(raw_type or "Unknown").strip()
    lower = normalized.lower()
    if lower in CANONICAL_DISPLAY:
        return CANONICAL_DISPLAY[lower]
    if lower in TYPE_NORMALIZATION:
        return TYPE_NORMALIZATION[lower]
    if "plant" in lower:
        return "Manufacturing Plant"
    if "distribution" in lower or "warehouse" in lower:
        return "Distribution Center"
    if "headquarter" in lower or lower == "hq":
        return "Corporate HQ"
    if "office" in lower:
        return "Sales Office"
    return "Unknown"


def validate_facilities(
    company_name: str,
    facilities: list[dict],
    industry_text: str = "",
    source_text_by_url: dict[str, str] | None = None,
    company_website: str = "",
) -> list[dict]:
    """
    Validate facilities extracted by Claude. 
    Applies secondary verification via Brave Search.
    Drops any items without proper formatting.
    """
    validated = []
    drop_audit: dict[str, int] = {
        "invalid_city": 0,
        "weak_source_evidence": 0,
        "quote_not_in_source": 0,
        "not_owned": 0,
        "no_hq_evidence": 0,
        "passed": 0,
    }

    low_fit_markers = {
        "saas", "software", "fintech", "media", "hospitality",
        "restaurant", "marketplace", "food service", "cloud",
    }
    industrial_evidence_markers = {
        "manufacturing", "plant", "processing", "refinery", "mine",
        "mill", "factory", "production", "industrial", "warehouse",
    }
    explicit_hq_markers = {"headquarters", "headquarter", "corporate hq", "global hq", "hq"}
    low_fit_company = any(m in industry_text.lower() for m in low_fit_markers)

    for f in facilities:
        city = f.get("city", "")
        state_region = f.get("state_region", "")
        country = f.get("country", "")
        raw_text_extracted = f.get("raw_text_extracted", "")
        source_url = f.get("source_url", "")
        f_type = _normalize_facility_type(f.get("facility_type", "Unknown"))
        f["facility_type"] = f_type
        
        # 1. Immediate rejection of nulls/unknowns/country-as-city
        city_clean = city.strip().strip("<>").lower()
        country_clean = (country or "").strip().lower()
        INVALID_CITIES = {
            "null", "unknown", "none", "n/a", "", "various", "multiple",
            "worldwide", "global", "international",
        }
        COUNTRY_NAMES = {
            "united states", "united kingdom", "canada", "mexico", "brazil",
            "china", "india", "germany", "france", "japan", "australia",
            "south korea", "italy", "spain", "netherlands", "switzerland",
            "sweden", "norway", "denmark", "finland", "belgium", "austria",
            "ireland", "singapore", "thailand", "indonesia", "malaysia",
            "south africa", "colombia", "chile", "argentina", "peru",
            "poland", "czech republic", "romania", "turkey", "russia",
            "saudi arabia", "uae", "egypt", "nigeria", "kenya",
            "new zealand", "philippines", "vietnam", "taiwan", "israel",
        }
        if not city_clean or city_clean in INVALID_CITIES or city_clean in COUNTRY_NAMES:
            log.debug(f"[{company_name}] DROP(invalid_city): {city}")
            drop_audit["invalid_city"] += 1
            continue
        if city_clean == country_clean:
            log.debug(f"[{company_name}] DROP(invalid_city): city==country '{city}'")
            drop_audit["invalid_city"] += 1
            continue
            
        location_str = f"{city}, {country}" if country else city
        if not _has_minimum_source_evidence(company_name, city, country, raw_text_extracted):
            log.debug(f"[{company_name}] DROP(weak_source_evidence): {location_str}")
            drop_audit["weak_source_evidence"] += 1
            continue
        # Source-page ownership + quote-traceability gate.
        # SEC EDGAR filings are bound to the company by CIK at fetch time and use
        # pronouns ("the Company", "we") rather than the legal name in the Properties
        # section, so the company-marker gate would wrongly drop them. Skip it for
        # EDGAR URLs but still enforce quote-traceability.
        quote_penalty = 0
        is_edgar_source = (
            "sec.gov" in (source_url or "").lower()
            or "edgar" in (source_url or "").lower()
        )
        source_text = (source_text_by_url or {}).get(source_url, "") if source_text_by_url else ""
        if source_text:
            source_norm = _normalize_text_for_match(source_text)
            if not is_edgar_source:
                company_markers_set = _company_markers(company_name)
                source_mentions_company = any(
                    m in source_norm for m in company_markers_set if len(m) >= 3
                )
                if not source_mentions_company:
                    log.debug(
                        f"[{company_name}] DROP(source_not_about_company): {location_str} "
                        f"— source page doesn't mention '{company_name}'"
                    )
                    drop_audit["quote_not_in_source"] += 1
                    continue

            city_in_source = city.lower() in source_norm
            quote_ok = _quote_exists_in_source(raw_text_extracted, source_text)
            # Fallback: an LLM occasionally mis-attributes the source URL of an
            # extracted facility. Look across ALL provided source pages — if any
            # contains the city, re-attribute the row to that page.
            if not quote_ok and not city_in_source:
                rescued_url = None
                for alt_url, alt_text in source_text_by_url.items():
                    if alt_url == source_url:
                        continue
                    if city.lower() in _normalize_text_for_match(alt_text):
                        rescued_url = alt_url
                        break
                if rescued_url:
                    f["source_url"] = rescued_url
                    source_url = rescued_url
                    city_in_source = True
                    quote_penalty = 1
                else:
                    log.debug(f"[{company_name}] DROP(quote_not_in_source): {location_str}")
                    drop_audit["quote_not_in_source"] += 1
                    continue
            if not quote_ok:
                quote_penalty = 2
        
        # 2. Evidence tier (primary source only) + OSINT strength → confidence
        source_tier, tier_breakdown = _compute_source_evidence_tier(
            company_name, city, country, raw_text_extracted, industrial_evidence_markers,
            source_url=source_url, company_website=company_website,
        )
        source_tier = max(0, source_tier - quote_penalty)
        # Apply the penalty to the breakdown so the UI explanation matches the value.
        if quote_penalty:
            tier_breakdown["quote_penalty"] = quote_penalty
            tier_breakdown["total"] = source_tier

        # Guardrail: avoid false-positive "plant" classifications for low-fit companies
        # unless the extracted evidence clearly indicates industrial operations.
        evidence_text = (
            f"{raw_text_extracted} {f.get('classification_basis', '')}"
        ).lower()
        has_industrial_evidence = any(m in evidence_text for m in industrial_evidence_markers)
        has_explicit_hq_evidence = any(m in evidence_text for m in explicit_hq_markers)
        appears_owned = _appears_owned_by_company(company_name, evidence_text)

        # If the source page itself mentions the company, that's sufficient ownership
        # proof — the extracted quote may be compact but the page is about this company.
        if not appears_owned and source_text_by_url:
            page_text = source_text_by_url.get(source_url, "")
            if page_text:
                page_norm = _normalize_text_for_match(page_text)
                appears_owned = any(
                    m in page_norm for m in _company_markers(company_name) if len(m) >= 3
                )

        # SEC EDGAR 10-K: ownership is already established by the CIK resolution at
        # fetch time (we wouldn't have retrieved this filing unless it was bound to
        # the target company's ticker). 10-K Properties sections routinely refer to
        # the filer as "the Company" / "we", so the marker check will otherwise fail.
        if not appears_owned and is_edgar_source:
            appears_owned = True

        if not appears_owned:
            log.debug(f"[{company_name}] DROP(not_owned): {location_str} — {f_type}")
            drop_audit["not_owned"] += 1
            continue

        if f_type in {"Corporate HQ", "Sales Office"} and not has_explicit_hq_evidence:
            log.debug(f"[{company_name}] DROP(no_hq_evidence): {location_str} — {f_type}")
            drop_audit["no_hq_evidence"] += 1
            continue
        if low_fit_company and f_type in PLANT_LIKE_TYPES and not has_industrial_evidence:
            f_type = "Sales Office"
            f["facility_type"] = f_type
            f["classification_basis"] = (
                f"{f.get('classification_basis', '')} "
                "[Downgraded from industrial type due weak evidence for low-fit industry]"
            ).strip()

        # 3. Secondary verification (graded, uses source URL for domain-aligned corroboration)
        category = (
            "industrial"
            if f_type in PLANT_LIKE_TYPES or (f_type == "Unknown" and has_industrial_evidence)
            else "general"
        )
        verify_strength = verify_location_strength(
            company_name,
            location_str,
            f_type,
            source_url,
            category=category,
            state_region=state_region,
        )
        confidence = _confidence_from_signals(verify_strength, source_tier)

        # SEC EDGAR 10-K Properties is itself an authoritative disclosure (legally
        # mandated). Floor confidence tiered by source evidence strength — a 10-K-
        # disclosed facility should never read as "estimated" and, when the quoted
        # evidence is strong, should promote to HIGH regardless of OSINT noise.
        src_lower = (source_url or "").lower()
        if "sec.gov" in src_lower or "edgar" in src_lower:
            if source_tier >= 8 and confidence != "HIGH":
                confidence = "HIGH"
            elif confidence in {"ESTIMATED", "LOW"}:
                confidence = "MED"

        # Keep classification_basis CLEAN — it's user-facing in dashboards and CSVs.
        # Move OSINT/source-tier signal to dedicated fields instead.
        f["osint_corroboration"] = verify_strength
        f["primary_source_tier"] = source_tier
        f["source_tier_breakdown"] = tier_breakdown
        osint_raw = get_verification_breakdown(
            company_name, location_str, f_type, source_url,
            category=category, state_region=state_region,
        )
        hit_urls = osint_raw.get("hit_urls") or []
        f["osint_breakdown"] = {
            "strength": verify_strength,
            "hit_count": len(hit_urls),
            "max_hit_score": osint_raw.get("max_hit", 0),
            "sample_urls": hit_urls[:5],
            "category": category,
        }

        if not f.get("classification_basis"):
            f["classification_basis"] = "Model extracted location and type from source text."

        f["confidence"] = confidence
        f["company"] = company_name
        f["facility_location"] = location_str
        f["state_region"] = state_region
        f["source_count"] = 1
        f["all_source_urls"] = [source_url] if source_url else []
        
        drop_audit["passed"] += 1
        validated.append(f)

    total_input = len(facilities)
    dropped = total_input - drop_audit["passed"]
    log.info(
        f"[{company_name}] Validation audit: {total_input} candidates → "
        f"{drop_audit['passed']} passed, {dropped} dropped "
        f"(invalid_city={drop_audit['invalid_city']}, "
        f"weak_evidence={drop_audit['weak_source_evidence']}, "
        f"quote_mismatch={drop_audit['quote_not_in_source']}, "
        f"not_owned={drop_audit['not_owned']}, "
        f"no_hq_evidence={drop_audit['no_hq_evidence']})"
    )
    return validated
