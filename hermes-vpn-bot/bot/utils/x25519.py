"""X25519 public key derivation, to check a Reality keypair actually pairs.

Reality authenticates clients against the inbound's private key while the
link carries a public key the panel stores separately. If those two were ever
regenerated out of step, every client fails authentication and is handed to
the fallback site — a connection that looks healthy and carries nothing.

Verified against the RFC 7748 section 6.1 vectors.
"""
import base64

_P = 2**255 - 19
_A24 = 121665


def _clamp(private: bytes) -> int:
    k = bytearray(private)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return int.from_bytes(k, "little")


def scalarmult(private: bytes, u_int: int = 9) -> bytes:
    """Montgomery ladder; u defaults to the curve's base point."""
    k = _clamp(private)
    x1, x2, z2, x3, z3, swap = u_int, 1, 0, u_int, 1, 0
    for t in range(254, -1, -1):
        kt = (k >> t) & 1
        swap ^= kt
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = kt
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = (da + cb) ** 2 % _P
        z3 = x1 * ((da - cb) ** 2) % _P
        x2 = aa * bb % _P
        z2 = e * ((aa + _A24 * e) % _P) % _P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    return ((x2 * pow(z2, _P - 2, _P)) % _P).to_bytes(32, "little")


def _b64decode(value: str) -> bytes:
    """Xray writes keys base64url without padding."""
    value = value.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(value + "=" * (-len(value) % 4))


def public_from_private(private_b64: str) -> str:
    """Return the base64url public key matching an Xray Reality private key."""
    raw = _b64decode(private_b64)
    if len(raw) != 32:
        raise ValueError(f"private key is {len(raw)} bytes, expected 32")
    return base64.urlsafe_b64encode(scalarmult(raw)).decode().rstrip("=")
