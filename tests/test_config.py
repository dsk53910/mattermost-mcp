from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mattermost_mcp.config import Settings


class SettingsTests(unittest.TestCase):
    def test_auto_mode_prefers_bearer_token(self) -> None:
        env = {
            "MATTERMOST_BASE_URL": "https://mattermost.example.com",
            "MATTERMOST_TOKEN": "bearer-token",
            "MATTERMOST_MMAUTHTOKEN": "session-cookie",
            "MATTERMOST_MMCSRF": "csrf-cookie",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.auth.mode, "token")
        self.assertEqual(settings.auth.token, "bearer-token")

    def test_browser_mode_reads_session_cookies(self) -> None:
        env = {
            "MATTERMOST_BASE_URL": "https://mattermost.example.com",
            "MATTERMOST_AUTH_MODE": "browser",
            "MATTERMOST_MMAUTHTOKEN": "session-cookie",
            "MATTERMOST_MMCSRF": "csrf-cookie",
            "MATTERMOST_MMUSERID": "user-id",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.auth.mode, "browser")
        self.assertEqual(settings.auth.session_token, "session-cookie")
        self.assertEqual(settings.auth.csrf_token, "csrf-cookie")
        self.assertEqual(settings.auth.user_id, "user-id")

    def test_login_mode_reads_credentials(self) -> None:
        env = {
            "MATTERMOST_BASE_URL": "https://mattermost.example.com",
            "MATTERMOST_AUTH_MODE": "login",
            "MATTERMOST_LOGIN_ID": "bot@example.com",
            "MATTERMOST_PASSWORD": "secret",
            "MATTERMOST_MFA_TOKEN": "123456",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.auth.mode, "login")
        self.assertEqual(settings.auth.login_id, "bot@example.com")
        self.assertEqual(settings.auth.password, "secret")
        self.assertEqual(settings.auth.mfa_token, "123456")

    def test_playwright_mode_reads_sso_configuration(self) -> None:
        env = {
            "MATTERMOST_BASE_URL": "https://mattermost.example.com",
            "MATTERMOST_AUTH_MODE": "playwright",
            "MATTERMOST_SSO_AUTH_URL": "https://sso.example.com/auth",
            "MATTERMOST_LOGIN_ID": "bot@example.com",
            "MATTERMOST_PASSWORD": "secret",
            "MATTERMOST_PLAYWRIGHT_HEADLESS": "false",
            "MATTERMOST_PLAYWRIGHT_INTERACTIVE": "true",
            "MATTERMOST_PLAYWRIGHT_BROWSER": "firefox",
            "MATTERMOST_PLAYWRIGHT_TIMEOUT_MS": "45000",
            "MATTERMOST_PLAYWRIGHT_SUCCESS_SELECTOR": ".channel-view",
            "MATTERMOST_AUTH_TEST_ONLY": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.auth.mode, "playwright")
        self.assertEqual(settings.auth.sso_auth_url, "https://sso.example.com/auth")
        self.assertEqual(settings.auth.login_id, "bot@example.com")
        self.assertEqual(settings.auth.password, "secret")
        self.assertFalse(settings.auth.playwright_headless)
        self.assertTrue(settings.auth.playwright_interactive)
        self.assertEqual(settings.auth.playwright_browser, "firefox")
        self.assertEqual(settings.auth.playwright_timeout_ms, 45000)
        self.assertEqual(settings.auth.playwright_success_selector, ".channel-view")
        self.assertTrue(settings.auth_test_only)
