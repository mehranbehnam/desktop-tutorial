#!/usr/bin/env python3
"""Find out what this panel build actually exposes, instead of guessing.

Reads the bot's .env for the panel URL and credentials, then reports:
  * which authentication the panel accepts
  * which candidate routes exist (405 = route exists, wrong method; 404 = absent)
  * every /api/ path string found in the panel's own JavaScript bundles

Run on the bot server:
    cd /opt/irannewvpn-bot && sudo venv/bin/python server/probe_panel.py
"""
import json
import os
import re
import sys

BOT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))
sys.path.insert(0, BOT_DIR)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BOT_DIR, ".env"))
except ImportError:
    pass

import requests  # noqa: E402

BASE = os.getenv("XUI_BASE_URL", "").rstrip("/")
USER = os.getenv("XUI_USERNAME", "")
PASS = os.getenv("XUI_PASSWORD", "")
TOKEN = os.getenv("XUI_API_TOKEN", "")
INB = os.getenv("XUI_INBOUND_ID", "1")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

if not BASE:
    sys.exit("XUI_BASE_URL is not set in .env")

print(f"panel: {BASE}\n")

# ------------------------------------------------------------------ auth
print("=" * 60)
print("1. WHICH AUTH DOES THIS PANEL ACCEPT?")
print("=" * 60)

sessions = {}

s = requests.Session()
s.headers["User-Agent"] = UA
if TOKEN:
    s.headers["Authorization"] = f"Bearer {TOKEN}"
    r = s.get(f"{BASE}/panel/api/inbounds/list", timeout=20)
    print(f"  bearer token  -> /panel/api/inbounds/list = {r.status_code}")
    if r.status_code == 200:
        sessions["token"] = s
else:
    print("  bearer token  -> not set in .env")

for label, kwargs in (("form", {"data": {"username": USER, "password": PASS}}),
                      ("json", {"json": {"username": USER, "password": PASS}})):
    c = requests.Session()
    c.headers["User-Agent"] = UA
    try:
        c.get(f"{BASE}/", timeout=15)
        r = c.post(f"{BASE}/login", timeout=15, **kwargs)
        body = r.text[:120].replace("\n", " ")
        print(f"  cookie ({label})  -> POST /login = {r.status_code}  {body}")
        if r.status_code == 200 and '"success":true' in r.text.replace(" ", ""):
            sessions[f"cookie-{label}"] = c
    except requests.RequestException as e:
        print(f"  cookie ({label})  -> {e}")

if not sessions:
    print("\n  no working auth found — everything below will 404/403")
else:
    print(f"\n  working auth: {', '.join(sessions)}")

# ------------------------------------------------------------------ routes
print()
print("=" * 60)
print("2. WHICH ROUTES EXIST?  (404 = absent, anything else = present)")
print("=" * 60)

candidates = [
    ("GET", "/panel/api/inbounds/list"),
    ("GET", f"/panel/api/inbounds/get/{INB}"),
    ("GET", f"/panel/api/inbounds/{INB}"),
    ("POST", "/panel/api/inbounds/addClient"),
    ("POST", "/panel/api/inbounds/add_client"),
    ("POST", f"/panel/api/inbounds/{INB}/addClient"),
    ("POST", f"/panel/api/inbounds/{INB}/clients"),
    ("POST", "/panel/api/inbounds/clients"),
    ("POST", "/panel/api/clients"),
    ("POST", f"/panel/api/clients/{INB}"),
    ("POST", "/panel/inbound/addClient"),
    ("POST", f"/panel/inbound/{INB}/addClient"),
    ("POST", "/api/inbounds/addClient"),
    ("POST", f"/api/inbounds/{INB}/clients"),
    ("POST", "/api/clients"),
    ("GET", "/panel/api/serverStatus"),
    ("GET", "/panel/api/server/status"),
    ("GET", "/panel/api"),
    ("GET", "/api"),
]

for name, sess in sessions.items() or [("no-auth", requests.Session())]:
    print(f"\n  --- using {name} ---")
    for method, path in candidates:
        try:
            r = sess.request(method, f"{BASE}{path}", timeout=15,
                             data={"id": INB, "settings": json.dumps({"clients": []})}
                             if method == "POST" else None)
            marker = "  <== EXISTS" if r.status_code != 404 else ""
            print(f"    {method:4} {path:45} {r.status_code}{marker}")
        except requests.RequestException as e:
            print(f"    {method:4} {path:45} ERR {e}")

# ------------------------------------------------------------------ bundles
print()
print("=" * 60)
print("3. API PATHS FOUND INSIDE THE PANEL'S OWN JAVASCRIPT")
print("=" * 60)

fetch = next(iter(sessions.values()), s)
seen, queue, found = set(), [], set()

try:
    index = fetch.get(f"{BASE}/", timeout=20).text
    queue += re.findall(r'(?:src|href)="([^"]+\.js)"', index)
except requests.RequestException as e:
    print(f"  could not fetch index: {e}")

while queue:
    ref = queue.pop(0)
    if ref in seen:
        continue
    seen.add(ref)
    url = ref if ref.startswith("http") else (
        f"{BASE.split('://')[0]}://{BASE.split('://')[1].split('/')[0]}{ref}"
        if ref.startswith("/") else f"{BASE}/{ref.lstrip('./')}")
    try:
        body = fetch.get(url, timeout=20).text
    except requests.RequestException:
        continue
    if len(body) < 50:
        continue
    print(f"  scanned {ref} ({len(body)} bytes)")
    found |= set(re.findall(r'["\'`](/(?:panel/)?api/[A-Za-z0-9_/\-{}$.:]*)["\'`]', body))
    # Vite chunks import each other by filename; follow those too.
    for chunk in re.findall(r'["\'`](\.?/?assets/[A-Za-z0-9_\-.]+\.js)["\'`]', body):
        if chunk not in seen and len(seen) < 40:
            queue.append(chunk)

if found:
    print("\n  API paths referenced by the frontend:")
    for p in sorted(found):
        print(f"    {p}")
else:
    print("\n  no /api/ strings found in the bundles that were reachable")

print("\nDone. Send this whole output back.")
