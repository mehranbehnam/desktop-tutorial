#!/usr/bin/env python3
"""Why the tunnel connects but carries no traffic.

The client showing "connected" only means it loaded the profile. This checks
the three things that stop data flowing anyway: the client being expired or
out of quota, the Reality handshake failing because the server cannot reach
the destination it borrows its certificate from, and Xray not running.

    cd /opt/irannewvpn-bot && sudo venv/bin/python server/diagnose_tunnel.py
"""
import datetime
import json
import os
import sys
import time

BOT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))
sys.path.insert(0, BOT_DIR)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BOT_DIR, ".env"))
except ImportError:
    pass

from xui_client import XUIClient, XUIError  # noqa: E402

x = XUIClient()
now_ms = int(time.time() * 1000)


def when(ms):
    if not ms:
        return "never expires"
    dt = datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    return f"{dt} ({'EXPIRED' if ms < now_ms else 'valid'})"


def size(n):
    return f"{n / (1024**3):.2f} GB" if n >= 1024**3 else f"{n / (1024**2):.0f} MB"


print("=" * 68)
print("1. CLIENTS — is the one you are testing with still valid?")
print("=" * 68)
try:
    clients = x._request("GET", "/panel/api/clients/list") or []
    if not clients:
        print("  no clients exist on the panel at all")
    for entry in clients[-12:]:
        c = entry.get("client", entry)
        email = c.get("email", "?")
        traffic = x.get_client_traffic(email) or {}
        used = traffic.get("up", 0) + traffic.get("down", 0)
        total = traffic.get("total", 0)
        exp = traffic.get("expiryTime", c.get("expiryTime", 0))
        depleted = total and used >= total
        state = []
        if not traffic.get("enable", c.get("enable", True)):
            state.append("DISABLED")
        if exp and exp < now_ms:
            state.append("EXPIRED")
        if depleted:
            state.append("QUOTA USED UP")
        flag = ("  <== " + ", ".join(state)) if state else "  (usable)"
        print(f"  {email:28} {size(used)} / {total and size(total) or 'unlimited'}"
              f"  exp {when(exp)}{flag}")
except XUIError as e:
    print(f"  could not list clients: {e}")

print()
print("=" * 68)
print("2. INBOUND — what the Reality handshake borrows")
print("=" * 68)
try:
    inbound = x.get_inbound()
    stream = inbound.get("streamSettings")
    stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
    reality = stream.get("realitySettings") or {}
    settings = reality.get("settings") or {}
    print(f"  port          : {inbound.get('port')}")
    print(f"  protocol      : {inbound.get('protocol')}   enabled: {inbound.get('enable')}")
    print(f"  security      : {stream.get('security')}")
    dest = reality.get("dest") or reality.get("target")
    names = reality.get("serverNames") or []
    print(f"  reality dest  : {dest}")
    print(f"  server names  : {names}")
    print(f"  fingerprint   : {settings.get('fingerprint')}")
    host = str(dest or "") + " " + " ".join(names)
    sanctioned = [d for d in ("microsoft.com", "apple.com", "amazon", "google",
                              "cloudflare.com", "intel.com", "nvidia")
                  if d in host.lower()]
    if sanctioned:
        print(f"\n  WARNING: the handshake borrows {sanctioned[0]}, which blocks Iranian")
        print("  addresses under sanctions. If this server cannot open a TLS 1.3")
        print("  connection to it, Reality fails and the client connects but moves")
        print("  no data — exactly the symptom being diagnosed. Point dest and")
        print("  serverNames at a site this server can actually reach from Iran")
        print("  (for example www.aparat.com or www.digikala.com), regenerate the")
        print("  links, and restart Xray.")
except (XUIError, ValueError) as e:
    print(f"  could not read the inbound: {e}")

print()
print("=" * 68)
print("3. IS ANY TRAFFIC ARRIVING AT ALL?")
print("=" * 68)
try:
    logs = x._request("POST", "/panel/api/server/xraylogs/200") or []
    if not logs:
        print("  the connection log is empty — nothing has reached Xray recently.")
        print("  That points at the handshake failing before any request is made.")
    else:
        print(f"  last {min(len(logs), 15)} of {len(logs)} connection records:")
        for row in logs[-15:]:
            if isinstance(row, dict):
                print(f"    {row.get('DateTime','')} {str(row.get('Email','')):22}"
                      f" -> {row.get('ToAddress','')}  via {row.get('Outbound','')}")
            else:
                print(f"    {str(row)[:140]}")
except XUIError as e:
    print(f"  could not read the log: {e}")

print()
print("=" * 68)
print("4. XRAY PROCESS OUTPUT (startup and runtime errors)")
print("=" * 68)
try:
    out = x._request("GET", "/panel/api/xray/getXrayResult")
    text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    print("  " + (text.strip()[:1500] if text and text.strip() else "(empty — no errors reported)"))
except XUIError as e:
    print(f"  could not read xray output: {e}")

print("\nDone — send this whole output back.")
