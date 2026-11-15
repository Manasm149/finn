"""Settings. Everything is an environment variable with a working default."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Load .env if present (KEY=VALUE lines). Real environment variables win.
if (ROOT / ".env").exists():
    for _line in (ROOT / ".env").read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
DATA_DIR = Path(os.environ.get("FINN_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR = ROOT / "web"

# Sample mode: every network call is answered from generated fixtures for
# fictional companies, so the whole pipeline runs offline. Never on by default.
SAMPLE = os.environ.get("FINN_SAMPLE", "") == "1"

# LLM: any OpenAI-compatible endpoint (Groq, Gemini, OpenRouter, Ollama...).
LLM_BASE_URL = os.environ.get("FINN_LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.environ.get("FINN_LLM_API_KEY", "")
MODEL_FAST = os.environ.get("FINN_MODEL_FAST", "")    # bulk extraction
MODEL_SMART = os.environ.get("FINN_MODEL_SMART", "") or MODEL_FAST  # reasoning
# Optional prices (USD per 1M tokens) so the cost meter can show money, not just tokens.
PRICE = {
    "fast": (float(os.environ.get("FINN_PRICE_FAST_IN", 0)), float(os.environ.get("FINN_PRICE_FAST_OUT", 0))),
    "smart": (float(os.environ.get("FINN_PRICE_SMART_IN", 0)), float(os.environ.get("FINN_PRICE_SMART_OUT", 0))),
}

# Cost guard-rails: past either, model reading switches off until the next UTC day.
LLM_DAILY_CALLS = int(os.environ.get("FINN_LLM_DAILY_CALLS", 400))
LLM_DAILY_USD = float(os.environ.get("FINN_LLM_DAILY_USD", 0))      # 0 = no money cap

TELEGRAM_TOKEN = os.environ.get("FINN_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("FINN_TELEGRAM_CHAT", "")

DEFAULT_RULES = {"vol": 2.0, "px": 4.0, "lookback": 20, "watch": [], "mute": []}


def llm_ready() -> bool:
    return bool(LLM_BASE_URL and MODEL_FAST) and not SAMPLE


def portfolio() -> list[dict]:
    """[{symbol, weight}] - the default book. The client may send its own."""
    if SAMPLE:
        from . import sample
        return sample.PORTFOLIO
    path = Path(os.environ.get("FINN_PORTFOLIO", ROOT / "portfolio.json"))
    return json.loads(path.read_text())["holdings"]
