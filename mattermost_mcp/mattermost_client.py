from __future__ import annotations

import json
import ssl
from http.cookies import SimpleCookie
from typing import Any, Callable
from urllib import error, parse, request

from .errors import MattermostApiError, MattermostConnectionError
from .playwright_auth import BrowserSession


class MattermostClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        session_token: str | None = None,
        csrf_token: str | None = None,
        user_id: str | None = None,
        login_id: str | None = None,
        password: str | None = None,
        mfa_token: str | None = None,
        session_provider: Callable[[], BrowserSession] | None = None,
        timeout_seconds: float = 15.0,
        verify_ssl: bool = True,
        lazy_session: bool = True,
        urlopen=request.urlopen,
    ) -> None:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/api/v4"):
            self.api_base = normalized
        else:
            self.api_base = f"{normalized}/api/v4"

        self.timeout_seconds = timeout_seconds
        self.urlopen = urlopen
        self.base_headers = {
            "Accept": "application/json",
        }
        self.auth_headers: dict[str, str] = {}
        self.login_id = login_id
        self.password = password
        self.mfa_token = mfa_token
        self.session_provider = session_provider
        self.can_relogin = bool(login_id and password) or session_provider is not None
        self.ssl_context = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()

        if token:
            self.auth_headers["Authorization"] = f"Bearer {token}"
        elif session_token and csrf_token:
            self._apply_browser_auth(
                session_token=session_token,
                csrf_token=csrf_token,
                user_id=user_id,
            )
        elif self.session_provider is not None:
            if not lazy_session:
                self._refresh_from_session_provider()
        elif self.can_relogin:
            self._login()
        else:
            raise ValueError("Provide token, session_token + csrf_token, login_id + password, or session_provider")

    def get_me(self) -> dict[str, Any]:
        return self._request("GET", "/users/me")

    def list_teams(self) -> list[dict[str, Any]]:
        return self._request("GET", "/users/me/teams")

    def list_channels(self, team_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/users/me/teams/{team_id}/channels")

    def get_channel_by_name(self, team_id: str, channel_name: str) -> dict[str, Any]:
        quoted_name = parse.quote(channel_name, safe="")
        return self._request("GET", f"/teams/{team_id}/channels/name/{quoted_name}")

    def get_channel_posts(
        self,
        channel_id: str,
        page: int = 0,
        per_page: int = 60,
        since: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
        }
        if since is not None:
            params["since"] = since
        return self._request("GET", f"/channels/{channel_id}/posts", params=params)

    def create_post(
        self,
        channel_id: str,
        message: str,
        root_id: str | None = None,
        file_ids: list[str] | None = None,
        props: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "channel_id": channel_id,
            "message": message,
        }
        if root_id:
            payload["root_id"] = root_id
        if file_ids:
            payload["file_ids"] = file_ids
        if props:
            payload["props"] = props
        return self._request("POST", "/posts", payload=payload)

    def search_posts(
        self,
        team_id: str,
        terms: str,
        is_or_search: bool = False,
        page: int = 0,
        per_page: int = 60,
    ) -> dict[str, Any]:
        payload = {
            "terms": terms,
            "is_or_search": is_or_search,
            "page": page,
            "per_page": per_page,
        }
        return self._request("POST", f"/teams/{team_id}/posts/search", payload=payload)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        allow_relogin: bool = True,
    ) -> Any:
        url = f"{self.api_base}{path}"
        if params:
            query = parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"

        self._ensure_auth()
        body = None
        headers = dict(self.base_headers)
        headers.update(self.auth_headers)
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url=url, data=body, headers=headers, method=method)

        try:
            with self.urlopen(req, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                raw = response.read().decode("utf-8")
                return self._parse_body(raw)
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            details = self._parse_body(raw)
            if allow_relogin and self.can_relogin and exc.code in {401, 403}:
                self._reauthorize()
                return self._request(method, path, params=params, payload=payload, allow_relogin=False)
            message = self._extract_error_message(details) or exc.reason or "Mattermost API request failed"
            raise MattermostApiError(exc.code, message, details) from exc
        except error.URLError as exc:
            raise MattermostConnectionError(str(exc.reason)) from exc

    def _ensure_auth(self) -> None:
        if self.auth_headers:
            return
        if self.session_provider is not None:
            self._refresh_from_session_provider()
            return
        if self.can_relogin:
            self._login()
            return
        raise MattermostConnectionError("Mattermost client has no credentials")

    def _reauthorize(self) -> None:
        if self.session_provider is not None:
            self._refresh_from_session_provider()
        else:
            self._login()

    def _login(self) -> None:
        login_payload: dict[str, Any] = {
            "login_id": self.login_id,
            "password": self.password,
        }
        if self.mfa_token:
            login_payload["token"] = self.mfa_token

        req = request.Request(
            url=f"{self.api_base}/users/login",
            data=json.dumps(login_payload).encode("utf-8"),
            headers={
                **self.base_headers,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self.urlopen(req, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                raw = response.read().decode("utf-8")
                user = self._parse_body(raw)
                self._update_auth_from_login_response(response.headers, user)
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            details = self._parse_body(raw)
            message = self._extract_error_message(details) or exc.reason or "Mattermost login failed"
            raise MattermostApiError(exc.code, message, details) from exc
        except error.URLError as exc:
            raise MattermostConnectionError(str(exc.reason)) from exc

    def _update_auth_from_login_response(self, headers: Any, user: Any) -> None:
        auth_headers: dict[str, str] = {}

        token = headers.get("Token")
        if isinstance(token, str) and token.strip():
            auth_headers["Authorization"] = f"Bearer {token.strip()}"

        cookies = self._extract_cookies(headers)
        cookie_header = self._compose_cookie_header(cookies)
        if cookie_header:
            auth_headers["Cookie"] = cookie_header

        csrf_token = cookies.get("MMCSRF")
        if csrf_token:
            auth_headers["X-CSRF-Token"] = csrf_token
            auth_headers["X-Requested-With"] = "XMLHttpRequest"

        if "MMUSERID" not in cookies and isinstance(user, dict):
            user_id = user.get("id")
            if isinstance(user_id, str) and user_id.strip() and "Cookie" in auth_headers:
                cookies["MMUSERID"] = user_id
                auth_headers["Cookie"] = self._compose_cookie_header(cookies)

        if not auth_headers:
            raise MattermostConnectionError("Mattermost login succeeded but returned no usable auth headers")

        self.auth_headers = auth_headers

    def _refresh_from_session_provider(self) -> None:
        if self.session_provider is None:
            raise MattermostConnectionError("Session provider is not configured")

        session = self.session_provider()
        self._apply_browser_auth(
            session_token=session.session_token,
            csrf_token=session.csrf_token,
            user_id=session.user_id,
        )

    @staticmethod
    def _extract_cookies(headers: Any) -> dict[str, str]:
        raw_cookies = []
        if hasattr(headers, "get_all"):
            raw_cookies.extend(headers.get_all("Set-Cookie") or [])
        elif isinstance(headers, dict):
            set_cookie = headers.get("Set-Cookie")
            if isinstance(set_cookie, list):
                raw_cookies.extend(set_cookie)
            elif isinstance(set_cookie, str):
                raw_cookies.append(set_cookie)

        cookies: dict[str, str] = {}
        for raw_cookie in raw_cookies:
            parsed = SimpleCookie()
            parsed.load(raw_cookie)
            for morsel in parsed.values():
                cookies[morsel.key] = morsel.value
        return cookies

    @staticmethod
    def _compose_cookie_header(cookies: dict[str, str]) -> str:
        if not cookies:
            return ""
        ordered_keys = ["MMAUTHTOKEN", "MMCSRF", "MMUSERID"]
        parts = [f"{key}={cookies[key]}" for key in ordered_keys if key in cookies]
        parts.extend(f"{key}={value}" for key, value in cookies.items() if key not in set(ordered_keys))
        return "; ".join(parts)

    @staticmethod
    def _parse_body(raw: str) -> Any:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}

    @staticmethod
    def _extract_error_message(details: Any) -> str | None:
        if isinstance(details, dict):
            for key in ("message", "detailed_error", "error"):
                value = details.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return None

    @staticmethod
    def _build_cookie_header(
        session_token: str,
        csrf_token: str,
        user_id: str | None = None,
    ) -> str:
        parts = [
            f"MMAUTHTOKEN={session_token}",
            f"MMCSRF={csrf_token}",
        ]
        if user_id:
            parts.append(f"MMUSERID={user_id}")
        return "; ".join(parts)

    def _apply_browser_auth(
        self,
        session_token: str,
        csrf_token: str,
        user_id: str | None = None,
    ) -> None:
        self.auth_headers["Cookie"] = self._build_cookie_header(
            session_token=session_token,
            csrf_token=csrf_token,
            user_id=user_id,
        )
        self.auth_headers["X-CSRF-Token"] = csrf_token
        self.auth_headers["X-Requested-With"] = "XMLHttpRequest"
