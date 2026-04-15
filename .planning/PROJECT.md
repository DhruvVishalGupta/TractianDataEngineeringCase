# Tractian GTM Data Engineering Pipeline

## What This Is

An automated intelligence pipeline that ingests 20 industrial companies and produces: (1) a structured, CRM-ready flat file where every row is a single verified facility — scored, classified, confidence-flagged, and source-attributed — and (2) a beautiful, interactive sales intelligence dashboard for Account Executives to explore, filter, and act on the data. Built as a competitive internship case submission for Tractian's GTM Data Engineering role.

## Core Value

A sales team must be able to open the output and immediately identify high-value industrial targets with enough confidence to make a cold call — every row must be defensible, every score must be explainable.

## Requirements

### Validated

- ✓ All 14 pipeline modules import cleanly (namespace packages, no `src/__init__.py` needed) — Phase 1
- ✓ Ollama qwen2.5:7b callable via `classify_facility`; returns valid `OllamaFacilityResponse` — Phase 1
- ✓ ICP scoring engine (all 4 dimensions) correct — 17/17 unit tests passed — Phase 1
- ✓ Raw data store (`save_raw/load_raw/has_raw`) wired to `data/raw/{slug}/` — Phase 1
- ✓ Failure logging (`log_failure`) writes to `logs/failures.log` — Phase 1

### Active

- [ ] Full pipeline runs on all 20 companies end-to-end without crashing
- [ ] tractian_leads.csv has ≥60 rows, no fabricated addresses, every row has source URL
- [ ] tractian_leads.xlsx has 3 formatted sheets (All Leads, Company Summary, High Value Targets) with professional formatting
- [ ] tractian_leads.json has complete nested score breakdowns for dashboard consumption
- [ ] ICP scoring rubric implemented across 4 dimensions (Industry Fit, Operational Scale, Physical Footprint, Equipment Dependency)
- [ ] Ollama qwen2.5:7b used for all LLM inference (facility classification, reasoning)
- [ ] FastAPI backend serves clean REST API from JSON pipeline output
- [ ] React/Vite frontend with dark theme, world map, filter panel, leads table, company scorecard
- [ ] All 20 companies processed; top ICP scorers (Cargill, Dow, ArcelorMittal, Kraft Heinz) have ≥10 facilities each
- [ ] README covers ICP rubric, 3 worked examples, source rationale, architecture diagram, known limitations

### Out of Scope

- Real-time data streaming — batch pipeline is sufficient for the use case
- User authentication for the dashboard — internship demo, not production SaaS
- Paid data sources (Clearbit, ZoomInfo, D&B) — must use free/public sources only
- Anthropic API or any external LLM — all inference via local Ollama
- Mobile-responsive design — targeting 1440p desktop AE workflow

## Context

- **Evaluators**: Senior GTM and data engineering professionals; will judge source selection logic, pipeline architecture, ICP reasoning quality, and output polish
- **Scoring criteria**: 4 dimensions totaling 10 points — Industry Fit (0-4), Operational Scale (0-3), Physical Footprint (0-2), Equipment Dependency (0-1)
- **Data sources hierarchy**: SEC EDGAR 10-K Properties (gold standard for US public) > Company website scraping > Brave Search > Wikipedia/Macrotrends
- **LLM**: Ollama at localhost:11434 with qwen2.5:7b — temperature 0, structured output with Pydantic schemas
- **20 Companies**: span full ICP spectrum from perfect matches (Dow, Cargill, ArcelorMittal) to clear misses (Salesforce, Stripe, Airbnb)
- **Private companies**: Cargill, SpaceX — flag SEC data unavailability explicitly, rely on press/website
- **Dashboard**: Dark theme (#0A0F1C), cyan accent (#00D4FF), glass morphism — Vercel dashboard meets Bloomberg terminal

## Constraints

- **LLM**: Ollama localhost:11434 qwen2.5:7b only — no Anthropic API, no external LLM services
- **Data integrity**: Never fabricate addresses; LOW confidence + source URL = company homepage is acceptable floor
- **Coverage**: ≥60 total rows in CSV; top scorers ≥10 facilities each
- **Stack**: Python pipeline, FastAPI backend, React+Vite frontend, Mapbox GL or Deck.gl for map
- **OS**: Windows 11, bash shell available
- **Presentation**: Output must look professional enough to demo live to a VP without modification

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Ollama qwen2.5:7b for all inference | Required by brief; local, free, deterministic at temp=0 | ✓ Confirmed callable, 3/3 smoke tests pass |
| Multi-source pipeline (Firecrawl + Brave + Playwright + SEC EDGAR) | No single source is complete; triangulation = higher confidence | — Pending (Phase 3) |
| FastAPI + React/Vite stack | Standard, fast to build, professional output | — Pending (Phases 6-7) |
| Store raw scraped data per company | Enables re-running intelligence layer without re-scraping | ✓ `raw_store.py` implemented and verified |
| Flat file row = one unique facility | CRM-ready format as required by brief | — Pending (Phase 5) |
| pip freeze for requirements.txt | Full environment reproducibility; 217 packages pinned | ✓ Phase 1 |

---
*Last updated: 2026-04-15 after Phase 1 (Environment & Scaffold)*
