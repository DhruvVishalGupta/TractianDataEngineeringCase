# Phase 2: ICP Rubric & Company List — Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Finalize the ICP scoring engine and create a rich company registry. Phase 2 covers INTEL-01, INTEL-02, INTEL-03. The scoring engine was scaffolded in Phase 1 — this phase verifies and finalizes it, adds missing edge-case tests, and builds the `companies.py` module that downstream data collection and intelligence phases will use as their authoritative company list.

**Important:** `icp_scorer.py` already exists and 17/17 unit tests pass. Plans that say "implement" should be interpreted as "verify, finalize, and fill gaps" — NOT rebuild from scratch.

</domain>

<decisions>
## Implementation Decisions

### ICP Scorer Status
- **D-01:** `src/pipeline/icp_scorer.py` is already fully implemented (333 lines, all 4 dimensions). Do NOT rewrite it.
- **D-02:** `scripts/test_icp_scorer.py` has 17 passing tests. Add 2 additional edge cases: (a) private company with `employees=None, revenue_billions=None` → should not crash, score operational scale = 0 LOW; (b) borderline industry (tier-2 match → score=2).
- **D-03:** Confirm `ICPScore` and `ScoreDimension` Pydantic schemas in `schema.py` are complete and match what `icp_scorer.py` returns. If minor gaps exist, fix them — do not redesign.

### companies.py Schema
- **D-04:** Create `src/pipeline/companies.py` as the authoritative company registry. Each entry is a typed dataclass or Pydantic model with these fields:
  - `name: str` — display name (e.g. "Dow Chemical")
  - `slug: str` — filesystem key (e.g. "dow-chemical") used for `data/raw/{slug}/`
  - `website: str` — primary domain without https:// (e.g. "dow.com")
  - `is_public: bool` — True = SEC EDGAR available
  - `sec_ticker: str | None` — stock ticker for EDGAR lookup (None if private)
  - `known_industry_hint: str` — single string hint fed to `score_industry_fit()` (e.g. "petrochemical polymer manufacturing")
  - `expected_icp_tier: str` — "HIGH" | "MED" | "LOW" — for validation; does NOT affect scoring
- **D-05:** Revenue and employees are NOT stored in companies.py — they are discovered at runtime by `firmographics.py`.
- **D-06:** All 20 companies must be present. The 4 obvious non-ICP targets (Salesforce, Stripe, Spotify, Airbnb) stay in the list — they demonstrate the full scoring spectrum.

### Private Company Handling
- **D-07:** Private companies (Cargill, Stripe, SpaceX) have `is_public: False` and `sec_ticker: None`. They will be flagged in the pipeline output with `sec_data: "unavailable"`. No other special treatment — pipeline still processes all 20 fully.

### Fast-Fail for Non-ICP Companies
- **D-08:** No fast-fail. All 20 companies run through the full pipeline. Expected low scorers are noted in `expected_icp_tier: "LOW"` but not skipped — the output must demonstrate the full ICP spectrum.

### companies.py as Import Source
- **D-09:** `config.py`'s `COMPANIES` list is superseded by `companies.py`. After Phase 2, downstream modules import from `companies.py`, not `config.py`. `config.py` retains non-company config (Ollama URL, paths, search templates).
- **D-10:** Provide a `get_all_companies()` function returning `list[Company]` and a `get_company_by_slug(slug: str) -> Company | None` helper. These are the only public API.

### Claude's Discretion
- Whether to use a dataclass or Pydantic BaseModel for the Company type (either is fine)
- Internal ordering of companies in the list
- Whether to add a `__repr__` for debugging

</decisions>

<specifics>
## Specific Ideas

- The 20 companies span the full ICP spectrum intentionally — top scorers (Cargill, Dow, ArcelorMittal, Kraft Heinz, Mosaic) should have `expected_icp_tier: "HIGH"`; clear misses (Salesforce, Stripe, Airbnb, Spotify) should be `"LOW"`.
- `known_industry_hint` should be specific enough to feed directly into `score_industry_fit()` — e.g. "meat processing and food manufacturing" not just "food".
- `sec_ticker` for major companies: Dow = DOW, Tyson = TSN, Kraft Heinz = KHC, Mosaic = MOS, ArcelorMittal = MT, AB InBev = BUD, International Paper = IP, Sealed Air = SEE, Caterpillar = CAT, P&G = PG, Colgate = CL, Mondelez = MDLZ, McDonald's = MCD, Walmart = WMT, Salesforce = CRM, Spotify = SPOT, Airbnb = ABNB.

</specifics>

<canonical_refs>
## Canonical References

No external spec files — all requirements are captured in REQUIREMENTS.md and decisions above.

### ICP Scoring Rubric
- `.planning/REQUIREMENTS.md` §Intelligence Layer — INTEL-01 through INTEL-03 define the full scoring spec

### Existing Implementation
- `src/pipeline/icp_scorer.py` — existing scorer implementation (finalize, do not rewrite)
- `src/pipeline/schema.py` — ICPScore and ScoreDimension Pydantic schemas
- `src/pipeline/config.py` — existing COMPANIES list to reference/migrate (company names, websites, is_public)
- `scripts/test_icp_scorer.py` — existing 17-test suite (add 2 edge cases, do not remove any)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `icp_scorer.py:calculate_icp_score()` — main entry point, already complete and tested
- `schema.py:ICPScore` and `ScoreDimension` — Pydantic models for scoring output
- `config.py:COMPANIES` — 20 companies with name/website/is_public already defined (migrate to companies.py)

### Established Patterns
- All pipeline modules use `from .schema import ...` — companies.py should follow the same pattern
- Logger: `from .logger import get_logger; log = get_logger("companies")`
- No hardcoded per-company data in scoring logic — scoring is always runtime-discovered

### Integration Points
- Phase 3 (data collection) imports company list from `companies.py` to drive scraping/search loops
- Phase 4 (intelligence) imports `calculate_icp_score` and will call it with runtime-discovered data
- Phase 5 (orchestrator) iterates `get_all_companies()` to drive the pipeline run

</code_context>

<deferred>
## Deferred Ideas

- Per-company known CIK number in companies.py — EDGAR module can discover CIK dynamically from ticker; not needed in Phase 2
- Industry synonym expansion in icp_scorer.py — if rubric misses edge cases, fix in Phase 4 after real data is collected

</deferred>

---

*Phase: 02-icp-rubric-company-list*
*Context gathered: 2026-04-15*
