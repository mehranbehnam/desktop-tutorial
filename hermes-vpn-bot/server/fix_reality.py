#!/usr/bin/env python3
"""Find out why the Reality handshake never completes, and repair it.

Reality hands any connection it cannot authenticate to the real site named in
`dest`, borrowing that site's certificate. So opening a plain TLS connection
to the inbound and looking at which certificate comes back says whether the
server can reach that site at all — and an Iranian server cannot reach the
sanctioned hosts these configs usually ship with.

    cd /opt/irannewvpn-bot && sudo venv/bin/python server/fix_reality.py
    ... --fix www.digikala.com    point Reality at a reachable site
"""
import json
import os
import socket
import ssl
import sys

BOT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot"))
sys.path.insert(0, BOT_DIR)
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BOT_DIR, ".env"))
except ImportError:
    pass

import config  # noqa: E402
from xui_client import XUIClient, XUIError  # noqa: E402

x = XUIClient()
HOST = config.XUI_PUBLIC_HOST or config.XUI_BASE_URL.split("//")[-1].split(":")[0]


def _cert_names(tls):
    """Subject CN and SANs of the peer certificate, without extra dependencies."""
    der = tls.getpeercert(binary_form=True)
    if not der:
        return "(none presented)"
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
        fh.write(ssl.DER_cert_to_PEM_cert(der))
        path = fh.name
    try:
        info = ssl._ssl._test_decode_cert(path)
        cn = dict(i[0] for i in info.get("subject", ())).get("commonName", "?")
        sans = [v for k, v in info.get("subjectAltName", ()) if k == "DNS"][:3]
        return f"{cn}" + (f" (also {', '.join(sans)})" if sans else "")
    except Exception:
        return "(could not parse)"
    finally:
        os.unlink(path)


def tls_probe(host, port, sni, timeout=12):
    """Return (ok, description) for a TLS handshake to host:port announcing sni."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=sni) as tls:
                # Whose certificate came back tells us which site the server
                # actually reached, which is the whole point of the probe.
                return True, f"{tls.version()}  cert={_cert_names(tls)}"
    except socket.timeout:
        return False, "timed out — the server accepted TCP but never finished the handshake"
    except ConnectionRefusedError:
        return False, "connection refused — nothing is listening on that port"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"


print("=" * 68)
print("1. IS THE PORT EVEN REACHABLE?")
print("=" * 68)
inbound = None
try:
    inbound = x.get_inbound()
    port = int(inbound.get("port", 443))
except XUIError as e:
    port = 443
    print(f"  (could not read the inbound: {e})")

try:
    with socket.create_connection((HOST, port), timeout=10):
        print(f"  OK    TCP {HOST}:{port} accepts connections")
except OSError as e:
    print(f"  FAIL  TCP {HOST}:{port} — {e}")
    print("        Nothing else matters until this works: check the Iran server's")
    print("        firewall and the cloud security rules for this port.")
    sys.exit(1)

print()
print("=" * 68)
print("2. WHAT REALITY BORROWS, AND WHETHER THE SERVER CAN REACH IT")
print("=" * 68)

stream = inbound.get("streamSettings") if inbound else None
stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
reality = stream.get("realitySettings") or {}
dest = reality.get("dest") or reality.get("target") or ""
names = reality.get("serverNames") or []
sni = names[0] if names else dest.split(":")[0]
print(f"  dest        : {dest}")
print(f"  serverNames : {names}")

ok, detail = tls_probe(HOST, port, sni)
print(f"\n  TLS to {HOST}:{port} with SNI {sni}")
print(f"    {'OK  ' if ok else 'FAIL'}  {detail}")

if ok:
    print("\n  The server completed a handshake, so it can reach the borrowed site.")
    print("  Reality's fallback is healthy — the failure is elsewhere (check that")
    print("  the client's publicKey/shortId match this inbound).")
else:
    print("\n  The server could not finish the borrowed handshake. Clients will")
    print("  connect and then move zero bytes, which is the symptom being chased.")
    print(f"  {sni} is very likely unreachable from an Iranian address.")
    print("\n  Re-run with a site this server can reach, for example:")
    print("    sudo venv/bin/python server/fix_reality.py --fix www.digikala.com")

if "--fix" in sys.argv:
    try:
        new_host = sys.argv[sys.argv.index("--fix") + 1]
    except IndexError:
        sys.exit("\n--fix needs a hostname, e.g. --fix www.digikala.com")

    print()
    print("=" * 68)
    print(f"3. REPOINTING REALITY AT {new_host}")
    print("=" * 68)

    backup = f"/tmp/inbound-{inbound.get('id')}-backup.json"
    with open(backup, "w") as fh:
        json.dump(inbound, fh, indent=2)
    print(f"  saved the current inbound to {backup}")

    reality["dest"] = f"{new_host}:443"
    reality["serverNames"] = [new_host]
    stream["realitySettings"] = reality

    body = {
        "enable": inbound.get("enable", True),
        "remark": inbound.get("remark", ""),
        "listen": inbound.get("listen", ""),
        "port": inbound.get("port"),
        "protocol": inbound.get("protocol"),
        "expiryTime": inbound.get("expiryTime", 0),
        "total": inbound.get("total", 0),
        "settings": json.loads(inbound["settings"]) if isinstance(inbound.get("settings"), str)
        else inbound.get("settings", {}),
        "streamSettings": stream,
        "sniffing": json.loads(inbound["sniffing"]) if isinstance(inbound.get("sniffing"), str)
        else inbound.get("sniffing", {}),
    }
    try:
        x._request("POST", f"/panel/api/inbounds/update/{inbound['id']}", json=body)
        print("  inbound updated")
        x._request("POST", "/panel/api/server/restartXrayService")
        print("  xray restarted")
    except XUIError as e:
        sys.exit(f"  FAILED: {e}\n  the previous inbound is saved at {backup}")

    import time

    time.sleep(6)
    ok2, detail2 = tls_probe(HOST, port, new_host)
    print(f"\n  re-test with SNI {new_host}:")
    print(f"    {'OK  ' if ok2 else 'FAIL'}  {detail2}")
    if ok2:
        print("\n  Handshake works now. Existing links carry the old SNI, so issue a")
        print("  fresh one from the bot's trial button and test with that.")
    else:
        print(f"\n  Still failing — try another site, or restore {backup}.")
