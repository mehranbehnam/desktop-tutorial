#!/usr/bin/env python3
"""
One-time helper: connects to a freshly-installed 3x-ui panel and creates a
VLESS + Reality inbound (no TLS certs to manage, good default for a small
VPS). Prints the values you need to put in bot/.env when it's done.

Auth: newer 3x-ui versions print an API Token at install time (see
/etc/x-ui/install-result.env) and require it for programmatic access —
the cookie-session /login endpoint rejects non-browser clients with a
plain 403. Pass that token with --api-token.

Usage:
    pip install requests
    python3 setup_inbound.py \
        --url http://127.0.0.1:PANEL_PORT/WEB_BASE_PATH \
        --api-token YOUR_API_TOKEN \
        --port 443 --sni www.microsoft.com
"""
import argparse
import glob
import json
import shutil
import subprocess
import sys
import uuid

import requests


def build_session(api_token: str) -> requests.Session:
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {api_token}"
    return session


def find_xray_binary() -> str:
    """Locate the xray-core binary x-ui manages, rather than guessing the
    panel's API route for key generation (that route's path has changed
    between panel versions and isn't worth chasing)."""
    candidates = [
        "/usr/local/x-ui/bin/xray-linux-amd64",
        "/usr/local/x-ui/bin/xray-linux-arm64",
        "/usr/local/x-ui/bin/xray-linux-arm64-v8a",
        "/usr/local/x-ui/xray-linux-amd64",
    ]
    candidates += glob.glob("/usr/local/x-ui/bin/xray-linux-*")
    for c in candidates:
        if shutil.which(c):
            return c
    found = shutil.which("xray")
    if found:
        return found
    raise RuntimeError(
        "Could not find the xray binary (looked under /usr/local/x-ui/bin and PATH). "
        "Run 'find / -name \"xray-linux-*\" 2>/dev/null' on the server to locate it."
    )


def generate_x25519_keypair() -> dict:
    xray_bin = find_xray_binary()
    result = subprocess.run([xray_bin, "x25519"], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(f"'{xray_bin} x25519' failed:\n{result.stderr}")

    private_key = public_key = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label = label.strip().lower()
        value = value.strip()
        # Label wording varies across xray-core versions/builds, e.g.
        # "PrivateKey:" vs "Private key:", and the public key has shown up
        # as "PublicKey:" or "Password (PublicKey):" — match by substring.
        if "private" in label:
            private_key = value
        elif "public" in label or "password" in label:
            public_key = value

    if not private_key or not public_key:
        raise RuntimeError(f"Could not parse '{xray_bin} x25519' output:\n{result.stdout}")
    return {"privateKey": private_key, "publicKey": public_key}


def create_inbound(session: requests.Session, base_url: str, port: int, remark: str, sni: str, keypair: dict) -> dict:
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
    ap.add_argument("--url", required=True, help="e.g. http://127.0.0.1:PANEL_PORT/WEB_BASE_PATH")
    ap.add_argument("--api-token", required=True, help="from /etc/x-ui/install-result.env")
    ap.add_argument("--public-host", default="", help="public IP/domain clients connect to (for reference only)")
    ap.add_argument("--port", type=int, default=443, help="Public port clients connect to")
    ap.add_argument("--remark", default="main")
    ap.add_argument("--sni", default="www.microsoft.com", help="Reality masking domain (a real, reachable HTTPS site)")
    args = ap.parse_args()

    base_url = args.url.rstrip("/")
    session = build_session(args.api_token)

    print("Generating Reality keypair (via local xray binary)...")
    keypair = generate_x25519_keypair()

    print("Creating inbound...")
    inbound = create_inbound(session, base_url, args.port, args.remark, args.sni, keypair)

    print("\n=== Done. Put these in bot/.env ===")
    print(f"XUI_BASE_URL={base_url}")
    print(f"XUI_API_TOKEN={args.api_token}")
    print(f"XUI_INBOUND_ID={inbound['id']}")
    if args.public_host:
        print(f"XUI_PUBLIC_HOST={args.public_host}")
    print("\n(The bot creates/deletes clients inside this inbound automatically via the panel API.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
