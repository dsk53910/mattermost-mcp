from __future__ import annotations

import unittest

from mattermost_mcp.errors import MattermostConnectionError
from mattermost_mcp.playwright_auth import BrowserSession, extract_mattermost_session


class PlaywrightAuthTests(unittest.TestCase):
    def test_extract_mattermost_session(self) -> None:
        session = extract_mattermost_session(
            [
                {"name": "MMAUTHTOKEN", "value": "session-cookie"},
                {"name": "MMCSRF", "value": "csrf-cookie"},
                {"name": "MMUSERID", "value": "user-id"},
            ]
        )

        self.assertEqual(
            session,
            BrowserSession(
                session_token="session-cookie",
                csrf_token="csrf-cookie",
                user_id="user-id",
            ),
        )

    def test_extract_mattermost_session_requires_main_cookies(self) -> None:
        with self.assertRaises(MattermostConnectionError):
            extract_mattermost_session(
                [
                    {"name": "MMUSERID", "value": "user-id"},
                ]
            )
