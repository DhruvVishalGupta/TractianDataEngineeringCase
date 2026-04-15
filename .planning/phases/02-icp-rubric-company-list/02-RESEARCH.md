# Phase 2: ICP Rubric & Company List — Research

**Researched:** 2026-04-15
**Domain:** ICP scoring engine verification, Python dataclass/Pydantic company registry, unit test extension
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** `src/pipeline/icp_scorer.py` is already fully implemented (333 lines, all 4 dimensions). Do NOT rewrite it.
- **D-02:** `scripts/test_icp_scorer.py` has 17 passing tests. Add 2 additional edge cases: (a) private company with `employees=None, revenue_billions=None` → should not crash, score operational scale = 0 LOW; (b) borderline industry (tier-2 match → score=2).
- **D-03:** Confirm `ICPScore` and `ScoreDimension` Pydantic schemas in `schema.py` are complete and match what `icp_scorer.py` returns. If minor gaps exist, fix them — do not redesign.
- **D-04:** Create `src/pipeline/companies.py` as the authoritative company registry. Each entry is a typed dataclass or Pydantic model with: `name`, `slug`, `website`, `is_public`, `sec_ticker`, `known_industry_hint`, `expected_icp_tier`.
- **D-05:** Revenue and employees are NOT stored in companies.py — they are discovered at runtime by `firmographics.py`.
- **D-06:** All 20 companies must be present. The 4 obvious non-ICP targets (Salesforce, Stripe, Spotify, Airbnb) stay in the list.
- **D-07:** Private companies (Cargill, Stripe, SpaceX) have `is_public: False` and `sec_ticker: None`. Flagged with `sec_data: "unavailable"` in pipeline output — no other special treatment.
- **D-08:** No fast-fail. All 20 companies run through the full pipeline.
- **D-09:** `config.py`'s `COMPANIES` list is superseded by `companies.py`. After Phase 2, downstream modules import from `companies.py`, not `config.py`. `config.py` retains non-company config.
- **D-10:** Provide `get_all_companies() -> list[Company]` and `get_company_by_slug(slug: str) -> Company | None` as the only public API.

### Claude's Discretion

- Whether to use a dataclass or Pydantic BaseModel for the Company type (either is fine)
- Internal ordering of companies in the list
- Whether to add a `__repr__` for debugging

### Deferred Ideas (OUT OF SCOPE)

- Per-company known CIK number in companies.py — EDGAR module can discover CIK dynamically from ticker; not needed in Phase 2
- Industry synonym expansion in icp_scorer.py — if rubric misses edge cases, fix in Phase 4 after real data is collected
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INTEL-01 | ICP scoring engine implements all 4 dimensions: Industry Fit (0-4), Operational Scale (0-3), Physical Footprint (0-2), Equipment Dependency (0-1), capped at 10 | icp_scorer.py is already fully implemented and verified (17/17 tests pass). Plans verify and finalize only. |
| INTEL-02 | Score confidence: HIGH (all 4 dims confident), MED (2-3 dims), LOW (<2 dims) | `compute_score_confidence()` in icp_scorer.py implements this exactly. Schema captures `score_confidence: str`. Verified correct. |
| INTEL-03 | Score breakdown stored as structured object — a salesperson can read it and understand every point awarded | `ICPScore` + `ScoreDimension` schema captures full breakdown. `plain_english` field contains salesperson-readable summary. Both verified complete. |
</phase_requirements>

---

## Summary

Phase 2 is primarily a **verification and gap-filling** phase, not new implementation. The ICP scoring engine (`icp_scorer.py`, 333 lines) was built in Phase 1 and all 17 existing unit tests pass (confirmed by live run: `17/17 passed`). The Pydantic schemas in `schema.py` are complete and correctly match what `icp_scorer.py` returns — no schema changes are required.

The substantive new work in this phase is creating `src/pipeline/companies.py`: a typed company registry with 20 entries supplying metadata (`slug`, `website`, `is_public`, `sec_ticker`, `known_industry_hint`, `expected_icp_tier`) that all downstream phases will import. This supersedes `config.py`'s plain-dict `COMPANIES` list. Two additional test cases must also be appended to the existing test script (not replacing existing tests).

**Primary recommendation:** Use a `dataclass` (not Pydantic BaseModel) for the `Company` type in `companies.py` — it is pure static registry data with no validation or serialization needed at this layer. Keep the file simple: a module-level `_COMPANIES` list of `Company` instances, plus `get_all_companies()` and `get_company_by_slug()`. Match the import pattern already used by all pipeline modules.

---

## Standard Stack

### Core (verified installed — Phase 1 pinned requirements.txt)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.x (pinned in requirements.txt) | `ICPScore` / `ScoreDimension` schemas | Already in use; all schema imports work |
| Python dataclasses | stdlib | `Company` registry type | Zero-dependency; sufficient for static registry |
| Python typing | stdlib | `Optional[str]`, `Literal` | Already used throughout pipeline |

### No new dependencies required

This phase adds no new packages. The only files created/modified are:
- `src/pipeline/companies.py` (new)
- `scripts/test_icp_scorer.py` (2 tests appended)
- `src/pipeline/icp_scorer.py` (no changes expected; verify only)
- `src/pipeline/schema.py` (no changes expected; verify only)

---

## Architecture Patterns

### Recommended Project Structure (existing — no changes)

```
src/pipeline/
├── companies.py      # NEW — authoritative company registry
├── icp_scorer.py     # VERIFY ONLY — already complete
├── schema.py         # VERIFY ONLY — already complete
├── config.py         # RETAIN — non-company config stays here
└── logger.py         # unchanged
scripts/
└── test_icp_scorer.py  # APPEND 2 tests — do not remove any
```

### Pattern 1: Company Registry as Typed Dataclass Module

**What:** A Python module containing a frozen dataclass `Company` and a module-level list `_COMPANIES`. Two public functions provide all access.

**When to use:** Static reference data that is read-only, has no I/O, and needs zero external dependencies.

**Example:**
```python
# src/pipeline/companies.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .logger import get_logger

log = get_logger("companies")


@dataclass(frozen=True)
class Company:
    name: str
    slug: str
    website: str
    is_public: bool
    sec_ticker: Optional[str]
    known_industry_hint: str
    expected_icp_tier: str  # "HIGH" | "MED" | "LOW"


_COMPANIES: list[Company] = [
    Company(
        name="Cargill",
        slug="cargill",
        website="cargill.com",
        is_public=False,
        sec_ticker=None,
        known_industry_hint="grain processing oilseed milling meat processing food manufacturing",
        expected_icp_tier="HIGH",
    ),
    # ... 19 more entries
]


def get_all_companies() -> list[Company]:
    return list(_COMPANIES)


def get_company_by_slug(slug: str) -> Optional[Company]:
    for c in _COMPANIES:
        if c.slug == slug:
            return c
    return None
```

### Pattern 2: Slug Convention

**What:** Slugs are lowercase, hyphen-separated, filesystem-safe strings derived from company name.

**When to use:** All 20 slugs must match `data/raw/{slug}/` directory layout used by Phase 3.

**Slug rules:**
- Lowercase
- Spaces and `&` → hyphen
- Drop punctuation (`.`, `,`, `'`)
- Abbreviations kept (e.g. "ab-inbev" not "anheuser-busch-inbev")

### Pattern 3: Test Extension (append-only)

**What:** New tests are appended to the existing `scripts/test_icp_scorer.py` file using the same `check()` helper pattern already in place.

**When to use:** Never remove existing passing tests. Append-only to preserve the 17-test baseline.

**Example (2 new edge cases per D-02):**
```python
# Edge case (a): private company, both values None → no crash, score=0, confidence=LOW
result_private = score_operational_scale(None, None)
check("op_scale: none/none no crash", result_private, 0)
check("op_scale: none/none confidence LOW", result_private, "LOW", "confidence")

# Edge case (b): borderline tier-2 industry match → score=2
check("industry_fit: tier-2 general manufacturing",
      score_industry_fit("general manufacturing industrial operations"),
      2)
```

Note: Edge case (a) is already covered by test `op_scale: no data` (line 76 in existing file). The new test adds a confidence check on top of the score check — making it explicit that `LOW` is returned. Edge case (b) is not currently tested.

### Anti-Patterns to Avoid

- **Storing runtime data in companies.py:** Revenue, employees, facility count — NEVER in this file. All discovered at runtime. (D-05)
- **Importing from config.COMPANIES in new code:** Phase 3+ must import from `companies.py`, not `config.py`. (D-09)
- **Using a Pydantic BaseModel for Company:** Adds unnecessary validation overhead for static data; a frozen dataclass suffices. (Claude's discretion — dataclass recommended)
- **Adding CIK numbers to companies.py:** Explicitly deferred — EDGAR discovers CIK from ticker dynamically. (Deferred)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Slug generation from name | Custom slugify function | Pre-define slugs manually in the list | Only 20 companies; manual is clearer and avoids edge cases (e.g., "Procter & Gamble" → "procter-and-gamble" vs "procter-gamble") |
| Company lookup by slug | Linear search reinvented | `get_company_by_slug()` already specified | Keeps API surface minimal |
| Test runner framework | pytest setup | Existing inline test pattern (no pytest) | The test file uses a plain Python runner; maintaining consistency avoids adding a new dependency |

**Key insight:** This phase is almost entirely about correct data entry (the 20 company records) and verification. The hardest part is getting `known_industry_hint` strings precise enough for `score_industry_fit()` to produce the correct `expected_icp_tier`.

---

## Complete Company Data for companies.py

This is the authoritative reference for all 20 entries. Cross-verified against `config.py` (source of truth for `name`, `website`, `is_public`) and CONTEXT.md (source of truth for tickers and hints).

| # | name | slug | website | is_public | sec_ticker | known_industry_hint | expected_icp_tier |
|---|------|------|---------|-----------|------------|--------------------|--------------------|
| 1 | Cargill | cargill | cargill.com | False | None | grain processing oilseed milling meat processing food manufacturing | HIGH |
| 2 | Dow Chemical | dow-chemical | dow.com | True | DOW | petrochemical polymer resin manufacturing ethylene specialty chemical | HIGH |
| 3 | Tyson Foods | tyson-foods | tysonfoods.com | True | TSN | meat processing poultry food manufacturing | HIGH |
| 4 | Kraft Heinz | kraft-heinz | kraftheinzcompany.com | True | KHC | food manufacturing beverage processing packaging | HIGH |
| 5 | Mosaic Company | mosaic-company | mosaicco.com | True | MOS | phosphate mining potash fertilizer agrochem mineral processing | HIGH |
| 6 | ArcelorMittal | arcelormittal | arcelormittal.com | True | MT | steel metal smelting rolling mill iron blast furnace electric arc furnace | HIGH |
| 7 | Anheuser-Busch InBev | ab-inbev | ab-inbev.com | True | BUD | brewing beverage food manufacturing | HIGH |
| 8 | International Paper | international-paper | internationalpaper.com | True | IP | pulp paper paperboard containerboard manufacturing | HIGH |
| 9 | Sealed Air | sealed-air | sealedair.com | True | SEE | packaging manufacturing polymer plastic | MED |
| 10 | Caterpillar | caterpillar | caterpillar.com | True | CAT | industrial manufacturing construction equipment manufacturing | MED |
| 11 | Procter & Gamble | procter-and-gamble | pg.com | True | PG | consumer goods manufacturing chemical processing | MED |
| 12 | Colgate-Palmolive | colgate-palmolive | colgatepalmolive.com | True | CL | consumer goods manufacturing chemical processing | MED |
| 13 | Mondelez International | mondelez | mondelezinternational.com | True | MDLZ | food manufacturing snack food processing beverage | HIGH |
| 14 | SpaceX | spacex | spacex.com | False | None | aerospace manufacturing | MED |
| 15 | McDonald's | mcdonalds | mcdonalds.com | True | MCD | food service restaurant fast food | LOW |
| 16 | Walmart | walmart | walmart.com | True | WMT | retail distribution logistics warehousing | LOW |
| 17 | Salesforce | salesforce | salesforce.com | True | CRM | cloud saas software platform | LOW |
| 18 | Stripe | stripe | stripe.com | False | None | fintech payment processing financial technology | LOW |
| 19 | Spotify | spotify | spotify.com | True | SPOT | media streaming software | LOW |
| 20 | Airbnb | airbnb | airbnb.com | True | ABNB | marketplace e-commerce platform hospitality | LOW |

**Scoring verification (known_industry_hint → expected_icp_tier alignment):**

Each `known_industry_hint` was tested mentally against `INDUSTRY_FIT_TIERS` in `icp_scorer.py`:
- Cargill: "grain processing" → tier-4 keyword "grain" → score 4 → HIGH
- Dow Chemical: "petrochemical polymer resin" → tier-4 keywords → score 4 → HIGH
- Tyson Foods: "meat processing" → tier-4 keyword → score 4 → HIGH
- Kraft Heinz: "food manufacturing" → tier-4 keyword "food" → score 4 → HIGH
- Mosaic Company: "phosphate mining potash fertilizer" → tier-4 keywords "mining", "phosphate", "fertilizer" → score 4 → HIGH
- ArcelorMittal: "steel metal smelting rolling mill" → tier-4 keywords "steel", "metal", "smelting", "rolling mill" → score 4 → HIGH
- AB InBev: "brewing beverage" → tier-4 keyword "brewing" → score 4 → HIGH
- International Paper: "pulp paper paperboard" → tier-4 keywords "pulp", "paper", "paperboard" → score 4 → HIGH
- Sealed Air: "packaging manufacturing polymer plastic" → tier-2 "packaging manufacturing" → score 2; "polymer" → tier-4 → score 4; hint has polymer → MED border HIGH; set MED for conservative expected tier
- Caterpillar: "industrial manufacturing" → tier-2 "industrial manufacturing" → score 2 → MED
- P&G: "consumer goods manufacturing chemical processing" → "chemical" → tier-4 → score 4; but note "consumer" is not in tier list; "chemical processing" partially matches; MED is conservative
- Colgate: same as P&G rationale → MED
- Mondelez: "food manufacturing" → tier-4 "food" → score 4 → HIGH
- SpaceX: "aerospace manufacturing" → tier-2 "aerospace manufacturing" → score 2 → MED
- McDonald's: "food service fast food" → tier-0 "food service", "fast food" → score 0 → LOW
- Walmart: "retail distribution logistics warehousing" → tier-2 "logistics", "warehousing"; tier-1 "retail distribution"; best = 2 → LOW (scale will save it to some extent; expected_icp_tier is LOW)
- Salesforce: "cloud saas software platform" → tier-0 → score 0 → LOW
- Stripe: "fintech payment processing" → tier-0 → score 0 → LOW
- Spotify: "media streaming software" → tier-0 → score 0 → LOW
- Airbnb: "marketplace hospitality" → tier-0 → score 0 → LOW

**Note on Sealed Air and P&G:** The `known_industry_hint` for Sealed Air includes "polymer" which is a tier-4 keyword — so `score_industry_fit()` will return 4, not 2. This means `expected_icp_tier` should be HIGH, not MED. Planner should set Sealed Air to HIGH. Similarly, P&G and Colgate hints containing "chemical processing" — "chemical" matches tier-4, so Industry Fit = 4. These will score HIGH, not MED. The planner should reconsider and set them HIGH, or deliberately soften the hint. The hint must be accurate to what `firmographics.py` will discover; the `expected_icp_tier` is just a validation label, not a scoring input, so accuracy of the hint takes priority. This is a data precision question for the planner.

---

## Schema Verification Results

**ICPScore (schema.py lines 18-27) — COMPLETE, no changes needed:**
- `total: int = Field(ge=0, le=10)` — correct, matches cap in `calculate_icp_score()`
- `industry_fit: ScoreDimension` — correct
- `operational_scale: ScoreDimension` — correct
- `physical_footprint: ScoreDimension` — correct
- `equipment_dependency: ScoreDimension` — correct
- `score_confidence: str` — correct, populated by `compute_score_confidence()`
- `plain_english: str` — correct, populated by `build_plain_english()`

**ScoreDimension (schema.py lines 9-15) — COMPLETE, no changes needed:**
- `dimension: str`, `score: int`, `max_score: int`, `evidence: str`, `confidence: str` — all present and used

**Confidence:** Both schemas are complete. The `confidence` field on `ScoreDimension` uses the literal values "HIGH", "MED", "LOW" consistently. No `Literal` type constraint is used (just `str`) — this is acceptable given the rubric is internal.

---

## Common Pitfalls

### Pitfall 1: known_industry_hint Too Vague Defeats Tier-4 Scoring

**What goes wrong:** If a hint like "food company" is used instead of "meat processing food manufacturing", `score_industry_fit()` may score tier-2 or tier-0 instead of tier-4 because it relies on exact substring matching.

**Why it happens:** `score_industry_fit()` does `kw in text_lower` substring matching against specific keyword strings. The hint must contain those exact strings.

**How to avoid:** Embed the exact tier-4 keywords from `INDUSTRY_FIT_TIERS` in the hint. Check: does the hint contain at least one string from the tier-4 list?

**Warning signs:** `expected_icp_tier: "HIGH"` for a company but `score_industry_fit(known_industry_hint)` returns <4.

### Pitfall 2: Slug Mismatch with Phase 3 Directory Layout

**What goes wrong:** Phase 3 creates `data/raw/{slug}/` directories. If the slug in `companies.py` doesn't match exactly, Phase 3 file lookups fail silently.

**Why it happens:** Slug is defined manually. Typo or inconsistency (e.g., "arcelormittal" vs "arcelor-mittal") breaks the path join.

**How to avoid:** Slugs are lowercase, hyphen-delimited, and must be consistent. Lock the slugs in this phase — they become the filesystem contract.

**Warning signs:** Phase 3 creates a directory that `get_company_by_slug()` cannot find.

### Pitfall 3: Accidentally Removing Existing Tests

**What goes wrong:** When appending to `test_icp_scorer.py`, accidental whitespace or import changes break the 17 existing assertions.

**Why it happens:** Text editor auto-formatting or copy-paste errors.

**How to avoid:** Append only after the existing `print(f"\nICP scorer tests:")` line. The final pass/fail count report should be updated to reflect 19 total, or just leave the counter as-is (it's auto-computed from `passed + failed`).

### Pitfall 4: Duplicate Test for Edge Case (a)

**What goes wrong:** Edge case (a) in D-02 ("private company, None/None → score=0, LOW confidence") is already covered by the existing `op_scale: no data` test (line 76). Adding an exact duplicate adds no value.

**Why it happens:** The D-02 description says "should not crash, score = 0 LOW" — this passes today.

**How to avoid:** The new edge case (a) test should be distinct: check the `confidence` field returns "LOW" explicitly, which the existing test does NOT check. The existing test only checks `score=0`.

---

## Code Examples

### Test Extension — Append to scripts/test_icp_scorer.py

```python
# ── Additional edge cases (D-02) ─────────────────────────────────────────────

# Edge case (a): private company, both None — verify confidence is LOW (not just score=0)
private_scale = score_operational_scale(None, None)
check("op_scale: none/none → confidence LOW",
      private_scale, "LOW", "confidence")

# Edge case (b): borderline tier-2 industry (not tier-4, not tier-0) → score=2
check("industry_fit: tier-2 general manufacturing",
      score_industry_fit("general manufacturing industrial operations"),
      2)
```

### companies.py Public API Usage Pattern

```python
# How Phase 3 will use companies.py
from src.pipeline.companies import get_all_companies, get_company_by_slug

for company in get_all_companies():
    raw_dir = DATA_RAW_DIR / company.slug
    if company.is_public and company.sec_ticker:
        # fetch EDGAR data
        ...
    else:
        # flag sec_data: "unavailable"
        ...

# Lookup by slug
company = get_company_by_slug("dow-chemical")
```

### Logger Pattern (established in Phase 1)

```python
from .logger import get_logger
log = get_logger("companies")
```

---

## Runtime State Inventory

Step 2.5 trigger: This phase is NOT a rename/refactor/migration phase. No runtime state inventory required.

---

## Environment Availability

This phase is code-only (dataclass file + test extension). No external tools, services, or runtimes needed beyond Python stdlib and the already-installed packages from Phase 1.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.x | All | Yes | confirmed (pip runs) | — |
| pydantic | schema.py imports | Yes | pinned in requirements.txt | — |
| scripts/test_icp_scorer.py runner | Validation | Yes | plain Python, no pytest | — |

**Missing dependencies:** None.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Plain Python (no pytest) — inline assertions with custom `check()` helper |
| Config file | None — script is self-contained |
| Quick run command | `python scripts/test_icp_scorer.py` |
| Full suite command | `python scripts/test_icp_scorer.py` (same file) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INTEL-01 | 4 dimensions scored correctly, capped at 10 | unit | `python scripts/test_icp_scorer.py` | Yes — 17 tests cover all 4 dimensions |
| INTEL-02 | Confidence: HIGH/MED/LOW based on dim count | unit | `python scripts/test_icp_scorer.py` | Partially — new edge case (a) adds explicit confidence check |
| INTEL-03 | Score breakdown readable by salesperson | unit | `python scripts/test_icp_scorer.py` | Yes — `plain_english non-empty` test covers this |

### Sampling Rate

- **Per task commit:** `python scripts/test_icp_scorer.py`
- **Per wave merge:** `python scripts/test_icp_scorer.py`
- **Phase gate:** All 19 tests green (17 existing + 2 new) before `/gsd:verify-work`

### Wave 0 Gaps

None — existing test infrastructure covers all phase requirements. The 2 new tests are appended, not created in a new file.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `config.py COMPANIES` plain dict list | `companies.py Company dataclass` with full metadata | This phase | Downstream modules get typed access; `slug` enables filesystem key; `known_industry_hint` feeds scorer directly |

**Deprecated after this phase:**
- `config.py COMPANIES` dict list: replaced by `companies.py`. `config.py` itself is retained for all non-company config.

---

## Open Questions

1. **Sealed Air, P&G, Colgate expected_icp_tier**
   - What we know: their `known_industry_hint` strings contain tier-4 keywords ("polymer", "chemical") so `score_industry_fit()` will return 4, not 2
   - What's unclear: the CONTEXT.md assigns them MED — but if the hint contains "polymer" → tier-4 match → HIGH industry fit
   - Recommendation: Set their `expected_icp_tier` to "HIGH" for consistency, OR deliberately omit tier-4 keywords from their hint if they are truly MED targets. Since `expected_icp_tier` is purely a validation label and does not affect scoring, accuracy of the hint takes priority. Planner should decide.

2. **Caterpillar hint — equipment manufacturer vs. user**
   - What we know: Caterpillar manufactures equipment (engines, motors, hydraulics) — they ARE heavy machinery users in their own factories
   - What's unclear: whether "industrial manufacturing" tier-2 is accurate, or whether "automotive" (tier-4) or "construction equipment manufacturing" (already in tier-2 per icp_scorer.py) applies
   - Recommendation: Use "construction equipment manufacturing industrial manufacturing" to hit tier-2. Caterpillar's own manufacturing facilities do use the exact rotating machinery Tractian monitors (CNC, assembly lines, testing rigs). MED expected_icp_tier is defensible.

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/pipeline/icp_scorer.py` (333 lines, fully read)
- Direct code inspection: `src/pipeline/schema.py` (complete schema)
- Direct code inspection: `src/pipeline/config.py` (existing 20-company list)
- Direct code inspection: `scripts/test_icp_scorer.py` (17 tests)
- Live test run: `python scripts/test_icp_scorer.py` → 17/17 passed (confirmed 2026-04-15)
- Live edge case verification: `score_operational_scale(None, None)` → score=0, confidence=LOW
- Live edge case verification: `score_industry_fit("general manufacturing industrial operations")` → score=2

### Secondary (MEDIUM confidence)
- `.planning/phases/02-icp-rubric-company-list/02-CONTEXT.md` — decision log (decisions locked)
- `.planning/REQUIREMENTS.md` — INTEL-01 through INTEL-03 specification
- `INDUSTRY_FIT_TIERS` keyword analysis — manually traced tier assignments for all 20 companies

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all existing packages verified installed
- Architecture: HIGH — existing patterns clear and tested; `companies.py` pattern is straightforward Python
- Pitfalls: HIGH — identified from direct code inspection, not speculation
- Company data: MEDIUM — ticker symbols from CONTEXT.md specifics section; industry hints verified against scorer keywords but not against live company data
- Schema completeness: HIGH — verified by import test and live scorer run

**Research date:** 2026-04-15
**Valid until:** Stable — no external dependencies; valid until icp_scorer.py is changed
