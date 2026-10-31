"""All settings come from environment variables (or a .env file next to this folder).

THIS IS THE DEMO COPY: prices are always simulated, Angel One and Supabase are switched off.

DATA_MODE=auto   -> live prices if an Angel One API is available (from .env or the user admin picked), else demo (default)
DATA_MODE=demo   -> simulated market, no account needed (for testing the app)
DATA_MODE=angel  -> always live; shows an error until an Angel One API is available
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def _load_env_file():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()

# ---- DEMO COPY: always simulated prices, never a real database or broker account ----
DEMO_ONLY = True
DATA_MODE = "demo"

# Optional: Angel One SmartAPI for the shared live price feed. Leave empty to use the API of the user
# chosen in the admin dashboard. Each user's balance/portfolio always uses their own API. No orders are ever placed.
ANGEL_API_KEY = ""
ANGEL_CLIENT_CODE = ""
ANGEL_PIN = ""
ANGEL_TOTP_SECRET = ""

# Supabase (optional; if empty, trades are saved in data/trades.json)
SUPABASE_URL = ""  # demo keeps everything in demo/data on this computer
SUPABASE_KEY = ""

# Telegram alerts (optional)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Admin login (users and their data are managed in the Admin dashboard)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")

# How many "top volatile" F&O stocks to track
TOP_VOLATILE_COUNT = int(os.getenv("TOP_VOLATILE_COUNT", "200"))

PORT = int(os.getenv("PORT", "8000"))
