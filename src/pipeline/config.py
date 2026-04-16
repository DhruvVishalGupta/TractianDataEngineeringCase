"""
Pipeline configuration — paths, API keys, and the Claude model ID.
Everything here is actually imported somewhere (verified against src/).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# ── Project paths ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent.parent
DATA_RAW_DIR = ROOT_DIR / "data" / "raw"
OUTPUTS_DIR = ROOT_DIR / "outputs"
LOGS_DIR = ROOT_DIR / "logs"

for d in (DATA_RAW_DIR, OUTPUTS_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Secrets ────────────────────────────────────────────────────────────────────
load_dotenv()

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

# ── Claude ─────────────────────────────────────────────────────────────────────
# Latest Haiku — far better classification + JSON discipline than 3-haiku, similar cost.
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_TEMPERATURE = 0.0
