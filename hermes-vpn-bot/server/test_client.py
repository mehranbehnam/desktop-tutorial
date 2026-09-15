#!/usr/bin/env python3
"""Standalone check: create a throwaway client, print its vless:// link, delete it.

Run on the bot server:
    cd /opt/irannewvpn-bot && venv/bin/python server/test_client.py
"""
import os
import sys
import time

BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot")
sys.path.insert(0, os.path.abspath(BOT_DIR))

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.abspath(BOT_DIR), ".env"))
except ImportError:
    pass

import config  # noqa: E402
from xui_client import XUIClient, XUIError  # noqa: E402

email = f"selftest_{int(time.time())}"

print(f"panel   : {config.XUI_BASE_URL}")
print(f"inbound : {config.XUI_INBOUND_ID}")
print(f"auth    : {'token+cookie' if config.XUI_API_TOKEN else 'cookie'}")
print()

client = XUIClient()

try:
    client._login()
    print("[1/4] login OK")
except XUIError as e:
    sys.exit(f"[1/4] login FAILED: {e}")

try:
    inbound = client.get_inbound()
    print(f"[2/4] inbound OK (port {inbound['port']})")
except Exception as e:
    sys.exit(f"[2/4] inbound FAILED: {e}")

try:
    created = client.add_client(email=email, gb=1, hours=1)
    print(f"[3/4] add_client OK -> {created['uuid']}")
except Exception as e:
    sys.exit(f"[3/4] add_client FAILED: {e}")

try:
    link = client.build_vless_link(created["uuid"], email, remark="selftest")
    print("[4/4] link OK\n")
    print(link)
except Exception as e:
    sys.exit(f"[4/4] build_vless_link FAILED: {e}")

if "--keep" not in sys.argv:
    try:
        client.delete_client(config.XUI_INBOUND_ID, created["uuid"], email=email)
        print("\ncleanup: test client deleted (pass --keep to retain it)")
    except Exception as e:
        print(f"\ncleanup: could not delete {created['uuid']}: {e}")
