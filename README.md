# Tractian GTM — Sales Intelligence Pipeline

Given a company name and website, this system returns a 1–10 fit score against Tractian's ICP plus a CRM-ready list of every facility that company runs, with per-row source attribution and confidence.

```
20 companies  ·  240 unique facilities  ·  31 countries  ·  100% geocoded
SEC EDGAR 10-K  ·  Firecrawl  ·  Brave Search OSINT  ·  Claude Haiku 4.5  ·  OpenStreetMap
```

The case submission covers all four evaluation criteria: the ICP is defined in code and scored consistently, sources are chosen for reliability (not convenience), the pipeline plumbing is visible, and there's a dashboard with filtering, a world map, and a live-demo endpoint that processes any new company on the fly.

---

## TL;DR — what the thing actually does

Two inputs go in:

```
"Dow Chemical"  +  "dow.com"
```

~60 seconds later, 34 rows come out:

| Company | Website | ICP | Facility Location | Type | Confidence | Source |
|---|---|---|---|---|---|---|
| Dow Chemical | dow.com | 9 | Midland, MI, USA | Corporate HQ | HIGH | SEC EDGAR 10-K |
| Dow Chemical | dow.com | 9 | Freeport, TX, USA | Manufacturing Plant | HIGH | SEC EDGAR 10-K |
| Dow Chemical | dow.com | 9 | Terneuzen, Netherlands | Manufacturing Plant | HIGH | SEC EDGAR 10-K |
| Dow Chemical | dow.com | 9 | Tarragona, Spain | Manufacturing Plant | HIGH | SEC EDGAR 10-K |
| … | … | … | … | … | … | … |

Every row has lat/lon, a classification basis, and an audit trail back to the exact URL it was extracted from.

---

## Architecture

```
  ┌─────────────────────────────────────────┐
  │  INPUT — { name, website, ticker? }     │
  └──────────────────┬──────────────────────┘
                     │
 ╔═══════════════════╪════════════════════════════════════════════════╗
 ║   1. DISCOVERY                                                      ║
 ║                                                                     ║
 ║   Brave Search ─────── OSINT dorks → deep-link facility URLs        ║
 ║                        site:co.com ("plant" OR refinery OR mill)    ║
 ║                                                                     ║
 ║   SEC EDGAR ────────── ticker → CIK → 10-K / 20-F Item 2 Properties ║
 ║                        (legally-mandated facility disclosures)      ║
 ║                                                                     ║
 ║   Wikipedia API ────── infobox → revenue, employees, industry, HQ   ║
 ╚═══════════════════╪═════════════════════════════════════════════════╝
                     │
 ╔═══════════════════╪═════════════════════════════════════════════════╗
 ║   2. EXTRACTION                                                     ║
 ║                                                                     ║
 ║   Firecrawl ────────── JS-rendered Markdown from each discovered    ║
 ║                        URL (company site / press releases)          ║
 ║                                                                     ║
 ║   Claude Haiku 4.5 ── tool-use JSON extraction with strict schema,  ║
 ║                        facility-type taxonomy, ownership rules;     ║
 ║                        cached by input fingerprint so iterative     ║
 ║                        runs are free                                ║
 ╚═══════════════════╪═════════════════════════════════════════════════╝
                     │
 ╔═══════════════════╪═════════════════════════════════════════════════╗
 ║   3. VALIDATION                                                     ║
 ║                                                                     ║
 ║   Quote traceability — model's quote must appear in source text     ║
 ║   Ownership guard    — facility must be tied to the target company  ║
 ║   Regional-HQ guard  — "India HQ" ≠ global HQ → Sales Office        ║
 ║   OSINT corroboration — second Brave pass grades strong/weak/none   ║
 ║   Reclassifier       — regex rules refine Manufacturing → Refinery  ║
 ║                        / Mine / Packaging / Processing / Distr.     ║
 ║   Deduplicator       — merge by city+country+type; cross-source     ║
 ║                        confidence boost                             ║
 ╚═══════════════════╪═════════════════════════════════════════════════╝
                     │
 ╔═══════════════════╪═════════════════════════════════════════════════╗
 ║   4. ENRICH + SCORE                                                 ║
 ║                                                                     ║
 ║   Nominatim ────────── lat/lon per facility (free, polite RL)       ║
 ║   ICP Scorer ────────── 4-dimension rubric + market modifier → 0-10 ║
 ║   HQ fallback ─────── 1 row per company even if no plants found     ║
 ╚═══════════════════╪═════════════════════════════════════════════════╝
                     │
  ┌──────────────────┴──────────────────────────────────────────────┐
  │  OUTPUTS                                                         │
  │                                                                  │
  │  • outputs/tractian_leads.csv   (flat, CRM-ready column order)   │
  │  • outputs/tractian_leads.xlsx  (3 styled sheets)                │
  │  • outputs/tractian_leads.json  (nested + flat, for dashboard)   │
  │  • FastAPI backend + React/Vite dashboard with map + filters     │
  └──────────────────────────────────────────────────────────────────┘
```

Every stage is idempotent. The first run takes about 7 minutes; subsequent runs are ~30 seconds because Brave, Firecrawl, EDGAR, Wikipedia, and even Claude are cached per-company in `data/raw/{slug}/`.

---

## Why these 20 companies

The brief says "cover a broad range of Tractian fit and edge cases." I picked the set to break the pipeline in interesting ways, not to cherry-pick easy wins. The four buckets:

### Perfect-fit heavy industry — 9 companies (expected ICP 8–10)
| Company | What it tests |
|---|---|
| **Cargill** | Sample-output reference. Food/oilseed processing at scale. Private, so no EDGAR — forces the website path. |
| **Dow Chemical** | Sample-output reference. Petrochemical complexes. Also where I caught the worst bug: my first CIK lookup did fuzzy name matching and returned Wells Fargo's 10-K for Mosaic. Fixed by using the ticker as the lookup key. |
| **ArcelorMittal** | World's largest steelmaker. Foreign issuer — files a 20-F, not a 10-K. Forces the EDGAR module to handle both form types. |
| **International Paper** | Pulp & paper. Tests the paper-mill keyword path. |
| **Caterpillar** | Heavy equipment. Their Wikipedia industry string contains "Financial services" as a tier-0 keyword, which originally capped their score at 1/4. Real fix required: don't cap tier-0 unless industrial signals are absent. |
| **Mosaic Company** | Phosphate / potash mining. Only company where "Mine and Extraction Site" is the dominant facility type. |
| **Tyson Foods** | Chicken/beef processing. Sparse Wikipedia infobox (no HQ, no revenue), forces snippet-based HQ recovery. |
| **Mondelez International** | FMCG snacks. Multiple tier-3 keywords that should collectively promote to tier-4. |
| **Sealed Air** | Protective packaging. Extremely sparse 10-K Properties section — tests the coverage-thin edge. |

### FMCG / mid-tier industrial — 4 companies (expected 7–9)
| Company | What it tests |
|---|---|
| **Kraft Heinz** | Sample-output reference. Ticker lookup (KHC). Also the 10-K has "69 manufacturing and processing facilities" as a summary without listing individual cities — a precision-over-recall test. |
| **Anheuser-Busch InBev** | Breweries. Tests the `brewery → Packaging Plant` reclassifier rule. |
| **Procter & Gamble** | 109k employees, 170+ brands, but their 10-K Properties is one paragraph. Coverage stress test. |
| **Colgate-Palmolive** | Same category as P&G. |

### Borderline — 2 companies (expected 5–7)
| Company | What it tests |
|---|---|
| **SpaceX** | Sample-output reference at 7/10. Private company, no SEC. Wikipedia HQ is "SpaceX Starbase" with no country. |
| **Walmart** | Retail with a massive logistics network. Should land tier-1 (retail), not tier-4 — they have DCs, not petrochemical complexes. |

### Clear miss — 5 companies (expected 2–5)
| Company | What it tests |
|---|---|
| **McDonald's** | Sample-output reference at 3/10. Fast food (tier-1). Tests restaurant-specific disambiguation so "food" alone doesn't promote them to tier-4. |
| **Stripe** | Pure fintech. Private. Dual-HQ (Dublin, Ireland + San Francisco). Tests HQ parsing and tier-0 cap. |
| **Salesforce** | Pure SaaS. Tests tier-0 dominance when industry string has multiple tier-0 keywords. |
| **Spotify** | Streaming. Foreign issuer (20-F). No physical plants — tests HQ fallback row. |
| **Airbnb** | Marketplace. Wikipedia HQ missing from infobox — tests Forbes-style "Headquarters · San Francisco" pattern recovery. |

---

## Source selection — what I chose and why

The case brief explicitly grades "Source Selection." I evaluated each candidate on three axes: **reliability** (will it lie to me?), **coverage** (does it have data for the 20 companies?), and **cost** (API fees + maintenance). Here's the shortlist.

### SEC EDGAR — the gold standard

Item 2 ("Properties") of a 10-K is a legally-mandated disclosure. If a publicly-traded US company tells the SEC they operate a plant in Freeport, Texas, that's defensible data with regulatory weight. No other source comes close.

**What I had to get right:**
- **CIK resolution via ticker, not name.** My first attempt did fuzzy name matching against `company_tickers.json` — it returned Wells Fargo's CIK when I searched for "Mosaic" (because Wells Fargo has a subsidiary with "Mosaic" in the title). The current implementation uses the registered ticker symbol as an exact-match primary key.
- **20-F support.** ArcelorMittal, Spotify, and Anheuser-Busch InBev file 20-F forms because they're foreign issuers. Same Item 2 structure, different form code.
- **Claude-assisted Properties extraction.** My first version used regex to carve "Item 2 ... Properties" out of the HTML. That worked for maybe 3 of 17 companies because modern 10-Ks use XBRL-tagged markup that breaks naive patterns. The current approach uses a carefully-written HTML stripper with multiple anchor patterns, plus a keyword-density filter so I don't accidentally grab Item 3 (Legal Proceedings).
- **Trust-by-CIK.** EDGAR Properties sections typically say "the Company" instead of the legal name. My initial ownership guard required the company's name to appear on the page, which dropped every EDGAR-sourced facility. The fix: if the source URL is on sec.gov, ownership is already proven at fetch time (we wouldn't have pulled this filing if CIK didn't match the ticker).

### Brave Search — deep-link discovery + corroboration

Brave does two jobs in this pipeline:

**1. Deep-link discovery.** I use site-scoped OSINT dorks like:
```
site:dow.com ("manufacturing plant" OR refinery OR "production facility")
```
This is dramatically more effective than a general "Dow Chemical facilities" query, because it bypasses the homepage noise and returns the specific URLs where plants are listed (e.g., `/locations/north-america`, `/operations/products/polyethylene`).

**2. Corroboration.** After Claude extracts a facility, the validator fires a second Brave pass — `"ArcelorMittal" "Contrecoeur" (plant OR facility OR manufacturing)` — and grades the results. Strong corroboration needs ≥2 high-quality hits or one domain-aligned hit with facility-context terms.

I chose Brave over Google because Brave returns clean JSON without CAPTCHA games, the free tier is generous, and the paid tier is ~$5/month for my usage. Google's Custom Search is more expensive and more restricted.

### Firecrawl — JS-rendered scraping

Many industrial companies load their plant lists client-side via React or Vue. A plain `requests.get` on Dow's operations page returns a near-empty shell. Firecrawl runs a headless browser, waits for hydration, and returns clean Markdown.

Alternatives I rejected:
- **Playwright self-hosted** — I'd own the browser infrastructure, the memory leaks, and the chromium updates. Firecrawl is cheaper than a week of my time.
- **Raw HTTP + BeautifulSoup** — fine for static sites, useless for the modern ones.

I cap at 8 URLs per company and prioritize the ones most likely to contain facility data (URL path contains "plant", "operations", "locations", etc.).

### Claude Haiku 4.5 — structured extraction

Two features that matter more than raw model quality:

**Tool use with a strict JSON schema.** The `report_facilities` tool forces the model to return typed objects with required fields. No parsing ambiguity, no trailing markdown. The schema enforces the facility type taxonomy as an enum — the model can't invent "Administrative Building" when I ask it to choose between 11 canonical types.

**Prompt caching.** The system prompt is 2,000+ tokens (taxonomy rules, disambiguation examples, ownership rules). Ephemeral caching on the system block means cache-read input tokens on every call after the first, which is a real cost savings over 20 companies.

I also added content-fingerprint caching in `claude_client.py`: the extraction output is persisted per company to `data/raw/{slug}/claude_facilities_{hash}.json`. Iterative development (tweaking the validator, re-running the scorer) no longer re-fires the extraction. One full pipeline run costs Claude credits; every subsequent run is free.

I chose Haiku 4.5 over Sonnet for cost (it's ~5x cheaper per token) and over GPT-4o-mini because Anthropic's tool-use mode had slightly tighter adherence to the schema in my prototypes.

### Wikipedia — firmographics

Revenue, employee count, industry classification, and headquarters location. The `parse` API returns raw wikitext, which has `|num_employees=36,000` style fields that are straightforward to extract. More reliable than scraping the HTML because the infobox structure is stable across pages.

The one thing Wikipedia gets wrong: HQ parsing. The infobox for dual-HQ companies (Stripe) uses "Dublin, Ireland; San Francisco, California" formatting, and the Airbnb page has the HQ only in the Forbes-import snippet ("Headquarters · San Francisco"). I wrote three fallback patterns in `firmographics.py` to handle these.

### OpenStreetMap Nominatim — geocoding

Free, no API key, 1 req/sec polite rate limit. I cache every lookup in `data/raw/_geocode/cache.json` so the same city string is never geocoded twice. 99% hit rate on the 240 facilities.

---

## The ICP rubric, spelled out

The case says "Define the ICP." Here it is. Four dimensions, maximum 10 points, clamp at both ends.

### Industry Fit (0–4)
The most important dimension. Tractian makes vibration sensors for rotating industrial equipment; if the company doesn't have rotating equipment, nothing else matters.

- **Tier 4** — heavy process industries: chemicals, petrochemicals, refining, mining, steel, pulp & paper, cement, food/beverage processing, heavy equipment manufacturing, automotive assembly.
- **Tier 3** — FMCG with manufacturing, pharma, plastics/rubber, glass, water treatment.
- **Tier 2** — general manufacturing, aerospace, semiconductors, logistics.
- **Tier 1** — retail, restaurants, wholesale distribution.
- **Tier 0** — SaaS, fintech, marketplace, streaming, pure media.

Tier 0 has a hard cap rule: if ≥2 tier-0 keywords match AND zero industrial keywords match, the score is capped at 0. This prevents Salesforce from scoring 2/4 because "logistics" appears in a customer testimonial on their homepage.

### Operational Scale (0–3)
- **3** — ≥10,000 employees AND ≥$1B revenue
- **2** — ≥1,000 employees OR ≥$100M revenue
- **1** — ≥100 employees OR ≥$10M revenue

### Physical Footprint (0–2)
- **2** — ≥10 industrial facilities discovered (manufacturing/processing/refining/mining)
- **1** — 3–9 industrial facilities, or ≥5 total
- **0** — fewer

### Equipment Dependency (0–1)
Binary signal: does the scraped content mention any of ~40 specific rotating-equipment keywords (compressor, turbine, crusher, boiler, kiln, centrifuge, etc.)? I removed `press` from the list because it matches "press release" in marketing text.

### Market Modifier (−1 / 0 / +1)
A corrective. Fires only on strong evidence:
- **+1** when ≥3 distinct PdM-intent signals appear ("predictive maintenance", "condition monitoring", "TPM", "OEE") AND the base score is ≤8.
- **−1** when ≥2 negative signals fire on a base ≥5.

The first version of this modifier was an auto-+1 on any positive signal, which collapsed every industrial company into a tie at 10/10. The current constraints spread 20 companies across 9 distinct scores: **2, 3, 3, 4, 5, 5, 6, 8, 8, 8, 8, 9, 9, 9, 9, 9, 10, 10, 10, 10.**

---

## Validation — why the output is trustworthy

Precision over recall was the guiding principle (it's also a case-brief quote). Every row in the output passed six independent checks:

| Check | Module | What it does |
|---|---|---|
| Valid city | `validator.py` | Drop nulls, "Various", country-as-city, city=country collisions |
| Minimum evidence | `validator.py` | Quote must be ≥15 chars and either contain the city or be substantive enough (≥50 chars) |
| Source mentions company | `validator.py` | Source page must contain company markers (unless it's an SEC filing, which is bound by CIK) |
| Quote traceability | `validator.py` | Model's quote split into 5-word sliding windows; ≥40% must appear in source text — blocks hallucinated quotes |
| Ownership | `validator.py` | Evidence text must reference the target company (not a customer / partner / case-study subject) |
| OSINT corroboration | `validator.py` + `searcher.py` | Second Brave pass grades `strong` / `weak` / `none` |

Then the reclassifier applies typed rules (`refinery` → Refinery, `brewery` → Packaging Plant, `regional headquarters` → Sales Office), and the deduplicator merges identical facilities across sources and boosts confidence for multi-source corroboration.

Final confidence distribution on the 240 rows: **HIGH 123 · MED 55 · LOW 9 · ESTIMATED 53**.

---

## Running it

### Prerequisites
- Python 3.11+
- Node 18+ (for the dashboard)
- `.env` at the project root with:
  ```
  CLAUDE_API_KEY=sk-ant-...
  BRAVE_API_KEY=BSA...
  FIRECRAWL_API_KEY=fc-...
  ```

### Full pipeline
```bash
pip install -r requirements.txt
python -m src.pipeline.orchestrator
```
First run is ~7 minutes. Subsequent runs are ~30 seconds (everything is cached per-company in `data/raw/{slug}/`).

### API + dashboard
```bash
# terminal 1
uvicorn src.api.main:app --port 8000

# terminal 2
cd src/dashboard
npm install
npm run dev
```
Dashboard at http://localhost:5173.

### Live demo
Click **"+ Add company (live demo)"** in the dashboard. Fill in name, website, and optionally the SEC ticker. Hit run. The backend spawns a thread that streams per-stage progress back; the new company and its facilities appear in the table and on the map the moment the pipeline finishes.

Suggested demo input: **ExxonMobil**, `exxonmobil.com`, public, ticker **XOM**. Processes in ~60 seconds and lands ~40 facilities at ICP 10/10.

---

## Output

Three formats, all in `outputs/`:

**`tractian_leads.csv`** — flat file, one row per facility. Column order matches the case's sample output exactly (Company / Website / Score / Location / Classification), followed by city/state/country/lat/lon for direct upload into mapping tools, then provenance fields. 22 columns total.

**`tractian_leads.xlsx`** — three styled sheets:
- **All Leads** — the full flat file with conditional formatting on ICP score
- **Company Summary** — one row per company with plain-English score reasoning
- **High-Value Targets** — filtered to ICP ≥ 8

**`tractian_leads.json`** — nested structure for the dashboard; includes per-company score breakdowns and a flat rows array.

All three are regenerated on every pipeline run. The dashboard's Export menu pulls these directly from the API.

---

## Directory structure

```
TractianCase-DhruvGupta/
├── src/
│   ├── pipeline/            # the pipeline — one module per concern
│   │   ├── orchestrator.py    # top-level driver; one function per phase
│   │   ├── companies.py       # the 20-company registry (typed dataclass)
│   │   ├── searcher.py        # Brave Search: OSINT dorks + corroboration
│   │   ├── scraper.py         # Firecrawl: JS-rendered Markdown
│   │   ├── edgar.py           # SEC EDGAR: ticker → CIK → 10-K/20-F Properties
│   │   ├── firmographics.py   # Wikipedia + Brave snippets for firmographics
│   │   ├── claude_client.py   # Claude Haiku 4.5 tool-use extraction + cache
│   │   ├── validator.py       # 6-check validation + confidence scoring
│   │   ├── reclassifier.py    # deterministic type refinement
│   │   ├── deduplicator.py    # merge by city+country+type, cross-source boost
│   │   ├── icp_scorer.py      # 4-dimension ICP rubric
│   │   ├── geocoder.py        # Nominatim geocoding with local cache
│   │   ├── output_csv.py      # flat CSV writer (CRM-ready ordering)
│   │   ├── output_xlsx.py     # 3-sheet formatted XLSX
│   │   ├── output_json.py     # nested + flat JSON for dashboard
│   │   ├── schema.py          # Pydantic models
│   │   ├── raw_store.py       # per-company disk cache
│   │   ├── logger.py          # configured loggers
│   │   └── config.py          # paths, API keys, rubric parameters
│   │
│   ├── api/                 # FastAPI backend
│   │   └── main.py            # /companies, /leads, /demo/*, /download/*
│   │
│   └── dashboard/           # Vite + React SPA
│       ├── index.html
│       ├── package.json
│       └── src/
│           ├── App.jsx        # table + map + filters + export + live demo
│           ├── App.css
│           └── main.jsx
│
├── data/
│   └── raw/                 # per-company API response cache (Brave, Firecrawl,
│                            # EDGAR, Wikipedia, Claude extractions, OSINT verifications)
│
├── outputs/
│   ├── tractian_leads.csv
│   ├── tractian_leads.xlsx
│   └── tractian_leads.json
│
├── logs/pipeline.log        # generated
├── requirements.txt
├── .env.example             # template for API keys
└── .env                     # not committed (real keys)
```

---

## Known limitations

Being honest about what doesn't work beats pretending it does:

- **Summary-style 10-Ks.** Kraft Heinz, Sealed Air, P&G, and Colgate all state total plant counts ("69 manufacturing and processing facilities") without listing the cities. They score correctly on ICP but only show 1–4 facility rows. Closing this gap would require scraping each company's interactive plant locator, which varies per site.
- **Private companies.** SpaceX, Stripe, and Cargill have no SEC filings. They rely on website scraping plus Wikipedia; coverage is necessarily thinner.
- **Geocoding precision.** Nominatim returns the centroid of the named city — accurate enough for territory visualization, not for street-level mapping.
- **Non-English sites.** Firecrawl handles JS rendering well in English; foreign-language subdomains (ArcelorMittal Spain, AB InBev LatAm) are less reliable. The pipeline tends to fall back to the English version or Wikipedia.
- **Vertically-integrated ambiguity.** ArcelorMittal runs steel mills AND iron-ore mines AND pellet plants; the reclassifier handles the clear cases but some facility types are genuinely ambiguous in the source text.
- **Ticker-less private SEC filers.** Rare, but if a private company somehow filed an S-1 without a registered ticker, the CIK lookup would fall back to name matching and could mismatch. None of the 20 companies trigger this path.

---

## What I'd build next

- **Playwright fallback** for sites Firecrawl can't render cleanly.
- **CRM export templates** with field mappings for Salesforce, HubSpot, Pipedrive.
- **Scheduled re-runs** so score drift + new-facility announcements flag as intent signals.
- **Custom filter presets** per AE (save "my territory" filter combinations).
- **Human-in-the-loop review queue** for ESTIMATED-confidence rows — one click to confirm/reject.

---

Built for the Tractian Summer 2026 GTM Data Engineering Internship Case.
