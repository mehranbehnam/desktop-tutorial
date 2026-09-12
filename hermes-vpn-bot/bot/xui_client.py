"""Thin wrapper around the 3x-ui panel REST API.

Endpoints follow the conventions used by MHSanaei/3x-ui (a common fork of
x-ui). If you're running a different fork, check its /panel/api routes —
paths may differ slightly between versions.
"""
import json
import time
import uuid

import requests

import config


class XUIError(RuntimeError):
    pass


class XUIClient:
    def __init__(
        self,
        base_url: str = None,
        username: str = None,
        password: str = None,
        api_token: str = None,
    ):
        self.base_url = (base_url or config.XUI_BASE_URL).rstrip("/")
        self.username = username or config.XUI_USERNAME
        self.password = password or config.XUI_PASSWORD
        self.api_token = api_token if api_token is not None else config.XUI_API_TOKEN
        self.session = requests.Session()
        self._authed = False
        if self.api_token:
            self.session.headers["Authorization"] = f"Bearer {self.api_token}"
            self._authed = True

    def _login(self):
        if self.api_token:
            self._authed = True
            return
        r = self.session.post(
            f"{self.base_url}/login",
            data={"username": self.username, "password": self.password},
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("success"):
            raise XUIError(f"XUI login failed: {body}")
        self._authed = True

    def _request(self, method: str, path: str, **kwargs):
        if not self._authed:
            self._login()
        r = self.session.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
        if r.status_code == 401 and not self.api_token:
            # session expired, retry once after re-login (token auth never expires this way)
            self._login()
            r = self.session.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
        r.raise_for_status()
        body = r.json()
        if not body.get("success", False):
            raise XUIError(f"XUI API error on {path}: {body}")
        return body.get("obj")

    def add_client(self, email: str, gb: int, days: int = 0, inbound_id: int = None, hours: int = 0) -> dict:
        """Create a VLESS client inside the configured inbound.

        Pass either `days` or `hours` (hours wins if both are given, e.g. for
        short trial accounts). 0/0 means no expiry.

        Returns dict with uuid, email, expiry_time (ms epoch), total_gb.
        """
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        client_uuid = str(uuid.uuid4())
        if hours > 0:
            expiry_ms = int((time.time() + hours * 3600) * 1000)
        elif days > 0:
            expiry_ms = int((time.time() + days * 86400) * 1000)
        else:
            expiry_ms = 0
        total_bytes = 0 if gb <= 0 else gb * 1024 * 1024 * 1024

        client = {
            "id": client_uuid,
            "email": email,
            "limitIp": 0,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": "",
            "subId": uuid.uuid4().hex[:16],
            "flow": "xtls-rprx-vision",
        }
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        self._request("POST", "/panel/api/inbounds/addClient", data=payload)
        return {"uuid": client_uuid, "email": email, "expiry_time": expiry_ms, "total_gb": gb}

    def update_client(self, client_uuid: str, email: str, gb: int, days: int, inbound_id: int = None) -> dict:
        """Renew/replace a client's quota and expiry (used for the 'renew service' flow)."""
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        expiry_ms = 0 if days <= 0 else int((time.time() + days * 86400) * 1000)
        total_bytes = 0 if gb <= 0 else gb * 1024 * 1024 * 1024

        client = {
            "id": client_uuid,
            "email": email,
            "limitIp": 0,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": "",
            "subId": uuid.uuid4().hex[:16],
            "flow": "xtls-rprx-vision",
        }
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        self._request("POST", f"/panel/api/inbounds/updateClient/{client_uuid}", data=payload)
        return {"uuid": client_uuid, "email": email, "expiry_time": expiry_ms, "total_gb": gb}

    def delete_client(self, inbound_id: int, client_uuid: str):
        self._request("POST", f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}")

    def get_client_traffic(self, email: str) -> dict | None:
        obj = self._request("GET", f"/panel/api/inbounds/getClientTraffics/{email}")
        return obj

    def get_inbound(self, inbound_id: int = None) -> dict:
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        return self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")

    def build_vless_link(self, client_uuid: str, email: str, remark: str = "") -> str:
        """Builds a vless:// link from the inbound's Reality stream settings.

        Good enough for manual copy/paste into v2rayNG / NekoBox / Streisand etc.
        """
        inbound = self.get_inbound()
        stream = json.loads(inbound["streamSettings"])
        reality = stream["realitySettings"]
        port = inbound["port"]

        # The panel API is reached over localhost/LAN for security, but the
        # client link must point at the server's public IP/domain.
        host = config.XUI_PUBLIC_HOST or self.base_url.split("//", 1)[-1].split(":")[0].split("/")[0]

        params = {
            "type": stream.get("network", "tcp"),
            "security": "reality",
            "pbk": reality["settings"]["publicKey"],
            "fp": reality["settings"].get("fingerprint", "chrome"),
            "sni": reality["serverNames"][0],
            "sid": reality["shortIds"][0],
            "spx": reality["settings"].get("spiderX", "/"),
            "flow": "xtls-rprx-vision",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        tag = remark or email
        return f"vless://{client_uuid}@{host}:{port}?{query}#{tag}"
