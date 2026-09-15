#!/usr/bin/env python3
"""Print the panel's subscription settings so the sub URL can be built exactly.

Run:  cd /opt/irannewvpn-bot && sudo venv/bin/python server/probe_sub.py
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

x = XUIClient()

print("=== subscription-related panel settings ===")
try:
    settings = x._request("POST", "/panel/api/setting/all") or {}
    subs = {k: v for k, v in settings.items()
            if "sub" in k.lower() or k.lower() in ("weblistenip", "webdomain", "webport")}
    for k, v in sorted(subs.items()):
        print(f"  {k} = {v!r}")
    if not subs:
        print("  (no keys matched — full key list below)")
        print("  " + ", ".join(sorted(settings)[:80]))
except XUIError as e:
    print(f"  could not read settings: {e}")

print("\n=== what a client record looks like (for subId) ===")
email = sys.argv[1] if len(sys.argv) > 1 else None
if not email:
    try:
        clients = x._request("GET", "/panel/api/clients/list") or []
        if clients:
            email = (clients[0].get("client") or clients[0]).get("email")
            print(f"  using first client: {email}")
    except XUIError as e:
        print(f"  could not list clients: {e}")

if email:
    try:
        print("  traffic:", json.dumps(x.get_client_traffic(email), ensure_ascii=False)[:400])
    except XUIError as e:
        print(f"  traffic failed: {e}")
    for path in (f"/panel/api/clients/get/{email}",):
        try:
            print(f"  {path}:", json.dumps(x._request("GET", path), ensure_ascii=False)[:600])
        except XUIError as e:
            print(f"  {path} failed: {e}")
else:
    print("  no client to inspect — create one first, or pass an email as an argument")

print("\nDone — send this output back.")
