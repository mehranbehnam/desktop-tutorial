"""Thin wrapper around the x-ui / 3x-ui panel REST API.

Route layout differs between panel builds: some expose everything under
/panel/api/inbounds/*, others only implement reads there and keep the
mutating calls on the web-UI routes under /panel/inbound/*. Each call below
therefore tries the known candidates in order and keeps the one that answers.

The panel also rejects requests without a browser-like User-Agent, and
mutating calls need a real login cookie even when an API token is present.
"""
import json
import time
import uuid

import requests

import config

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


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
        self.session.headers["User-Agent"] = BROWSER_UA
        self.session.headers["Accept"] = "application/json, text/plain, */*"
        if self.api_token:
            self.session.headers["Authorization"] = f"Bearer {self.api_token}"
        self._authed = False

    def _login(self):
        """Establish a cookie session. Mutating routes need it even with a token."""
        if not (self.username and self.password):
            if not self.api_token:
                raise XUIError("No XUI credentials: set XUI_USERNAME/XUI_PASSWORD or XUI_API_TOKEN")
            self._authed = True
            return

        try:
            # Touch the root page first so the panel hands out its initial cookie.
            self.session.get(self.base_url + "/", timeout=15)
            r = self.session.post(
                f"{self.base_url}/login",
                data={"username": self.username, "password": self.password},
                timeout=15,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise XUIError(f"Cannot reach panel at {self.base_url}: {e}") from e
        try:
            body = r.json()
        except ValueError:
            raise XUIError(f"XUI login returned non-JSON (HTTP {r.status_code})")
        if not body.get("success"):
            raise XUIError(f"XUI login failed: {body}")
        self._authed = True

    def _try_paths(self, method: str, paths: list[str], **kwargs):
        """Call the first candidate path the panel actually implements.

        A 404 means "wrong route for this build" — move on to the next one.
        """
        if not self._authed:
            self._login()

        last_error = None
        for path in paths:
            try:
                r = self.session.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
                if r.status_code in (401, 403):
                    self._login()
                    r = self.session.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
                if r.status_code == 404:
                    last_error = f"{path} -> 404"
                    continue
                r.raise_for_status()
            except requests.RequestException as e:
                last_error = f"{path} -> {e}"
                continue
            try:
                body = r.json()
            except ValueError:
                last_error = f"{path} -> non-JSON response"
                continue
            if not body.get("success", False):
                raise XUIError(f"XUI API error on {path}: {body}")
            return body.get("obj")

        raise XUIError(f"No working route among {paths} ({last_error})")

    @staticmethod
    def _build_client(client_uuid: str, email: str, gb: int, expiry_ms: int) -> dict:
        return {
            "id": client_uuid,
            "email": email,
            "limitIp": 0,
            "totalGB": 0 if gb <= 0 else gb * 1024 * 1024 * 1024,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": "",
            "subId": uuid.uuid4().hex[:16],
            "flow": "xtls-rprx-vision",
        }

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

        client = self._build_client(client_uuid, email, gb, expiry_ms)
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        self._try_paths(
            "POST",
            ["/panel/inbound/addClient", "/panel/api/inbounds/addClient"],
            data=payload,
        )
        return {"uuid": client_uuid, "email": email, "expiry_time": expiry_ms, "total_gb": gb}

    def update_client(self, client_uuid: str, email: str, gb: int, days: int, inbound_id: int = None) -> dict:
        """Renew/replace a client's quota and expiry (used for the 'renew service' flow)."""
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        expiry_ms = 0 if days <= 0 else int((time.time() + days * 86400) * 1000)

        client = self._build_client(client_uuid, email, gb, expiry_ms)
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        self._try_paths(
            "POST",
            [
                f"/panel/inbound/updateClient/{client_uuid}",
                f"/panel/api/inbounds/updateClient/{client_uuid}",
            ],
            data=payload,
        )
        return {"uuid": client_uuid, "email": email, "expiry_time": expiry_ms, "total_gb": gb}

    def delete_client(self, inbound_id: int, client_uuid: str):
        self._try_paths(
            "POST",
            [
                f"/panel/inbound/{inbound_id}/delClient/{client_uuid}",
                f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}",
            ],
        )

    def get_client_traffic(self, email: str) -> dict | None:
        return self._try_paths(
            "GET",
            [
                f"/panel/api/inbounds/getClientTraffics/{email}",
                f"/panel/inbound/getClientTraffics/{email}",
            ],
        )

    def get_inbound(self, inbound_id: int = None) -> dict:
        """Fetch one inbound, falling back to filtering the full list.

        /panel/api/inbounds/list is the one route confirmed present on every
        build we've seen, so it is the reliable fallback.
        """
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        try:
            return self._try_paths(
                "GET",
                [f"/panel/api/inbounds/get/{inbound_id}", f"/panel/inbound/get/{inbound_id}"],
            )
        except XUIError:
            inbounds = self._try_paths("GET", ["/panel/api/inbounds/list"]) or []
            for inbound in inbounds:
                if inbound.get("id") == inbound_id:
                    return inbound
            raise XUIError(f"Inbound {inbound_id} not found in panel inbound list")

    def build_vless_link(self, client_uuid: str, email: str, remark: str = "") -> str:
        """Builds a vless:// link from the inbound's Reality stream settings.

        Good enough for manual copy/paste into v2rayNG / NekoBox / Streisand etc.
        """
        inbound = self.get_inbound()
        try:
            stream = json.loads(inbound["streamSettings"])
            reality = stream["realitySettings"]
            port = inbound["port"]
        except (KeyError, ValueError, TypeError) as e:
            raise XUIError(f"Inbound {inbound.get('id')} is not a Reality inbound: {e}") from e

        # The panel API is reached over localhost/LAN for security, but the
        # client link must point at the server's public IP/domain.
        host = config.XUI_PUBLIC_HOST or self.base_url.split("//", 1)[-1].split(":")[0].split("/")[0]

        try:
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
        except (KeyError, IndexError) as e:
            raise XUIError(f"Reality settings incomplete on inbound: missing {e}") from e
        query = "&".join(f"{k}={v}" for k, v in params.items())
        tag = remark or email
        return f"vless://{client_uuid}@{host}:{port}?{query}#{tag}"
