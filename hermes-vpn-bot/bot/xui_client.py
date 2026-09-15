"""Client for the 3x-ui v3 panel API.

Routes and payloads follow the panel's published OpenAPI description: clients
are their own resource under /panel/api/clients, not an operation on an
inbound. The panel generates the per-protocol secrets and renders the
subscription URLs, so neither is built here.

Authentication is the API token (Authorization: Bearer). Cookie login is only
attempted as a fallback for builds that lack token auth — this one answers
/login with 403 for any non-browser client.
"""
import time

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
        self._authed = bool(self.api_token)

    def _login(self):
        if self._authed:
            return
        if not (self.username and self.password):
            raise XUIError("No XUI credentials: set XUI_API_TOKEN, or XUI_USERNAME/XUI_PASSWORD")
        try:
            self.session.get(self.base_url + "/", timeout=15)
            r = self.session.post(
                f"{self.base_url}/login",
                data={"username": self.username, "password": self.password},
                timeout=15,
            )
            r.raise_for_status()
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            raise XUIError(f"Cannot log in to panel at {self.base_url}: {e}") from e
        if not body.get("success"):
            raise XUIError(f"XUI login failed: {body}")
        self._authed = True

    def _request(self, method: str, path: str, **kwargs):
        self._login()
        url = f"{self.base_url}{path}"
        try:
            r = self.session.request(method, url, timeout=20, **kwargs)
            r.raise_for_status()
            body = r.json()
        except requests.RequestException as e:
            raise XUIError(f"{method} {path} failed: {e}") from e
        except ValueError as e:
            raise XUIError(f"{method} {path} returned non-JSON: {e}") from e
        if not body.get("success", False):
            raise XUIError(f"XUI API error on {path}: {body.get('msg') or body}")
        return body.get("obj")

    @staticmethod
    def _expiry_ms(days: int, hours: int = 0) -> int:
        if hours > 0:
            return int((time.time() + hours * 3600) * 1000)
        if days > 0:
            return int((time.time() + days * 86400) * 1000)
        return 0

    def add_client(self, email: str, gb: int, days: int = 0, inbound_id: int = None, hours: int = 0) -> dict:
        """Create a client and attach it to the configured inbound.

        Pass either `days` or `hours` (hours wins, e.g. for short trials);
        0/0 means no expiry. The panel generates the UUID and subId itself.

        Returns dict with uuid, email, expiry_time (ms epoch), total_gb.
        """
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        expiry_ms = self._expiry_ms(days, hours)
        payload = {
            "client": {
                "email": email,
                "totalGB": 0 if gb <= 0 else gb * 1024 * 1024 * 1024,
                "expiryTime": expiry_ms,
                "tgId": 0,
                "limitIp": 0,
                "limitHwid": 0,
                "enable": True,
            },
            "inboundIds": [int(inbound_id)],
        }
        self._request("POST", "/panel/api/clients/add", json=payload)
        created = self.get_client_traffic(email) or {}
        return {
            "uuid": created.get("uuid", ""),
            "email": email,
            "expiry_time": expiry_ms,
            "total_gb": gb,
        }

    def update_client(self, client_uuid: str, email: str, gb: int, days: int, inbound_id: int = None) -> dict:
        """Renew a client's quota and expiry (the 'renew service' flow)."""
        expiry_ms = self._expiry_ms(days)
        payload = {
            "email": email,
            "totalGB": 0 if gb <= 0 else gb * 1024 * 1024 * 1024,
            "expiryTime": expiry_ms,
            "enable": True,
        }
        self._request("POST", f"/panel/api/clients/update/{email}", json=payload)
        return {"uuid": client_uuid, "email": email, "expiry_time": expiry_ms, "total_gb": gb}

    def delete_client(self, inbound_id: int, client_uuid: str, email: str = None):
        """Delete a client. The panel addresses clients by email, not UUID."""
        if not email:
            raise XUIError("delete_client needs the client's email on this panel version")
        self._request("POST", f"/panel/api/clients/del/{email}")

    def get_client_traffic(self, email: str) -> dict | None:
        try:
            return self._request("GET", f"/panel/api/clients/traffic/{email}")
        except XUIError:
            return None

    def get_inbound(self, inbound_id: int = None) -> dict:
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        return self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")

    def build_vless_link(self, client_uuid: str, email: str, remark: str = "") -> str:
        """Return the client's connection URL as the panel renders it.

        The panel knows the inbound's advertised hosts, Reality keys and
        protocol, so its own link is authoritative — including for inbounds
        that are not Reality at all.
        """
        links = self._request("GET", f"/panel/api/clients/links/{email}") or []
        if not links:
            raise XUIError(f"panel returned no connection link for {email}")
        link = links[0]
        if remark:
            link = link.split("#", 1)[0] + "#" + remark
        return link
