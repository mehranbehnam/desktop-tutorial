import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@your_support")
BOT_NAME = os.getenv("BOT_NAME", "VPN Store")

# Real business bank card — set these in .env, never hardcode real numbers here.
CARD_NUMBER = os.getenv("CARD_NUMBER", "0000-0000-0000-0000")
CARD_OWNER = os.getenv("CARD_OWNER", "SET CARD_OWNER IN .env")

XUI_BASE_URL = os.getenv("XUI_BASE_URL", "http://127.0.0.1:2053")
XUI_USERNAME = os.getenv("XUI_USERNAME", "admin")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "admin")
XUI_INBOUND_ID = int(os.getenv("XUI_INBOUND_ID", "1"))
# Optional: base URL for a subscription link if you expose one via the panel/sub server.
XUI_SUB_BASE_URL = os.getenv("XUI_SUB_BASE_URL", "")

DB_PATH = os.getenv("DB_PATH", "bot.db")

TRIAL_GB = int(os.getenv("TRIAL_GB", "1"))
TRIAL_HOURS = int(os.getenv("TRIAL_HOURS", "24"))

# Edit prices/plans freely. gb=0 means unlimited data (only time-limited).
PLANS = [
    {"key": "p10_30", "label": "10 گیگ / 30 روز", "gb": 10, "days": 30, "price": 40000},
    {"key": "p20_30", "label": "20 گیگ / 30 روز", "gb": 20, "days": 30, "price": 60000},
    {"key": "p30_30", "label": "30 گیگ / 30 روز", "gb": 30, "days": 30, "price": 85000},
    {"key": "p50_30", "label": "50 گیگ / 30 روز", "gb": 50, "days": 30, "price": 130000},
    {"key": "p100_30", "label": "100 گیگ / 30 روز", "gb": 100, "days": 30, "price": 180000},
]

PLANS_BY_KEY = {p["key"]: p for p in PLANS}
