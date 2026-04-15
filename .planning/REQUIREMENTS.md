# Requirements: Tractian GTM Data Engineering Pipeline

**Defined:** 2026-04-15
**Core Value:** Sales team opens the output and immediately identifies high-value industrial targets with defensible, explainable scores

## v1 Requirements

### Pipeline Infrastructure

- [ ] **INFRA-01**: Environment verified — Ollama reachable, qwen2.5:7b responds, all MCPs connected
- [ ] **INFRA-02**: Project scaffold created with modular architecture (scraper, searcher, firmographics, scorer, classifier, validator, orchestrator, output modules)
- [ ] **INFRA-03**: Raw scraped data stored per company in structured directory for re-run without re-scraping
- [ ] **INFRA-04**: tqdm progress tracking throughout pipeline run
- [ ] **INFRA-05**: Dedicated failure log file; pipeline never crashes on single company failure

### Data Collection

- [ ] **DATA-01**: Firecrawl scrapes homepage + discovers location-relevant pages (locations, facilities, plants, offices, global, contact, manufacturing, operations, sitemap.xml)
- [ ] **DATA-02**: Playwright fallback for JS-rendered location finders when Firecrawl returns <3 locations
- [ ] **DATA-03**: Brave Search fires ≥5 targeted queries per company (manufacturing locations, worldwide operations, industry-specific facilities, SEC/annual report properties, industrial operations keywords)
- [ ] **DATA-04**: SEC EDGAR 10-K Properties section (Item 2) extracted for all US public companies
- [ ] **DATA-05**: Firmographics (revenue, employee count, industry, headquarters) sourced from Wikipedia/Macrotrends/Craft.co/Bloomberg
- [ ] **DATA-06**: Private companies (Cargill, SpaceX) explicitly flagged as no SEC data available
- [ ] **DATA-07**: All 20 companies have ≥1 facility in output

### Intelligence Layer

- [ ] **INTEL-01**: ICP scoring engine implements all 4 dimensions: Industry Fit (0-4), Operational Scale (0-3), Physical Footprint (0-2), Equipment Dependency (0-1), capped at 10
- [ ] **INTEL-02**: Score confidence: HIGH (all 4 dims confident), MED (2-3 dims), LOW (<2 dims)
- [ ] **INTEL-03**: Score breakdown stored as structured object — a salesperson can read it and understand every point awarded
- [ ] **INTEL-04**: Facility classification via Ollama qwen2.5:7b with Pydantic schema — taxonomy: Manufacturing Plant, Packaging Plant, Processing Plant, Distribution Center, Corporate HQ, R&D Center, Sales Office, Refinery, Mine and Extraction Site, Power Plant, Unknown
- [ ] **INTEL-05**: Classification basis is specific (cites actual source, not generic phrases)
- [ ] **INTEL-06**: Confidence levels: HIGH (explicit label in primary source), MED (inferred from strong context), LOW (guessed from location name), ESTIMATED (best guess, no context)
- [ ] **INTEL-07**: Ollama retry mechanism — retry once with stricter prompt on malformed output, then fail gracefully
- [ ] **INTEL-08**: Cross-reference validation via Brave Search per facility; upgrade/downgrade confidence based on corroboration
- [ ] **INTEL-09**: needs_verification=true for locations with zero independent corroboration
- [ ] **INTEL-10**: Deduplication by fuzzy city+country match; source count tracked per location

### Output Files

- [ ] **OUT-01**: tractian_leads.csv — all columns, UTF-8, ≥60 rows, no fabricated addresses, every row has source_url
- [ ] **OUT-02**: tractian_leads.xlsx Sheet 1 "All Leads" — frozen header, auto-fitted columns, alternating row shading, conditional color on ICP score (green 8-10, amber 5-7, red 1-4), confidence color coding, filters on all columns, sorted by ICP score desc
- [ ] **OUT-03**: tractian_leads.xlsx Sheet 2 "Company Summary" — one row per company, plain-English score breakdown, facility counts by type, data quality indicator
- [ ] **OUT-04**: tractian_leads.xlsx Sheet 3 "High Value Targets" — companies scoring ≥8, top facilities, sorted by score desc
- [ ] **OUT-05**: tractian_leads.json — complete structured output with nested score breakdowns for dashboard

### API

- [ ] **API-01**: FastAPI backend starts cleanly, serves tractian_leads.json as data source
- [ ] **API-02**: Endpoint: GET /leads with filter params (score range, facility type, country, confidence, company search)
- [ ] **API-03**: Endpoint: GET /companies — list + individual company detail
- [ ] **API-04**: Endpoint: GET /stats — summary statistics
- [ ] **API-05**: Endpoint: GET /distributions — facility type and confidence distribution data

### Dashboard

- [ ] **DASH-01**: React+Vite SPA with dark theme (#0A0F1C), cyan accent (#00D4FF), glass morphism cards
- [ ] **DASH-02**: Header with Tractian brand treatment, navigation, live data indicator
- [ ] **DASH-03**: KPI strip — Total Companies, Total Facilities, Average ICP Score, High Value Targets count
- [ ] **DASH-04**: World map (Mapbox GL or Deck.gl) with facility dots colored/sized by ICP tier, rich hover tooltips, click-to-detail side panel, cluster at low zoom
- [ ] **DASH-05**: Filter panel — ICP score range slider, facility type multi-select, country multi-select, confidence filter, company name search; all filters update map + table simultaneously
- [ ] **DASH-06**: Leads table — paginated, sortable, all columns, expandable rows showing score breakdown and classification basis
- [ ] **DASH-07**: Company scorecard — ICP score gauge/ring, score breakdown by dimension, facility list, mini-map
- [ ] **DASH-08**: Pipeline intelligence panel — run metadata, source counts, confidence donut chart, facility type bar chart, failed companies log
- [ ] **DASH-09**: Dashboard loads fast, no visible UI bugs or console errors, all filters work correctly

### Documentation

- [ ] **DOC-01**: README covers: Tractian ICP in plain English, full scoring rubric, 3 worked examples (perfect match, borderline, clear miss)
- [ ] **DOC-02**: README covers: source selection rationale with reliability ranking, SEC EDGAR called out as gold standard
- [ ] **DOC-03**: README covers: ASCII pipeline architecture diagram
- [ ] **DOC-04**: README covers: known limitations (private company gaps, JS-rendered pages, facility classification ambiguity, false positive risk)
- [ ] **DOC-05**: README covers: full setup and run instructions
- [ ] **DOC-06**: README covers: "what I would build next" section

## v2 Requirements

### Enhancements (post-submission)

- **ENH-01**: Real-time pipeline re-run trigger from dashboard
- **ENH-02**: CRM direct integration (Salesforce/HubSpot API)
- **ENH-03**: Email alerting when new high-value targets discovered
- **ENH-04**: Historical scoring trend tracking per company

## Out of Scope

| Feature | Reason |
|---------|--------|
| External LLM APIs (OpenAI, Anthropic, etc.) | Brief explicitly requires local Ollama only |
| Paid data sources (Clearbit, ZoomInfo, D&B) | Must use free/public sources only |
| User authentication | Demo scope, not production SaaS |
| Mobile-responsive design | Desktop AE workflow at 1440p |
| Real-time streaming pipeline | Batch is sufficient; complexity not justified |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 through INFRA-05 | Phase 1 | Pending |
| DATA-01 through DATA-07 | Phase 3 | Pending |
| INTEL-01 through INTEL-10 | Phase 4 | Pending |
| OUT-01 through OUT-05 | Phase 5 | Pending |
| API-01 through API-05 | Phase 6 | Pending |
| DASH-01 through DASH-09 | Phase 7 | Pending |
| DOC-01 through DOC-06 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 44 total
- Mapped to phases: 44
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-15*
*Last updated: 2026-04-15 after initial definition*
