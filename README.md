# Tractian GTM — Sales Intelligence Pipeline

Given just a company name, this pipeline returns a 1–10 ICP fit score plus a CRM-ready list of every facility that company operates, with source attribution and confidence per row. Website and ticker are auto-discovered.

**21 companies · 246 facilities · 31 countries · 100% geocoded**

🔗 **Live dashboard (hosted snapshot):** https://tractiandataengineeringcase.vercel.app
🔗 **Repo:** https://github.com/DhruvVishalGupta/TractianDataEngineeringCase

---

## How it works

```
       { name }
          │
          ▼
  ┌──────────────────────────────────────────────┐
  │  1. DISCOVERY                                 │
  │    Brave Search — auto-discover website       │
  │    Brave Search (site-scoped OSINT dorks)     │
  │    SEC EDGAR 10-K / 20-F Item 2 Properties    │
  │    Wikipedia API (firmographics)              │
  └──────────────────────┬───────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────┐
  │  2. EXTRACTION                                │
  │    Firecrawl — JS-rendered Markdown           │
  │    Claude Haiku 4.5 — tool-use JSON (cached)  │
  └──────────────────────┬───────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────┐
  │  3. VALIDATION                                │
  │    Quote traceability  ·  Ownership guard     │
  │    Regional-HQ downgrade  ·  Reclassifier     │
  │    OSINT corroboration (second Brave pass)    │
  │    Dedup + cross-source confidence boost      │
  └──────────────────────┬───────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────┐
  │  4. ENRICH + SCORE                            │
  │    Nominatim geocoding (lat/lon per row)      │
  │    ICP scorer — 4 dimensions → 0-10           │
  └──────────────────────┬───────────────────────┘
                         ▼
        outputs/tractian_leads.{csv, xlsx, json}
              FastAPI  +  React/Vite dashboard
```

Everything is cached per-company under `data/raw/{slug}/`, so the first run takes ~7 minutes and every subsequent run is ~30 seconds.

---

## Running it

### Prerequisites
- Python 3.11+
- Node 18+ (for the dashboard)
- Keys in `.env` (see `.env.example`):
  ```
  CLAUDE_API_KEY=...
  BRAVE_API_KEY=...
  FIRECRAWL_API_KEY=...
  ```

### Pipeline
```bash
pip install -r requirements.txt
python -m src.pipeline.orchestrator
```

### API + dashboard
```bash
# terminal 1
uvicorn src.api.main:app --port 8000

# terminal 2
cd src/dashboard
npm install
npm run dev
```
Dashboard: http://localhost:5173

### Live demo
Two options:
- **Hosted snapshot** (read-only): open the live dashboard URL above. All 21 companies / 246 facilities are browsable with filters, map, and per-facility drill-down. The "Add company" button is disabled — running the full pipeline needs API keys and is local-only.
- **Local live demo** (full pipeline): with both servers running, click **"+ Add company (live demo)"** and type any company name. The pipeline auto-discovers the website, crawls OSINT sources, scores it, and appends it to the dashboard in real time.

---

## Output

| File | Purpose |
|---|---|
| `outputs/tractian_leads.csv` | Flat file, one row per facility. CRM-ready column order matching the case sample (Company / Website / Score / Location / Classification first). |
| `outputs/tractian_leads.xlsx` | 3 styled sheets: All Leads · Company Summary · High-Value Targets. |
| `outputs/tractian_leads.json` | Nested for the dashboard (company-level scores + flat rows). |

---

## Directory

```
src/
├── pipeline/      # the 20 modules that make up the pipeline
├── api/           # FastAPI backend (live + snapshot data, DELETE endpoint)
└── dashboard/     # Vite + React SPA
    └── public/data/  # bundled snapshot used by the hosted build

data/raw/          # per-company OSINT cache (auto-created, gitignored)
outputs/           # final CSV / XLSX / JSON

vercel.json        # static-snapshot deploy config
.vercelignore      # excludes Python pipeline from frontend build
```
