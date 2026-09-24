"""Low-level HTTP client: authentication, retries and raw API calls."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import requests
import urllib3

from .exceptions import (ReolinkAuthError, ReolinkCommandError,
                         ReolinkConnectionError)

# Cameras ship self-signed certificates.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ReolinkHTTP:
    """Handles login, token refresh and API calls against ``/api.cgi``."""

    THROTTLE = 0.25     # s between requests (prevents camera overload)
    SET_SETTLE = 1.5    # s after a Set command (let the camera apply it)

    def __init__(self, host: str, username: str, password: str,
                 port: int = 443, scheme: str = "https", timeout: int = 15):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.scheme = scheme
        self.timeout = timeout
        self.base = f"{scheme}://{host}:{port}/api.cgi"
        self.token = ""

    def login(self) -> str:
        body = [{"cmd": "Login", "action": 0, "param": {
            "User": {"userName": self.username, "password": self.password}
        }}]
        for attempt in range(4):
            try:
                r = requests.post(f"{self.base}?cmd=Login", json=body,
                                  verify=False, timeout=self.timeout)
                if not r.text.strip():
                    time.sleep(5 * (attempt + 1))
                    continue
                data = r.json()
                first = data[0] if isinstance(data, list) and data else {}
                token = first.get("value", {}).get("Token", {}).get("name", "")
                if token:
                    self.token = token
                    return token
                raise ReolinkAuthError(f"Login failed: {json.dumps(data)}")
            except ReolinkAuthError:
                raise
            except Exception as exc:
                if attempt == 3:
                    raise ReolinkConnectionError(f"Login error: {exc}") from exc
                time.sleep(5 * (attempt + 1))
        raise ReolinkAuthError("Login failed after 4 attempts")

    def logout(self) -> None:
        if not self.token:
            return
        try:
            requests.post(
                f"{self.base}?cmd=Logout&token={self.token}",
                json=[{"cmd": "Logout", "action": 0, "param": {}}],
                verify=False, timeout=5,
            )
        except Exception:
            pass
        self.token = ""

    def _refresh(self) -> None:
        self.logout()
        time.sleep(3)
        self.login()

    def call(self, cmd: str, param: Optional[dict] = None,
             action: int = 0, _retry: int = 0) -> dict:
        """Call the camera API and return the first response object."""
        time.sleep(self.THROTTLE)
        body = [{"cmd": cmd, "action": action, "param": param or {}}]
        url = f"{self.base}?cmd={cmd}&token={self.token}"
        try:
            r = requests.post(url, json=body, verify=False, timeout=self.timeout)
        except requests.RequestException as exc:
            if _retry < 2:
                self._refresh()
                return self.call(cmd, param, action, _retry + 1)
            raise ReolinkConnectionError(str(exc)) from exc

        if not r.text.strip():
            if _retry == 0:
                time.sleep(3)
                return self.call(cmd, param, action, 1)
            if _retry == 1:
                self._refresh()
                return self.call(cmd, param, action, 2)
            raise ReolinkCommandError(f"{cmd}: empty response")

        data = r.json()
        resp = data[0] if isinstance(data, list) and data else data

        if resp.get("code", -1) != 0:
            err = resp.get("error", {})
            if isinstance(err, dict):
                if err.get("rspCode") == -6 or "login" in str(err).lower():
                    if _retry < 2:
                        self._refresh()
                        return self.call(cmd, param, action, _retry + 1)
            raise ReolinkCommandError(f"{cmd} failed: {err or resp}")

        return resp

    def get(self, cmd: str, param: Optional[dict] = None) -> dict:
        return self.call(cmd, param, action=0)

    def set(self, cmd: str, param: dict, settle: bool = True) -> dict:
        resp = self.call(cmd, param, action=0)
        if settle:
            time.sleep(self.SET_SETTLE)
        return resp

    @staticmethod
    def value(resp: dict, key: str) -> Any:
        return resp.get("value", {}).get(key)
