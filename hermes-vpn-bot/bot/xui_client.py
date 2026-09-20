"""Client for the 3x-ui v3 panel API.

Routes and payloads follow the panel's published OpenAPI description: clients
are their own resource under /panel/api/clients, not an operation on an
inbound. The panel generates the per-protocol secrets and renders the
subscription URLs, so neither is built here.

Authentication is the API token (Authorization: Bearer). Cookie login is only
attempted as a fallback for builds that lack token auth — this one answers
/login with 403 for any non-browser client.
"""
import json
import re
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
        self._panel_settings = None
        self._flow = None

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

    def add_client(self, email: str, gb: int = 0, days: int = 0, inbound_id: int = None,
                   hours: int = 0, mb: int = 0) -> dict:
        """Create a client and attach it to the configured inbound.

        Quota comes from `mb` when given (trials are sub-gigabyte), otherwise
        `gb`; 0 for both means unlimited. Pass either `days` or `hours` (hours
        wins); 0/0 means no expiry. The panel generates the UUID and subId.

        Returns dict with uuid, email, expiry_time (ms epoch), total_gb.
        """
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        expiry_ms = self._expiry_ms(days, hours)
        total_bytes = mb * 1024 * 1024 if mb > 0 else (gb * 1024 * 1024 * 1024 if gb > 0 else 0)
        client = {
            "email": email,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "tgId": 0,
            "limitIp": 0,
            "limitHwid": 0,
            "enable": True,
        }
        flow = self.client_flow(inbound_id)
        if flow:
            client["flow"] = flow
        payload = {
            "client": client,
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
        flow = self.client_flow(inbound_id)
        if flow:
            payload["flow"] = flow
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

    def client_flow(self, inbound_id: int = None) -> str:
        """The XTLS flow this inbound's clients need, or "" when it takes none.

        VLESS over Reality (or TLS) on raw TCP is the one combination that
        wants xtls-rprx-vision; setting it anywhere else breaks the client.
        """
        if self._flow is None:
            self._flow = ""
            try:
                inbound = self.get_inbound(inbound_id)
                stream = inbound.get("streamSettings")
                stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
                network = stream.get("network", "tcp")
                security = stream.get("security", "")
                if (inbound.get("protocol") == "vless"
                        and network in ("tcp", "raw")
                        and security in ("reality", "tls")):
                    self._flow = "xtls-rprx-vision"
            except (XUIError, ValueError):
                pass
        return self._flow

    def _settings(self) -> dict:
        if self._panel_settings is None:
            try:
                self._panel_settings = self._request("POST", "/panel/api/setting/all") or {}
            except XUIError:
                self._panel_settings = {}
        return self._panel_settings

    def get_sub_url(self, email: str) -> str:
        """Subscription URL for a client, or "" when the panel has none enabled.

        The subscription server is configured independently of the panel (own
        port, path and optional domain), so the address is read from the
        panel's settings rather than derived from the API URL.
        """
        settings = self._settings()
        if not settings:
            return ""
        enabled = settings.get("subEnable", settings.get("subenable"))
        if enabled in (False, "false", 0, "0"):
            return ""

        traffic = self.get_client_traffic(email) or {}
        sub_id = traffic.get("subId") or traffic.get("subid")
        if not sub_id:
            return ""

        explicit = settings.get("subURI") or settings.get("subUri") or settings.get("suburi")
        if explicit:
            return explicit.rstrip("/") + "/" + sub_id

        host = (settings.get("subDomain") or settings.get("subdomain")
                or config.XUI_PUBLIC_HOST
                or self.base_url.split("//", 1)[-1].split(":")[0].split("/")[0])
        port = settings.get("subPort") or settings.get("subport")
        path = settings.get("subPath") or settings.get("subpath") or "/sub/"
        scheme = "https" if (settings.get("subKeyFile") or settings.get("subCertFile")) else "http"

        netloc = f"{host}:{port}" if port and str(port) not in ("80", "443") else host
        return f"{scheme}://{netloc}{path if path.startswith('/') else '/' + path}{sub_id}"

    def set_client_enabled(self, email: str, enabled: bool):
        """Block/unblock a client without touching its quota or expiry."""
        t = self.get_client_traffic(email)
        if not t:
            raise XUIError(f"client {email} not found")
        body = {"email": email, "totalGB": t.get("total", 0), "expiryTime": t.get("expiryTime", 0), "enable": enabled}
        flow = self.client_flow()
        if flow:
            body["flow"] = flow
        self._request("POST", f"/panel/api/clients/update/{email}", json=body)

    def get_online_emails(self) -> set[str]:
        """Best-effort live online-client list from the panel's own onlines
        endpoint. Panel versions differ in whether/how they expose this, so
        any failure just means no account shows as online — never an error
        surfaced to whoever's checking their status."""
        try:
            obj = self._request("POST", "/panel/api/inbounds/onlines")
        except XUIError:
            return set()
        if not obj:
            return set()
        emails = set()
        for item in obj:
            if isinstance(item, str):
                emails.add(item)
            elif isinstance(item, dict) and item.get("email"):
                emails.add(item["email"])
        return emails

    def build_vless_link(self, client_uuid: str, email: str, remark: str = "",
                          inbound_id: int = None) -> str:
        """Return the client's connection URL as the panel renders it.

        The panel knows the inbound's advertised hosts, Reality keys and
        protocol, so its own link is authoritative — including for inbounds
        that are not Reality at all. One exception: for a WS+TLS inbound
        fronted by a CDN (Cloudflare), the panel still renders the raw
        origin IP as the address, which defeats the whole point of the
        CDN — the client has to connect to the *hostname* so DNS routes it
        through the CDN's edge instead of straight at a blockable IP. When
        the configured inbound is such a setup, the address is swapped for
        its own wsSettings Host header.
        """
        links = self._request("GET", f"/panel/api/clients/links/{email}") or []
        if not links:
            raise XUIError(f"panel returned no connection link for {email}")
        link = links[0]
        if remark:
            link = link.split("#", 1)[0] + "#" + remark

        try:
            inbound = self.get_inbound(inbound_id)
            stream = inbound.get("streamSettings")
            stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
            if stream.get("network") == "ws":
                host = (stream.get("wsSettings") or {}).get("headers", {}).get("Host")
                if host:
                    link = re.sub(r"@[^:/?#]+(:\d+)", lambda m: f"@{host}{m.group(1)}", link, count=1)
        except (XUIError, ValueError):
            pass
        return link
