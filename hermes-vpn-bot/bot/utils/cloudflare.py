"""Minimal Cloudflare API client for the WS+TLS-behind-CDN setup.

Only what's needed to stand up one subdomain: find its zone, point it at
the Iran server (proxied, so Cloudflare's edge fronts it), and issue an
Origin CA certificate to install there. Runs inside the bot process
(ordinary internet access), never in whatever environment writes this code.
"""
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import config

BASE = "https://api.cloudflare.com/client/v4"


class CloudflareError(RuntimeError):
    pass


def _headers() -> dict:
    if not config.CLOUDFLARE_API_TOKEN:
        raise CloudflareError("توکن Cloudflare تنظیم نشده — از ☁️ تنظیم Cloudflare API استفاده کن.")
    return {"Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}


def _call(method: str, path: str, **kwargs):
    try:
        r = requests.request(method, f"{BASE}{path}", headers=_headers(), timeout=20, **kwargs)
        body = r.json()
    except CloudflareError:
        raise
    except Exception as e:
        raise CloudflareError(f"{type(e).__name__}: {e}") from e
    if not body.get("success"):
        raise CloudflareError(str(body.get("errors") or body))
    return body.get("result")


def get_zone_id(domain: str) -> str:
    result = _call("GET", "/zones", params={"name": domain})
    if not result:
        raise CloudflareError(f"دامنه‌ی {domain} تو این اکانت Cloudflare پیدا نشد.")
    return result[0]["id"]


def create_or_update_dns_record(zone_id: str, hostname: str, ip: str, proxied: bool = True) -> dict:
    """Create an A record, or update it in place if one already exists."""
    existing = _call("GET", f"/zones/{zone_id}/dns_records", params={"name": hostname, "type": "A"})
    payload = {"type": "A", "name": hostname, "content": ip, "ttl": 1, "proxied": proxied}
    if existing:
        return _call("PUT", f"/zones/{zone_id}/dns_records/{existing[0]['id']}", json=payload)
    return _call("POST", f"/zones/{zone_id}/dns_records", json=payload)


def generate_key_and_csr(hostname: str) -> tuple[str, str]:
    """A fresh RSA keypair + CSR for `hostname`. The private key never
    leaves this function's caller — only the CSR (a public signing
    request, no secret material) goes to Cloudflare."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()
    return key_pem, csr_pem


def request_origin_certificate(hostnames: list[str], csr: str) -> dict:
    """Issue a Cloudflare Origin CA cert (15-year validity) for `hostnames`.

    `csr` is a PEM-encoded certificate signing request; Cloudflare signs it
    and returns the certificate, so the private key never leaves the
    server that generated the CSR.
    """
    payload = {
        "hostnames": hostnames,
        "requested_validity": 5475,  # 15 years, Cloudflare's max
        "request_type": "origin-rsa",
        "csr": csr,
    }
    return _call("POST", "/certificates", json=payload)
