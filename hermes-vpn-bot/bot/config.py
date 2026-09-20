import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
# Separate bot for maintenance/admin use, menu-driven, admin-only. Empty
# means it is not deployed here; devbot_main.py refuses to start without it.
DEV_BOT_TOKEN = os.getenv("DEV_BOT_TOKEN", "")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@your_support")
BOT_NAME = os.getenv("BOT_NAME", "VPN Store")

# Real business bank card — set these in .env, never hardcode real numbers here.
CARD_NUMBER = os.getenv("CARD_NUMBER", "0000-0000-0000-0000")
CARD_OWNER = os.getenv("CARD_OWNER", "SET CARD_OWNER IN .env")
CURRENCY_LABEL = os.getenv("CURRENCY_LABEL", "لیر")

XUI_BASE_URL = os.getenv("XUI_BASE_URL", "http://127.0.0.1:2053")
# Preferred auth: an API token (Authorization: Bearer ...) — newer 3x-ui
# versions print one at install time and reject cookie-session /login for
# non-browser clients. username/password are kept as a fallback for older
# panel versions that only support the cookie-login flow.
XUI_API_TOKEN = os.getenv("XUI_API_TOKEN", "")
XUI_USERNAME = os.getenv("XUI_USERNAME", "admin")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "admin")
XUI_INBOUND_ID = int(os.getenv("XUI_INBOUND_ID", "1"))
# Public host/IP clients connect to — usually different from XUI_BASE_URL,
# which points at 127.0.0.1 so the panel API stays localhost-only.
XUI_PUBLIC_HOST = os.getenv("XUI_PUBLIC_HOST", "")
# Optional: base URL for a subscription link if you expose one via the panel/sub server.
XUI_SUB_BASE_URL = os.getenv("XUI_SUB_BASE_URL", "")

DB_PATH = os.getenv("DB_PATH", "bot.db")

# SSH into the Iran panel server itself (OS level, not the panel's web
# login) — only used by the developer bot, for things the panel's HTTP API
# has no endpoint for (fail2ban ban list/unban, restarting the panel
# service itself). Set via the developer bot's own "تنظیم SSH سرور ایران"
# flow, never hand-typed into this repo.
IRAN_SSH_HOST = os.getenv("IRAN_SSH_HOST", "")
IRAN_SSH_PORT = int(os.getenv("IRAN_SSH_PORT", "22"))
IRAN_SSH_USER = os.getenv("IRAN_SSH_USER", "")
IRAN_SSH_PASSWORD = os.getenv("IRAN_SSH_PASSWORD", "")

# Cloudflare API token (DNS:Edit scope) for the WS+TLS-behind-CDN setup —
# api.cloudflare.com is unreachable from wherever this code gets written,
# so the bot itself (with its own normal internet access) has to be the
# one making these calls. Set via "تنظیم Cloudflare API" in the developer
# bot, never hand-typed into this repo.
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")

# Optional. /update and setup_iran_vpn.sh read source files from GitHub's
# Contents API, which rate-limits unauthenticated requests to 60/hour — easy
# to hit during a debugging session with several updates in a row. Any
# GitHub personal access token (no special scopes needed for a public repo)
# raises that to 5000/hour.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

TRIAL_MB = int(os.getenv("TRIAL_MB", "200"))
TRIAL_HOURS = int(os.getenv("TRIAL_HOURS", "1"))

# Edit prices/plans freely. gb=0 means unlimited data (only time-limited).
PLANS = [
    {"key": "p30_30", "label": "30 گیگ / 30 روز", "gb": 30, "days": 30, "price": 500},
    {"key": "p50_30", "label": "50 گیگ / 30 روز", "gb": 50, "days": 30, "price": 700},
    {"key": "unl_30", "label": "نامحدود / 30 روز", "gb": 0, "days": 30, "price": 1000},
]

PLANS_BY_KEY = {p["key"]: p for p in PLANS}
