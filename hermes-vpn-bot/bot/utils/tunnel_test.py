"""Run a real Xray client against our own inbound, from the bot server itself.

This answers the one question nothing else can: does a genuine Reality
handshake succeed against this inbound at all, independent of the user's
phone, carrier, or app. If it works from here (Frankfurt) but not from the
user's device, the server is proven fine and the fault is on the path
between their carrier and the Iran server. If it fails here too, the debug
log says exactly why.
"""
import json
import os
import subprocess
import time
import urllib.request
import zipfile

XRAY_DIR = "/tmp/irannewvpn-xraytest"
XRAY_BIN = os.path.join(XRAY_DIR, "xray")
XRAY_URL = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"


def ensure_xray() -> str:
    """Download and unpack the Xray-core binary once; reuse it after that."""
    if os.path.isfile(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK):
        return XRAY_BIN
    os.makedirs(XRAY_DIR, exist_ok=True)
    zip_path = os.path.join(XRAY_DIR, "xray.zip")
    urllib.request.urlretrieve(XRAY_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract("xray", XRAY_DIR)
    os.chmod(XRAY_BIN, 0o755)
    os.remove(zip_path)
    return XRAY_BIN


def build_client_config(socks_port: int, server_host: str, server_port: int,
                        uuid: str, reality: dict, flow: str) -> dict:
    settings = reality.get("settings") or {}
    names = reality.get("serverNames") or []
    short_ids = reality.get("shortIds") or []
    outbound_user = {"id": uuid, "encryption": "none"}
    if flow:
        outbound_user["flow"] = flow
    return {
        "log": {"loglevel": "debug"},
        "inbounds": [{"listen": "127.0.0.1", "port": socks_port, "protocol": "socks",
                      "settings": {"udp": False}}],
        "outbounds": [{
            "protocol": "vless",
            "settings": {"vnext": [{"address": server_host, "port": server_port,
                                    "users": [outbound_user]}]},
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "serverName": names[0] if names else "",
                    "fingerprint": settings.get("fingerprint", "chrome"),
                    "publicKey": settings.get("publicKey", ""),
                    "shortId": short_ids[0] if short_ids else "",
                    "spiderX": settings.get("spiderX", "/"),
                },
            },
        }],
    }


def run_probe(server_host: str, server_port: int, uuid: str, reality: dict,
             flow: str, socks_port: int = 19797, timeout: int = 20):
    """Returns (curl_ok, ip_or_error, log_tail)."""
    xray = ensure_xray()
    cfg_path = os.path.join(XRAY_DIR, "client.json")
    with open(cfg_path, "w") as fh:
        json.dump(build_client_config(socks_port, server_host, server_port, uuid, reality, flow), fh)

    log_path = os.path.join(XRAY_DIR, "run.log")
    with open(log_path, "w") as log_fh:
        proc = subprocess.Popen([xray, "run", "-c", cfg_path], stdout=log_fh, stderr=subprocess.STDOUT)
    try:
        time.sleep(2.5)  # let it bind the local socks listener
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", str(timeout),
                 "--socks5-hostname", f"127.0.0.1:{socks_port}",
                 "https://api.ipify.org"],
                capture_output=True, text=True, timeout=timeout + 5,
            )
            curl_ok = result.returncode == 0 and bool(result.stdout.strip())
            ip_or_error = result.stdout.strip() if curl_ok else (
                result.stderr.strip() or f"curl exit {result.returncode}")
        except subprocess.TimeoutExpired:
            curl_ok, ip_or_error = False, "curl timed out"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    log_tail = ""
    if os.path.isfile(log_path):
        with open(log_path, errors="replace") as fh:
            lines = fh.readlines()
        log_tail = "".join(lines[-40:])

    return curl_ok, ip_or_error, log_tail
