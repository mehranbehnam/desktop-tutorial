#!/usr/bin/env python3
"""
One-time helper: logs into a freshly-installed 3x-ui panel and creates a
VLESS + Reality inbound (no TLS certs to manage, good default for a small
VPS). Prints the values you need to put in bot/.env when it's done.

Usage:
    pip install requests
    python3 setup_inbound.py \
        --url http://SERVER_IP:2053 \
        --username admin --password admin \
        --port 443 --remark "main" --sni www.microsoft.com

Run this AFTER you've set a real panel username/password via the `x-ui`
menu on the server (don't leave admin/admin).
"""
import argparse
import json
import sys
import uuid

import requests


def login(session: requests.Session, base_url: str, username: str, password: str) -> None:
    r = session.post(f"{base_url}/login", data={"username": username, "password": password}, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("success", False):
        raise RuntimeError(f"Login failed: {body}")


def get_reality_keypair(session: requests.Session, base_url: str) -> dict:
    r = session.post(f"{base_url}/panel/api/server/getNewX25519Cert", timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("success", False):
        raise RuntimeError(f"Could not generate Reality keypair: {body}")
    return body["obj"]


def create_inbound(session: requests.Session, base_url: str, port: int, remark: str, sni: str, keypair: dict) -> dict:
    client_id = str(uuid.uuid4())
    short_id = uuid.uuid4().hex[:8]

    settings = {
        "clients": [],
        "decryption": "none",
        "fallbacks": [],
    }

    stream_settings = {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
            "show": False,
            "dest": f"{sni}:443",
            "xver": 0,
            "serverNames": [sni],
            "privateKey": keypair["privateKey"],
            "publicKey": keypair["publicKey"],
            "shortIds": [short_id],
            "settings": {
                "publicKey": keypair["publicKey"],
                "fingerprint": "chrome",
                "serverName": sni,
                "spiderX": "/",
            },
        },
    }

    sniffing = {"enabled": True, "destOverride": ["http", "tls", "quic"]}

    payload = {
        "up": 0,
        "down": 0,
        "total": 0,
        "remark": remark,
        "enable": True,
        "expiryTime": 0,
        "listen": "",
        "port": port,
        "protocol": "vless",
        "settings": json.dumps(settings),
        "streamSettings": json.dumps(stream_settings),
        "sniffing": json.dumps(sniffing),
    }

    r = session.post(f"{base_url}/panel/api/inbounds/add", data=payload, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("success", False):
        raise RuntimeError(f"Could not create inbound: {body}")
    return body["obj"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="e.g. http://SERVER_IP:2053 (or your custom panel port)")
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--port", type=int, default=443, help="Public port clients connect to")
    ap.add_argument("--remark", default="main")
    ap.add_argument("--sni", default="www.microsoft.com", help="Reality masking domain (a real, reachable HTTPS site)")
    args = ap.parse_args()

    base_url = args.url.rstrip("/")
    session = requests.Session()

    print("Logging into panel...")
    login(session, base_url, args.username, args.password)

    print("Generating Reality keypair...")
    keypair = get_reality_keypair(session, base_url)

    print("Creating inbound...")
    inbound = create_inbound(session, base_url, args.port, args.remark, args.sni, keypair)

    print("\n=== Done. Put these in bot/.env ===")
    print(f"XUI_BASE_URL={base_url}")
    print(f"XUI_USERNAME={args.username}")
    print(f"XUI_PASSWORD={args.password}")
    print(f"XUI_INBOUND_ID={inbound['id']}")
    print("\n(The bot creates/deletes clients inside this inbound automatically via the panel API.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
