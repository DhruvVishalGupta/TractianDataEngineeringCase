"""
Pipeline configuration — company list, ICP weights, taxonomies, endpoints.
"""
from pathlib import Path

# ── Project paths ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent.parent
DATA_RAW_DIR = ROOT_DIR / "data" / "raw"
DATA_PROCESSED_DIR = ROOT_DIR / "data" / "processed"
OUTPUTS_DIR = ROOT_DIR / "outputs"
LOGS_DIR = ROOT_DIR / "logs"

for d in [DATA_RAW_DIR, DATA_PROCESSED_DIR, OUTPUTS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Ollama ─────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TEMPERATURE = 0
OLLAMA_TIMEOUT = 120  # seconds

# ── Company list ──────────────────────────────────────────────────────────────
COMPANIES = [
    {"name": "Cargill",                "website": "cargill.com",                 "is_public": False},
    {"name": "Dow Chemical",           "website": "dow.com",                     "is_public": True},
    {"name": "Tyson Foods",            "website": "tysonfoods.com",              "is_public": True},
    {"name": "Kraft Heinz",            "website": "kraftheinzcompany.com",       "is_public": True},
    {"name": "Mosaic Company",         "website": "mosaicco.com",                "is_public": True},
    {"name": "ArcelorMittal",          "website": "arcelormittal.com",           "is_public": True},
    {"name": "Anheuser-Busch InBev",   "website": "ab-inbev.com",               "is_public": True},
    {"name": "International Paper",    "website": "internationalpaper.com",      "is_public": True},
    {"name": "Sealed Air",             "website": "sealedair.com",               "is_public": True},
    {"name": "Caterpillar",            "website": "caterpillar.com",             "is_public": True},
    {"name": "Procter & Gamble",       "website": "pg.com",                      "is_public": True},
    {"name": "Colgate-Palmolive",      "website": "colgatepalmolive.com",        "is_public": True},
    {"name": "Mondelez International", "website": "mondelezinternational.com",   "is_public": True},
    {"name": "SpaceX",                 "website": "spacex.com",                  "is_public": False},
    {"name": "McDonald's",             "website": "mcdonalds.com",               "is_public": True},
    {"name": "Walmart",                "website": "walmart.com",                 "is_public": True},
    {"name": "Salesforce",             "website": "salesforce.com",              "is_public": True},
    {"name": "Stripe",                 "website": "stripe.com",                  "is_public": False},
    {"name": "Spotify",                "website": "spotify.com",                 "is_public": True},
    {"name": "Airbnb",                 "website": "airbnb.com",                  "is_public": True},
]

# ── ICP scoring weights ────────────────────────────────────────────────────────
ICP_MAX_SCORE = 10

ICP_INDUSTRY_FIT = {
    4: [
        "Food and Beverage", "Chemical", "Pulp and Paper", "Mining", "Minerals",
        "Steel", "Metals", "Cement", "Automotive", "Oil and Gas", "Refining",
        "Agriculture Processing", "Grain Processing"
    ],
    3: ["Pharmaceutical", "Plastics", "Rubber", "Water Treatment", "Wastewater"],
    2: ["General Manufacturing", "Logistics", "Warehousing", "Aerospace"],
    1: ["Retail", "Construction", "Defense"],
    0: ["SaaS", "Fintech", "Media", "Consulting", "Hospitality", "Food Service", "Technology"],
}

# ── Facility type taxonomy ─────────────────────────────────────────────────────
FACILITY_TYPES = [
    "Manufacturing Plant",
    "Packaging Plant",
    "Processing Plant",
    "Distribution Center",
    "Corporate HQ",
    "R&D Center",
    "Sales Office",
    "Refinery",
    "Mine and Extraction Site",
    "Power Plant",
    "Unknown",
]

# ── Confidence levels ──────────────────────────────────────────────────────────
CONFIDENCE_LEVELS = ["HIGH", "MED", "LOW", "ESTIMATED"]

# ── Source types ───────────────────────────────────────────────────────────────
SOURCE_TYPES = ["WEBSITE", "SEC_EDGAR", "SEARCH", "WIKIPEDIA", "MULTIPLE"]

# ── SEC EDGAR ─────────────────────────────────────────────────────────────────
EDGAR_FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index?q={query}&dateRange=custom&startdt=2023-01-01&enddt=2025-12-31&forms=10-K"
EDGAR_COMPANY_SEARCH = "https://www.sec.gov/cgi-bin/browse-edgar?company={name}&CIK=&type=10-K&dateb=&owner=include&count=5&search_text=&action=getcompany"
EDGAR_FILING_BASE = "https://www.sec.gov"

# ── Search queries template ───────────────────────────────────────────────────
SEARCH_QUERY_TEMPLATES = [
    "{company} manufacturing plant locations facilities",
    "{company} worldwide operations global facilities",
    "{company} {industry_term} plant locations",
    "{company} SEC 10-K properties facilities annual report",
    "{company} industrial operations processing plants",
]

# ── Scraping URL patterns ──────────────────────────────────────────────────────
LOCATION_URL_KEYWORDS = [
    "location", "locations", "facility", "facilities", "plant", "plants",
    "office", "offices", "global", "worldwide", "contact", "where-we-are",
    "our-sites", "manufacturing", "operations", "site", "sites", "map",
    "find-us", "about", "presence", "footprint"
]
