#!/usr/bin/env python3
"""Check that a client's link actually matches the inbound serving it.

Reality silently forwards any handshake it cannot authenticate to the site in
`dest`. So a client whose uuid, public key or shortId does not match the
inbound behaves exactly like a healthy connection that carries no data — and
nothing is logged, because Xray never accepted it as a client.

    cd /opt/irannewvpn-bot && sudo venv/bin/python server/verify_client.py
    ... <email>     check one client
    ... --restart   restart Xray afterwards, so a client the database has but
                    the running core does not gets loaded
"""
import json
import os
import sys
import urllib.parse

BOT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))
sys.path.insert(0, BOT_DIR)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BOT_DIR, ".env"))
except ImportError:
    pass

from xui_client import XUIClient, XUIError  # noqa: E402

x = XUIClient()
args = [a for a in sys.argv[1:] if not a.startswith("--")]

inbound = x.get_inbound()
stream = inbound.get("streamSettings")
stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
reality = stream.get("realitySettings") or {}
rsettings = reality.get("settings") or {}
settings = inbound.get("settings")
settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
inbound_clients = settings.get("clients") or []

print("=" * 68)
print("SERVER CLOCK")
print("=" * 68)
# Reality authentication is time-based, so a server clock that has drifted
# rejects every client and hands them all to the fallback site.
try:
    import email.utils
    import time as _time

    import requests as _requests

    r = _requests.get(x.base_url + "/", timeout=15,
                      headers={"User-Agent": "Mozilla/5.0"})
    served = r.headers.get("Date")
    if served:
        skew = email.utils.mktime_tz(email.utils.parsedate_tz(served)) - _time.time()
        print(f"  panel says   : {served}")
        print(f"  skew vs here : {skew:+.0f} seconds")
        if abs(skew) > 90:
            print("  FAIL  the clock has drifted far enough to break Reality auth.")
            print("        On the Iran server: timedatectl set-ntp true")
        else:
            print("  OK    within the tolerance Reality needs")
    else:
        print("  (no Date header to compare)")
except Exception as e:
    print(f"  could not check: {e}")

print()
print("=" * 68)
print("INBOUND", inbound.get("id"), "on port", inbound.get("port"))
print("=" * 68)
print(f"  publicKey  : {rsettings.get('publicKey')}")
print(f"  shortIds   : {reality.get('shortIds')}")
print(f"  serverNames: {reality.get('serverNames')}")
print(f"  clients in the inbound config: {len(inbound_clients)}")
for c in inbound_clients[-8:]:
    print(f"    {c.get('email','?'):28} id={c.get('id','?')}  flow={c.get('flow','') or '(none)'}")

email = args[0] if args else None
if not email:
    if not inbound_clients:
        sys.exit("\nNo clients in the inbound at all — creation is not reaching this inbound.")
    email = inbound_clients[-1].get("email")
    print(f"\n  (checking the most recent client: {email})")

print()
print("=" * 68)
print(f"LINK THE PANEL HANDS OUT FOR {email}")
print("=" * 68)
try:
    link = x.build_vless_link("", email)
except XUIError as e:
    sys.exit(f"  could not get a link: {e}")
print(f"  {link}\n")

parsed = urllib.parse.urlparse(link)
params = dict(urllib.parse.parse_qsl(parsed.query))
link_uuid = parsed.username or ""
print(f"  uuid in link : {link_uuid}")
print(f"  pbk  in link : {params.get('pbk')}")
print(f"  sid  in link : {params.get('sid')}")
print(f"  sni  in link : {params.get('sni')}")

print()
print("=" * 68)
print("DO THEY MATCH?")
print("=" * 68)
problems = []

ids = {str(c.get("id")) for c in inbound_clients}
if link_uuid in ids:
    print("  OK    the uuid is present in the inbound's client list")
else:
    print("  FAIL  the uuid is NOT in the inbound's client list")
    problems.append("uuid missing from the inbound")

if params.get("pbk") and rsettings.get("publicKey"):
    if params["pbk"] == rsettings["publicKey"]:
        print("  OK    public key matches")
    else:
        print("  FAIL  public key differs from the inbound's")
        problems.append("public key mismatch")

short_ids = [str(s) for s in (reality.get("shortIds") or [])]
if params.get("sid"):
    if params["sid"] in short_ids:
        print("  OK    shortId matches")
    else:
        print(f"  FAIL  shortId {params['sid']} is not in {short_ids}")
        problems.append("shortId mismatch")

names = reality.get("serverNames") or []
if params.get("sni"):
    if params["sni"] in names:
        print("  OK    sni matches the inbound's serverNames")
    else:
        print(f"  FAIL  sni {params['sni']} is not in {names}")
        problems.append("sni mismatch")

print()
if problems:
    print("  Mismatches: " + "; ".join(problems))
    print("  A client that does not match is treated as a stranger, handed to the")
    print("  fallback site, and never logged — which is what you are seeing.")
else:
    print("  Everything matches. The database and the link agree, so if traffic")
    print("  still does not flow, the running core has not loaded this client.")
    print("  Restart Xray to push the stored config into it:")
    print("    sudo venv/bin/python server/verify_client.py --restart")

if "--set-flow" in sys.argv:
    # Clients created before the flow fix carry none; VLESS over Reality on
    # raw TCP needs xtls-rprx-vision on both ends or the stream stalls.
    flow = x.client_flow()
    print(f"\n  setting flow={flow or '(none)'} on {email} …")
    traffic = x.get_client_traffic(email) or {}
    body = {
        "email": email,
        "totalGB": traffic.get("total", 0),
        "expiryTime": traffic.get("expiryTime", 0),
        "enable": True,
    }
    if flow:
        body["flow"] = flow
    try:
        x._request("POST", f"/panel/api/clients/update/{email}", json=body)
        print("  updated — fetch the link again and reconnect.")
    except XUIError as e:
        print(f"  failed: {e}")

if "--restart" in sys.argv:
    print("\n  restarting xray …")
    try:
        x._request("POST", "/panel/api/server/restartXrayService")
        print("  done — reconnect the client and watch the byte counters.")
    except XUIError as e:
        print(f"  restart failed: {e}")
