from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

from .errors import MattermostConnectionError


@dataclass(frozen=True)
class BrowserSession:
    session_token: str
    csrf_token: str
    user_id: str | None = None


def extract_mattermost_session(cookies: list[dict[str, Any]]) -> BrowserSession:
    cookie_map = {
        cookie.get("name"): cookie.get("value")
        for cookie in cookies
        if isinstance(cookie.get("name"), str) and isinstance(cookie.get("value"), str)
    }

    session_token = cookie_map.get("MMAUTHTOKEN")
    csrf_token = cookie_map.get("MMCSRF")
    user_id = cookie_map.get("MMUSERID")

    if not session_token or not csrf_token:
        raise MattermostConnectionError(
            "SSO login completed but Mattermost cookies MMAUTHTOKEN/MMCSRF were not found"
        )

    return BrowserSession(
        session_token=session_token,
        csrf_token=csrf_token,
        user_id=user_id,
    )


class MattermostPlaywrightAuthenticator:
    def __init__(
        self,
        *,
        base_url: str,
        auth_url: str,
        login_id: str,
        password: str,
        verify_ssl: bool = True,
        headless: bool = True,
        interactive: bool = False,
        browser_name: str = "chromium",
        timeout_ms: int = 300000,
        username_selector: str = 'input[name="username"]',
        password_selector: str = 'input[name="password"]',
        submit_selector: str = 'input[name="login"], button[type="submit"], #kc-login',
        post_login_url_prefix: str | None = None,
        success_selector: str | None = None,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.base_url = _normalize_web_base_url(base_url)
        self.auth_url = auth_url
        self.login_id = login_id
        self.password = password
        self.verify_ssl = verify_ssl
        self.headless = headless
        self.interactive = interactive
        self.browser_name = browser_name
        self.timeout_ms = timeout_ms
        self.username_selector = username_selector
        self.password_selector = password_selector
        self.submit_selector = submit_selector
        self.post_login_url_prefix = post_login_url_prefix or self.base_url
        self.success_selector = success_selector
        self.playwright_factory = playwright_factory or _default_playwright_factory

    def login(self) -> BrowserSession:
        try:
            with self.playwright_factory() as playwright:
                launcher = getattr(playwright, self.browser_name, None)
                if launcher is None:
                    raise MattermostConnectionError(
                        f"Unsupported Playwright browser: {self.browser_name}"
                    )

                browser = launcher.launch(headless=self.headless)
                context = browser.new_context(ignore_https_errors=not self.verify_ssl)
                page = context.new_page()

                try:
                    page.goto(self.auth_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    if not self.interactive:
                        page.locator(self.username_selector).first.wait_for(
                            state="visible",
                            timeout=self.timeout_ms,
                        )
                        page.locator(self.username_selector).first.fill(self.login_id)
                        page.locator(self.password_selector).first.fill(self.password)
                        page.locator(self.submit_selector).first.click()
                    else:
                        print(
                            "Playwright SSO: browser opened, waiting for manual login and final redirect to Mattermost...",
                            file=sys.stderr,
                            flush=True,
                        )

                    page.wait_for_url(
                        re.compile(f"^{re.escape(self.post_login_url_prefix)}"),
                        timeout=self.timeout_ms,
                    )

                    print(
                        f"Playwright SSO: reached {page.url}, waiting for Mattermost session cookies...",
                        file=sys.stderr,
                        flush=True,
                    )

                    return self._wait_for_session(context=context, page=page)
                finally:
                    browser.close()
        except MattermostConnectionError:
            raise
        except Exception as exc:
            raise MattermostConnectionError(f"Playwright SSO login failed: {exc}") from exc

    def _wait_for_session(self, *, context: Any, page: Any) -> BrowserSession:
        deadline = time.monotonic() + (self.timeout_ms / 1000)
        cookie_error: MattermostConnectionError | None = None
        success_selector_checked = False

        while time.monotonic() < deadline:
            cookies = context.cookies([self.base_url])
            try:
                return extract_mattermost_session(cookies)
            except MattermostConnectionError as exc:
                cookie_error = exc

            if self.success_selector and not success_selector_checked:
                try:
                    page.locator(self.success_selector).first.wait_for(
                        state="visible",
                        timeout=1000,
                    )
                    success_selector_checked = True
                except Exception:
                    pass

            time.sleep(1)

        cookie_names = ", ".join(
            sorted(
                cookie.get("name")
                for cookie in context.cookies([self.base_url])
                if isinstance(cookie.get("name"), str)
            )
        ) or "<none>"

        current_url = getattr(page, "url", "<unknown>")
        if cookie_error is None:
            cookie_error = MattermostConnectionError(
                "SSO login completed but Mattermost cookies MMAUTHTOKEN/MMCSRF were not found"
            )

        raise MattermostConnectionError(
            f"{cookie_error}. Current URL: {current_url}. Visible Mattermost cookies: {cookie_names}"
        )


def _normalize_web_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/api/v4"):
        normalized = normalized[: -len("/api/v4")]
    return normalized


def _default_playwright_factory():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise MattermostConnectionError(
            "Playwright is not installed. Run `uv sync` and `uv run playwright install chromium`."
        ) from exc

    return sync_playwright()
