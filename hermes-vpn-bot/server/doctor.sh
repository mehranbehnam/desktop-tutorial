#!/usr/bin/env bash
# One-shot health check for the bot server. Prints why the bot is down and
# whether the panel on the VPN server is reachable from here.
# Run:  curl -fsSL <raw-url>/server/doctor.sh | sudo bash

echo "=============== 1. APP DIRECTORY ==============="
APP=$(ls -d /opt/irannewvpn-bot /opt/hermes-vpn-bot 2>/dev/null | head -1)
if [ -z "$APP" ]; then
  echo "FAIL: neither /opt/irannewvpn-bot nor /opt/hermes-vpn-bot exists"
  ls -la /opt/ 2>/dev/null
  exit 1
fi
SVC=$(basename "$APP")
echo "app dir : $APP"
echo "service : $SVC"

echo
echo "=============== 2. SERVICE STATUS ==============="
systemctl is-enabled "$SVC" 2>&1 | sed 's/^/enabled: /'
systemctl is-active "$SVC" 2>&1 | sed 's/^/active : /'
echo "--- last 25 log lines ---"
journalctl -u "$SVC" -n 25 --no-pager 2>&1 | tail -25

echo
echo "=============== 3. FILES PRESENT ==============="
for f in bot/main.py bot/config.py bot/xui_client.py bot/handlers/trial.py bot/.env; do
  if [ -s "$APP/$f" ]; then
    echo "ok    $f ($(wc -c < "$APP/$f") bytes)"
  else
    echo "MISSING/EMPTY  $f"
  fi
done

echo
echo "=============== 4. CONFIG (secrets masked) ==============="
if [ -f "$APP/bot/.env" ]; then
  while IFS='=' read -r k v; do
    case "$k" in
      ''|\#*) continue ;;
      BOT_TOKEN|XUI_PASSWORD|XUI_API_TOKEN)
        if [ -n "$v" ]; then echo "$k=<set, ${#v} chars>"; else echo "$k=<EMPTY>"; fi ;;
      *) echo "$k=$v" ;;
    esac
  done < "$APP/bot/.env"
else
  echo "no .env file!"
fi

echo
echo "=============== 5. PANEL REACHABLE FROM HERE ==============="
BASE=$(grep -E '^XUI_BASE_URL=' "$APP/bot/.env" 2>/dev/null | cut -d= -f2-)
USER_=$(grep -E '^XUI_USERNAME=' "$APP/bot/.env" 2>/dev/null | cut -d= -f2-)
PASS_=$(grep -E '^XUI_PASSWORD=' "$APP/bot/.env" 2>/dev/null | cut -d= -f2-)
echo "panel base: $BASE"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 -A "$UA" "$BASE/" 2>&1)
echo "GET  /                 -> $code"

rm -f /tmp/doctor_cookies.txt
login=$(curl -s --max-time 12 -A "$UA" -c /tmp/doctor_cookies.txt \
  -X POST "$BASE/login" -d "username=$USER_&password=$PASS_" 2>&1 | head -c 200)
echo "POST /login            -> $login"

list=$(curl -s -o /tmp/doctor_list.json -w '%{http_code}' --max-time 12 -A "$UA" \
  -b /tmp/doctor_cookies.txt "$BASE/panel/api/inbounds/list" 2>&1)
echo "GET  /api/inbounds/list-> $list"
if [ "$list" = "200" ]; then
  python3 -c "
import json
d=json.load(open('/tmp/doctor_list.json'))
for i in d.get('obj') or []:
    print(f\"   inbound id={i.get('id')} port={i.get('port')} protocol={i.get('protocol')} enable={i.get('enable')}\")
" 2>/dev/null || head -c 300 /tmp/doctor_list.json
fi

echo
echo "=============== 6. PYTHON IMPORTS ==============="
cd "$APP" || exit 1
if [ -x venv/bin/python ]; then
  venv/bin/python -c "
import sys; sys.path.insert(0,'bot')
try:
    import config, db, xui_client
    from handlers import trial, buy, status, start, renew, admin
    print('all bot modules import OK')
except Exception as e:
    import traceback; traceback.print_exc()
" 2>&1 | tail -20
else
  echo "FAIL: $APP/venv/bin/python missing"
fi

echo
echo "=============== 7. LIVE CLIENT TEST ==============="
if [ -f "$APP/server/test_client.py" ] && [ -x venv/bin/python ]; then
  venv/bin/python server/test_client.py 2>&1 | tail -20
else
  echo "server/test_client.py not present — skipping"
fi

echo
echo "=============== 8. RESTART ATTEMPT ==============="
systemctl restart "$SVC" 2>&1
sleep 3
echo "active after restart: $(systemctl is-active "$SVC" 2>&1)"
journalctl -u "$SVC" -n 8 --no-pager 2>&1 | tail -8

echo
echo "=============== DONE ==============="
