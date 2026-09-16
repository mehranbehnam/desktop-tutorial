#!/usr/bin/env bash
# End-to-end setup + verification for the Iran VPN bot.
#
# Runs on the bot server (Nautilus). Refreshes the code, repairs the config,
# checks the whole chain through to the VPN panel on the Iran server, creates a
# real client, and prints a working vless:// link — or says exactly what broke.
#
# Credentials are never stored in this repo. Pass them on the command line the
# first time; afterwards the values already in .env are reused:
#
#   XUI_BASE_URL=http://IP:PORT/webbasepath \
#   XUI_USERNAME=... XUI_PASSWORD=... XUI_PUBLIC_HOST=IP \
#   bash setup_iran_vpn.sh

RAW=https://raw.githubusercontent.com/mehranbehnam/desktop-tutorial/refs/heads/claude/iran-vpn-turkey-d2hbvg/hermes-vpn-bot
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
FAILED=0
FAILLOG=""

say()  { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; FAILLOG="$FAILLOG
• $1"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; }

# ---------------------------------------------------------------- 1. locate
say "1. INSTALL DIRECTORY"
APP=$(ls -d /opt/irannewvpn-bot /opt/hermes-vpn-bot 2>/dev/null | head -1)
if [ -z "$APP" ]; then
  bad "no install found in /opt — run the deploy script first"
  exit 1
fi
SVC=$(basename "$APP")
ok "app dir: $APP"
ok "service: $SVC"

# ---------------------------------------------------------------- 2. code
say "2. REFRESH CODE FROM GITHUB"
mkdir -p "$APP/bot/handlers" "$APP/bot/utils" "$APP/server"
FILES="bot/config.py bot/db.py bot/keyboards.py bot/main.py bot/devbot_main.py bot/xui_client.py bot/requirements.txt
bot/handlers/__init__.py bot/handlers/admin.py bot/handlers/buy.py bot/handlers/renew.py
bot/handlers/start.py bot/handlers/status.py bot/handlers/trial.py
bot/handlers/ops.py bot/handlers/devmenu.py
bot/utils/__init__.py bot/utils/pricing.py bot/utils/delivery.py bot/utils/x25519.py bot/utils/tunnel_test.py server/test_client.py"
for f in $FILES; do
  # __init__.py files are legitimately empty, so trust curl's exit status
  # rather than the downloaded size.
  if curl -fsSL --max-time 30 "$RAW/$f" -o "$APP/$f.new"; then
    mv "$APP/$f.new" "$APP/$f"
  else
    rm -f "$APP/$f.new"
    bad "could not download $f"
  fi
done
[ "$FAILED" = 0 ] && ok "all $(echo $FILES | wc -w) files downloaded"

# ---------------------------------------------------------------- 3. config
say "3. REPAIR CONFIG (.env)"
ENV="$APP/bot/.env"
if [ ! -f "$ENV" ]; then
  bad "$ENV does not exist — cannot continue without bot token"
  exit 1
fi
cp "$ENV" "$ENV.bak.$(date +%s)"

set_env() {  # set_env KEY VALUE
  local key="$1" val="$2"
  [ -z "$val" ] && return
  if grep -qE "^${key}=" "$ENV"; then
    local cur
    cur=$(grep -E "^${key}=" "$ENV" | head -1 | cut -d= -f2-)
    [ "$cur" = "$val" ] && return
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV"
    echo "  changed ${key}"
  else
    echo "${key}=${val}" >> "$ENV"
    echo "  added   ${key}"
  fi
}

# The database must live inside the current install dir. A renamed folder
# leaves the old path behind, and then every handler dies on sqlite open.
set_env DB_PATH "$APP/bot/bot.db"
set_env XUI_BASE_URL "$XUI_BASE_URL"
set_env XUI_USERNAME "$XUI_USERNAME"
set_env XUI_PASSWORD "$XUI_PASSWORD"
set_env XUI_API_TOKEN "$XUI_API_TOKEN"
set_env XUI_PUBLIC_HOST "$XUI_PUBLIC_HOST"
set_env XUI_INBOUND_ID "$XUI_INBOUND_ID"
set_env TRIAL_MB "${TRIAL_MB:-200}"
set_env TRIAL_HOURS "${TRIAL_HOURS:-1}"
set_env DEV_BOT_TOKEN "$DEV_BOT_TOKEN"

get_env() { grep -E "^$1=" "$ENV" 2>/dev/null | head -1 | cut -d= -f2-; }
BASE=$(get_env XUI_BASE_URL); PUSER=$(get_env XUI_USERNAME); PPASS=$(get_env XUI_PASSWORD)
PHOST=$(get_env XUI_PUBLIC_HOST); INB=$(get_env XUI_INBOUND_ID); TOKEN=$(get_env BOT_TOKEN)
DEVTOKEN=$(get_env DEV_BOT_TOKEN)

echo "  panel      : $BASE"
echo "  public host: $PHOST"
echo "  inbound id : $INB"
echo "  db path    : $(get_env DB_PATH)"
[ -n "$BASE" ]  && ok "XUI_BASE_URL set"   || bad "XUI_BASE_URL empty"
[ -n "$PUSER" ] && ok "panel user set"     || warn "XUI_USERNAME empty (cookie login will fail)"
[ -n "$PHOST" ] && ok "XUI_PUBLIC_HOST set" || warn "XUI_PUBLIC_HOST empty — links would point at the panel host"
[ -n "$TOKEN" ] && ok "BOT_TOKEN set"      || bad "BOT_TOKEN empty"
[ -n "$DEVTOKEN" ] && ok "DEV_BOT_TOKEN set (maintenance bot will run)" || warn "DEV_BOT_TOKEN empty — maintenance bot skipped"

# ---------------------------------------------------------------- 4. venv
say "4. PYTHON ENVIRONMENT"
if [ ! -x "$APP/venv/bin/python" ]; then
  warn "venv missing — creating"
  python3 -m venv "$APP/venv" 2>&1 | tail -2
fi
PY="$APP/venv/bin/python"
if [ -x "$PY" ]; then
  "$PY" -m pip install -q --upgrade pip 2>/dev/null
  "$PY" -m pip install -q -r "$APP/bot/requirements.txt" 2>&1 | tail -3
  ok "$("$PY" --version 2>&1) with deps installed"
else
  bad "could not create venv"
  exit 1
fi

cd "$APP" || exit 1
IMPORTS=$("$PY" -c "
import sys; sys.path.insert(0,'bot')
try:
    import config, db, xui_client
    from handlers import trial, buy, status, start, renew, admin, ops, devmenu
    print('OK')
except Exception:
    import traceback; traceback.print_exc()
" 2>&1)
if [ "$IMPORTS" = "OK" ]; then ok "all bot modules import"; else bad "import error:"; echo "$IMPORTS" | tail -12; fi

# ---------------------------------------------------------------- 5. network
say "5. IRAN PANEL REACHABLE FROM THIS SERVER"
HOSTPORT=$(echo "$BASE" | sed -E 's#https?://##; s#/.*##')
PHOST_ONLY=${HOSTPORT%%:*}; PPORT=${HOSTPORT##*:}; [ "$PPORT" = "$PHOST_ONLY" ] && PPORT=80
if timeout 8 bash -c "echo > /dev/tcp/$PHOST_ONLY/$PPORT" 2>/dev/null; then
  ok "TCP $PHOST_ONLY:$PPORT reachable"
else
  bad "TCP $PHOST_ONLY:$PPORT NOT reachable — panel down, or the Iran server's firewall blocks this server's IP"
  echo "     this server's public IP: $(curl -s --max-time 8 https://api.ipify.org 2>/dev/null)"
fi

CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -A "$UA" "$BASE/")
[ "$CODE" = "200" ] && ok "GET $BASE/ -> 200" || bad "GET $BASE/ -> $CODE (wrong web base path?)"

PTOKEN=$(get_env XUI_API_TOKEN)
rm -f /tmp/ivpn_cookies.txt
LOGIN=$(curl -s --max-time 15 -A "$UA" -c /tmp/ivpn_cookies.txt -X POST "$BASE/login" \
        -d "username=$PUSER&password=$PPASS" | head -c 150)
case "$LOGIN" in
  *'"success":true'*|*'"success": true'*) ok "panel login succeeded" ;;
  *) if [ -n "$PTOKEN" ]; then
       warn "cookie login refused (this build is token-only) — using the API token"
     else
       bad "panel login failed and no API token to fall back on -> $LOGIN"
     fi ;;
esac

LIST=$(curl -s -o /tmp/ivpn_list.json -w '%{http_code}' --max-time 15 -A "$UA" \
       -H "Authorization: Bearer $PTOKEN" \
       -b /tmp/ivpn_cookies.txt "$BASE/panel/api/inbounds/list")
if [ "$LIST" = "200" ]; then
  ok "inbound list readable"
  "$PY" - <<'PYEOF'
import json
try:
    data = json.load(open('/tmp/ivpn_list.json'))
except Exception as e:
    raise SystemExit(f"     could not parse inbound list: {e}")
for i in data.get('obj') or []:
    stream = i.get('streamSettings') or '{}'
    sec = json.loads(stream).get('security', '?') if stream.startswith('{') else '?'
    print(f"     inbound id={i.get('id')} port={i.get('port')} proto={i.get('protocol')} "
          f"security={sec} enabled={i.get('enable')} clients={len(json.loads(i.get('settings') or '{}').get('clients', []))}")
PYEOF
else
  bad "inbound list -> HTTP $LIST"
fi

# ---------------------------------------------------------------- 6. provision
say "6. CREATE A REAL CLIENT AND BUILD THE LINK"
PROVISION=$("$PY" server/test_client.py --keep 2>&1)
echo "$PROVISION" | sed 's/^/  /'
LINK=$(echo "$PROVISION" | grep -o 'vless://[^ ]*' | head -1)
[ -n "$LINK" ] && ok "client created and link built" || bad "provisioning did not produce a link"

# ---------------------------------------------------------------- 7. service
say "7. BOT SERVICE"
systemctl daemon-reload 2>&1
systemctl restart "$SVC" 2>&1
sleep 4
STATE=$(systemctl is-active "$SVC" 2>&1)
[ "$STATE" = "active" ] && ok "service active" || bad "service $STATE"
journalctl -u "$SVC" -n 12 --no-pager 2>&1 | sed 's/^/     /' | tail -12

if [ -n "$TOKEN" ]; then
  ME=$(curl -s --max-time 15 "https://api.telegram.org/bot$TOKEN/getMe" | tr -d ' ')
  case "$ME" in
    *'"ok":true'*) ok "telegram token valid: @$(echo "$ME" | grep -o '"username":"[^"]*' | cut -d'"' -f4)" ;;
    *) bad "telegram getMe failed -> $(echo "$ME" | head -c 120)" ;;
  esac
fi

# ---------------------------------------------------------------- 7b. dev bot
if [ -n "$DEVTOKEN" ]; then
  say "7b. MAINTENANCE BOT SERVICE (developer bot)"
  DEVSVC="${SVC}-dev"
  cat > "/etc/systemd/system/${DEVSVC}.service" << SERVICEEOF
[Unit]
Description=iranvpn maintenance/developer Telegram bot
After=network.target ${SVC}.service

[Service]
WorkingDirectory=${APP}/bot
ExecStart=${APP}/venv/bin/python ${APP}/bot/devbot_main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICEEOF
  systemctl daemon-reload 2>&1
  systemctl enable --now "$DEVSVC" 2>&1
  sleep 3
  DEVSTATE=$(systemctl is-active "$DEVSVC" 2>&1)
  [ "$DEVSTATE" = "active" ] && ok "service $DEVSVC active" || bad "service $DEVSVC $DEVSTATE"
  journalctl -u "$DEVSVC" -n 8 --no-pager 2>&1 | sed 's/^/     /' | tail -8

  DEVME=$(curl -s --max-time 15 "https://api.telegram.org/bot$DEVTOKEN/getMe" | tr -d ' ')
  case "$DEVME" in
    *'"ok":true'*) ok "dev bot token valid: @$(echo "$DEVME" | grep -o '"username":"[^"]*' | cut -d'"' -f4) — send it /start" ;;
    *) bad "dev bot getMe failed -> $(echo "$DEVME" | head -c 120)" ;;
  esac
fi

# ---------------------------------------------------------------- verdict
say "RESULT"
if [ "$FAILED" = 0 ] && [ -n "$LINK" ]; then
  printf '  \033[32mEVERYTHING WORKS\033[0m\n\n'
  echo "  Your Iran VPN link (import into v2rayNG / NekoBox / Streisand):"
  echo
  echo "$LINK"
  echo
  echo "  The 🧪 تست button in the bot now returns a link like this one."
  REPORT="✅ راه‌اندازی کامل شد و همه‌چیز کار می‌کنه.

سرویس ربات فعاله و ساخت کلاینت روی پنل ایران تست شد.

لینک VPN ایران (در v2rayNG / NekoBox / Streisand وارد کن):

$LINK

دکمه‌ی 🧪 تست هم از الان لینکی مثل همین می‌ده."
else
  printf '  \033[31mSOMETHING IS STILL BROKEN\033[0m — see the FAIL lines above.\n'
  REPORT="❌ راه‌اندازی کامل نشد.

مراحلی که شکست خوردن:
$(printf '%s\n' "$FAILLOG")

سرویس: $(systemctl is-active "$SVC" 2>&1)
این متن رو برای کلاد بفرست تا ادامه بده."
fi

# Send the verdict straight to Telegram so the result never has to be copied
# out of a terminal by hand.
ADMINS=$(get_env ADMIN_IDS)
if [ -n "$TOKEN" ] && [ -n "$ADMINS" ]; then
  echo
  for id in $(echo "$ADMINS" | tr ',' ' '); do
    SENT=$(curl -s --max-time 20 -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
      --data-urlencode "chat_id=$id" --data-urlencode "text=$REPORT" | tr -d ' ' | head -c 60)
    case "$SENT" in
      *'"ok":true'*) ok "result sent to your Telegram (chat $id)" ;;
      *) warn "could not send result to Telegram chat $id: $SENT" ;;
    esac
  done
fi
