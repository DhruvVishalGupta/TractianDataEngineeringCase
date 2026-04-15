# Roadmap: Tractian GTM Data Engineering Pipeline

**Created:** 2026-04-15
**Milestone:** v1.0 — Internship Case Submission

## Overview

9-phase execution plan from environment setup to final polish. Phases 3–5 (data collection, intelligence, orchestration) are the core value. Phases 6–7 (API + dashboard) are the bonus requirement. Phase 8 is the integration run. Phase 9 is polish.

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5
                                              ↓
                               Phase 6 ← ← ← ┘
                                   ↓
                               Phase 7
                                   ↓
                               Phase 8
                                   ↓
                               Phase 9
```

---

## Phase 1: Environment & Scaffold

**Goal:** Verified working environment, full project scaffold, all dependencies installed

**Plans:**
3/3 plans complete
2. Install Python dependencies (requests, pydantic, firecrawl-py, openpyxl, pandas, tqdm, httpx, tenacity)
3. Create project directory structure: src/pipeline/, src/api/, src/dashboard/, data/raw/, data/processed/, outputs/
4. Create base config (config.py with company list, ICP weights, taxonomy, Ollama URL)

**Covers:** INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05

---

## Phase 2: ICP Rubric & Company List

**Goal:** ICP scoring engine implemented and tested, company list finalized with metadata

**Plans:**
1. Implement ICP scorer module (icp_scorer.py) with all 4 dimensions, confidence logic, score breakdown structure
2. Write unit tests for scorer with edge cases (all zeros, all max, mixed, private companies)
3. Create company registry (companies.py) with all 20 companies, domains, known industries

**Covers:** INTEL-01, INTEL-02, INTEL-03

---

## Phase 3: Data Collection Layer

**Goal:** Multi-source data collection working for all 20 companies; raw data cached per company

**Plans:**
1. Firecrawl scraper module (scraper.py) — homepage + location page discovery + sitemap parsing + content extraction
2. Playwright fallback module (playwright_scraper.py) — JS-rendered pages, scroll-triggered lazy loading
3. Brave Search module (searcher.py) — ≥5 targeted queries per company, snippet extraction with source URLs
4. SEC EDGAR module (edgar.py) — 10-K Properties section (Item 2) extraction for US public companies
5. Firmographics module (firmographics.py) — revenue, employees, industry, HQ from Wikipedia/Macrotrends/Craft
6. Raw data storage system — per-company JSON files in data/raw/{company_slug}/

**Covers:** DATA-01 through DATA-07

---

## Phase 4: Intelligence Layer

**Goal:** Ollama-powered facility classification, ICP scoring with breakdowns, confidence validation

**Plans:**
1. Ollama client module (ollama_client.py) — Pydantic schemas, retry logic, temperature 0, structured output
2. Facility classifier (classifier.py) — taxonomy enforcement, classification basis generation, confidence assignment
3. Location extractor (location_extractor.py) — parse raw scraped/search content into candidate locations
4. Cross-reference validator (validator.py) — Brave Search per facility, confidence upgrade/downgrade logic, needs_verification flag
5. Deduplicator (deduplicator.py) — fuzzy city+country matching, source count tracking, source URL merging

**Covers:** INTEL-04 through INTEL-10

---

## Phase 5: Orchestrator & Output

**Goal:** Full pipeline orchestrated end-to-end; all 3 output files generated

**Plans:**
1. Orchestrator (orchestrator.py) — company iteration, phase coordination, tqdm progress, failure logging
2. Output schema (schema.py) — dataclass/Pydantic model for final row with all required columns
3. CSV writer (output_csv.py) — UTF-8, all columns, ≥60 rows
4. Excel writer (output_xlsx.py) — 3 sheets with full formatting, conditional colors, filters, sort
5. JSON writer (output_json.py) — nested score breakdowns, all fields, dashboard-ready structure

**Covers:** OUT-01 through OUT-05

---

## Phase 6: FastAPI Backend

**Goal:** Clean REST API serving pipeline data with all required endpoints

**Plans:**
1. FastAPI app scaffold (api/main.py) — CORS, data loading from tractian_leads.json
2. Leads endpoint (GET /leads) — filter params: score_min, score_max, facility_type, country, confidence, company
3. Companies endpoints (GET /companies, GET /companies/{name})
4. Stats + distributions endpoints (GET /stats, GET /distributions)
5. API documentation and startup test

**Covers:** API-01 through API-05

---

## Phase 7: React Dashboard

**Goal:** Full-featured sales intelligence dashboard, all components working, no UI bugs

**Plans:**
1. Vite+React scaffold with TypeScript, Tailwind CSS, dark theme tokens, glass morphism components
2. API client layer + React Query for data fetching, filter state management
3. KPI strip component + header with Tractian branding
4. World map component (Mapbox GL or Deck.gl) — facility dots, hover tooltips, click side panel, clustering
5. Filter panel component — score slider, multi-selects, search, active filter count
6. Leads table component — sortable, paginated, expandable rows with score breakdowns
7. Company scorecard component — score gauge, dimension breakdown, facility list, mini-map
8. Pipeline intelligence panel — donut chart, bar chart, metadata

**Covers:** DASH-01 through DASH-09

---

## Phase 8: Full Pipeline Run & Integration Test

**Goal:** Pipeline runs on all 20 companies; ≥60 rows in CSV; dashboard renders real data; no visible bugs

**Plans:**
1. Run full pipeline on all 20 companies; monitor, fix any runtime failures
2. Verify output files: CSV row count, XLSX formatting, JSON structure
3. Verify top scorer coverage: Cargill, Dow, ArcelorMittal, Kraft Heinz each have ≥10 facilities
4. Start FastAPI server, load dashboard, verify map renders real dots, all filters work
5. Fix any integration issues found during test

**Covers:** DATA-07 (coverage), all output + dashboard requirements end-to-end

---

## Phase 9: README, Polish & Final Checklist

**Goal:** Submission-ready — README impressive, code clean, all deliverables verified

**Plans:**
1. Write README: ICP explanation, scoring rubric, 3 worked examples, ASCII architecture diagram
2. Write README: source rationale, SEC EDGAR gold standard, known limitations, setup instructions, "what next"
3. Code polish: meaningful error handling, remove dead code, ensure tqdm logging is informative
4. Final checklist: all 6 definition-of-done criteria verified; run dashboard demo flow end-to-end

**Covers:** DOC-01 through DOC-06

---

## Coverage Summary

| Phase | Requirements Covered | Count |
|-------|---------------------|-------|
| Phase 1 | INFRA-01 to INFRA-05 | 5 |
| Phase 2 | INTEL-01 to INTEL-03 | 3 |
| Phase 3 | DATA-01 to DATA-07 | 7 |
| Phase 4 | INTEL-04 to INTEL-10 | 7 |
| Phase 5 | OUT-01 to OUT-05 | 5 |
| Phase 6 | API-01 to API-05 | 5 |
| Phase 7 | DASH-01 to DASH-09 | 9 |
| Phase 8 | Integration (all) | — |
| Phase 9 | DOC-01 to DOC-06 | 6 |
| **Total** | | **47** |

All 44 v1 requirements covered (+ 3 INTEL from Phase 2 counted separately above). ✓

---
*Roadmap created: 2026-04-15*
