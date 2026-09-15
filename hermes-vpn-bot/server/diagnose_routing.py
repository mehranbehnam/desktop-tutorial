#!/usr/bin/env python3
"""Find out why Iranian sites do not open while the tunnel is connected.

Note on where routing decisions live: on the Iran server, the "direct"
outbound means the server itself opens the connection, so Iranian traffic
sent there still leaves from the Iranian address — those rules are correct
and are not the problem. Traffic can only skip the tunnel because of a rule
in the *client* app, or be dropped by a blackhole rule on the server.

    cd /opt/irannewvpn-bot && sudo venv/bin/python server/diagnose_routing.py
"""
import json
import os
import sys

BOT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))
sys.path.insert(0, BOT_DIR)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BOT_DIR, ".env"))
except ImportError:
    pass

from xui_client import XUIClient, XUIError  # noqa: E402

TARGETS = ["bmi.ir", "bankmellat.ir", "sb24.ir", "bpi.ir", "bsi.ir",
           "shaparak.ir", "adliran.ir", "digikala.com"]
IR_TOKENS = ("category-ir", "geoip:ir", "geosite:ir", "\\.ir$", "iran")
DROP_TAGS = ("block", "blocked", "blackhole", "reject")

x = XUIClient()

print("=" * 68)
print("1. SERVER ROUTING — anything that DROPS Iranian traffic")
print("=" * 68)

try:
    cfg = x._request("GET", "/panel/api/server/getConfigJson")
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
except (XUIError, ValueError) as e:
    sys.exit(f"could not read the running config: {e}")

outbounds = cfg.get("outbounds") or []
print("  outbounds:", ", ".join(f"{o.get('tag')}({o.get('protocol')})" for o in outbounds) or "none")

# An outbound that forwards somewhere else would move the exit address off
# this server, which would defeat the whole purpose.
forwarding = [o for o in outbounds
              if o.get("protocol") not in ("freedom", "blackhole", "dns")]
if forwarding:
    print("  NOTE: these outbounds forward elsewhere, so traffic matching them")
    print("        would NOT leave from this server's Iranian address:")
    for o in forwarding:
        print(f"          {o.get('tag')} ({o.get('protocol')})")

rules = ((cfg.get("routing") or {}).get("rules")) or []
print(f"  {len(rules)} routing rules\n")

dropped = []
for i, rule in enumerate(rules):
    tag = str(rule.get("outboundTag", ""))
    tokens = []
    for key in ("domain", "ip", "protocol", "port"):
        v = rule.get(key)
        if v:
            tokens += v if isinstance(v, list) else [str(v)]
    blob = " ".join(str(t).lower() for t in tokens)
    harmful = tag.lower() in DROP_TAGS and any(t in blob for t in IR_TOKENS)
    if harmful:
        dropped.append(i)
    shown = ", ".join(str(t) for t in tokens[:4]) + (" …" if len(tokens) > 4 else "")
    note = "   <== DROPS IRANIAN TRAFFIC" if harmful else ""
    print(f"  [{i}] -> {tag or '(default)'}: {shown}{note}")

print()
print("=" * 68)
print("2. WHICH OUTBOUND THE CORE PICKS PER DESTINATION")
print("=" * 68)
for target in TARGETS:
    picked = None
    for payload in ({"domain": target, "network": "tcp"},
                    {"target": target, "network": "tcp"},
                    {"host": target, "network": "tcp"}):
        try:
            res = x._request("POST", "/panel/api/xray/routeTest", data=payload)
            picked = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)[:60]
            break
        except XUIError:
            continue
    print(f"  {target:18} -> {picked if picked is not None else '(routeTest not available)'}")

print()
print("=" * 68)
print("3. WHAT TO CHECK NEXT")
print("=" * 68)

if dropped:
    print(f"  Rules {dropped} drop Iranian traffic on the server. Remove them in")
    print("  the panel under Xray Configs → Routing, then restart Xray.")
elif forwarding:
    print("  The server has forwarding outbounds; make sure the bank domains are")
    print("  not routed into one of them, or they will not exit from Iran.")
else:
    print("  The server side is clean: everything it receives leaves from its own")
    print("  Iranian address. So the traffic is either never reaching the server,")
    print("  or the bank is refusing this address. Check, in this order:\n")
    print("  a) In the VPN app, turn OFF any 'bypass Iran' / 'دور زدن سایت‌های")
    print("     ایرانی' routing option and set routing to Global. This is the")
    print("     usual cause — such a rule keeps bank traffic on your own")
    print("     connection, so the bank sees a Turkish address.")
    print("  b) With the VPN connected, open  https://api.ipify.org  in a browser.")
    print(f"     It must show {os.getenv('XUI_PUBLIC_HOST', 'the Iran server IP')}.")
    print("     If it shows a Turkish address, it is (a).")
    print("  c) If it does show the Iranian address and the bank still refuses,")
    print("     the bank is blocking this hosting range. No setting here can")
    print("     change that — it needs an Iranian IP the bank accepts.")
