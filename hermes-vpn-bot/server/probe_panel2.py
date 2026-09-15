#!/usr/bin/env python3
"""Second-pass probe: why writes 404 while reads succeed.

Tests three hypotheses:
  A. /login 403s because the request does not look like the panel's own SPA —
     retry with the full browser header set a real login sends.
  B. The router answers 405 for a known path with the wrong method, which would
     make 404 a reliable "this path does not exist" signal.
  C. The write routes are named in the dashboard's JS chunks, which the first
     probe never loaded because it only ever fetched the login page.

Run:  cd /opt/irannewvpn-bot && sudo venv/bin/python server/probe_panel2.py
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

ORIGIN = "://".join(BASE.split("://")[0:1] + [BASE.split("://")[1].split("/")[0]])
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
BROWSER = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": ORIGIN,
    "Referer": BASE + "/",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

print(f"panel : {BASE}")
print(f"origin: {ORIGIN}\n")

# =============================================== A. login with browser headers
print("=" * 62)
print("A. LOGIN WITH A FULL BROWSER HEADER SET")
print("=" * 62)

cookie_session = None
attempts = [
    ("form + browser headers", {"data": {"username": USER, "password": PASS}}, BROWSER),
    ("json + browser headers", {"json": {"username": USER, "password": PASS}}, BROWSER),
    ("form + UA only", {"data": {"username": USER, "password": PASS}}, {"User-Agent": UA}),
]
for label, payload, headers in attempts:
    s = requests.Session()
    s.headers.update(headers)
    try:
        s.get(BASE + "/", timeout=15)
        r = s.post(BASE + "/login", timeout=15, **payload)
        body = r.text[:160].replace("\n", " ")
        print(f"  {label:26} -> {r.status_code}  {body}")
        if r.status_code == 200 and '"success":true' in r.text.replace(" ", ""):
            cookie_session = s
            print(f"  {'':26}    COOKIE LOGIN WORKS with this combination")
            break
    except requests.RequestException as e:
        print(f"  {label:26} -> {e}")

# =============================================== B. does the router send 405?
print()
print("=" * 62)
print("B. DOES A WRONG METHOD GIVE 405?  (tells us whether 404 means anything)")
print("=" * 62)

tok = requests.Session()
tok.headers.update(BROWSER)
if TOKEN:
    tok.headers["Authorization"] = f"Bearer {TOKEN}"

for method, path in [("GET", "/panel/api/inbounds/list"),
                     ("POST", "/panel/api/inbounds/list"),
                     ("PUT", "/panel/api/inbounds/list"),
                     ("GET", f"/panel/api/inbounds/get/{INB}"),
                     ("POST", f"/panel/api/inbounds/get/{INB}")]:
    try:
        r = tok.request(method, BASE + path, timeout=15)
        print(f"  {method:5} {path:38} {r.status_code}")
    except requests.RequestException as e:
        print(f"  {method:5} {path:38} ERR {e}")
print("  -> if POST on a known-good path gives 405, then 404 really means 'no such route'")
print("  -> if it gives 404 too, the router hides methods and 404 proves nothing")

# =============================================== C. dashboard chunks
print()
print("=" * 62)
print("C. SCAN THE DASHBOARD'S JAVASCRIPT (not just the login page)")
print("=" * 62)

fetch = cookie_session or tok
asset_base = f"{ORIGIN}{BASE[len(ORIGIN):]}"

# Vite/rolldown keep a chunk map; try the usual manifest spots first.
for manifest in ["/assets/manifest.json", "/.vite/manifest.json", "/manifest.json",
                 "/assets/.vite/manifest.json"]:
    try:
        r = fetch.get(asset_base + manifest, timeout=15)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            print(f"  found manifest at {manifest}")
            print("  " + r.text[:600])
    except requests.RequestException:
        pass

seen, queue, found = set(), [], set()
for page in ["/", "/panel/inbounds", "/inbounds", "/panel"]:
    try:
        html = fetch.get(BASE + page, timeout=15).text
        refs = re.findall(r'(?:src|href)="([^"]+\.js)"', html)
        if refs:
            print(f"  {page:18} referenced {len(refs)} scripts")
        queue += refs
    except requests.RequestException:
        pass

while queue and len(seen) < 60:
    ref = queue.pop(0)
    if ref in seen:
        continue
    seen.add(ref)
    url = ref if ref.startswith("http") else (
        asset_base + ref if ref.startswith("/") else f"{BASE}/{ref.lstrip('./')}")
    try:
        body = fetch.get(url, timeout=25).text
    except requests.RequestException:
        continue
    if len(body) < 50:
        continue
    # Any chunk this one imports, including lazily loaded route chunks.
    for chunk in re.findall(r'["\'`](\.?\/?(?:assets\/)?[A-Za-z0-9_\-]+-[A-Za-z0-9_\-]{6,}\.js)["\'`]', body):
        c = chunk if chunk.startswith("/") else "/assets/" + chunk.split("/")[-1]
        if c not in seen:
            queue.append(c)
    for pat in [r'["\'`](/?(?:panel/)?api/[A-Za-z0-9_/\-{}$.:]+)["\'`]',
                r'["\'`]([A-Za-z0-9_/\-]*[Ii]nbound[A-Za-z0-9_/\-]*)["\'`]',
                r'["\'`]([A-Za-z0-9_/\-]*[Cc]lient[A-Za-z0-9_/\-]*)["\'`]',
                r'baseURL\s*[:=]\s*["\'`]([^"\'`]+)["\'`]']:
        found |= {m for m in re.findall(pat, body) if 3 < len(m) < 80}

print(f"\n  scanned {len(seen)} files")
interesting = sorted(p for p in found
                     if any(k in p.lower() for k in ("api", "inbound", "client", "panel")))
if interesting:
    print("  strings that look like API routes:")
    for p in interesting[:80]:
        print(f"    {p}")
else:
    print("  nothing route-like found")

print("\nDone — send this whole output back.")
