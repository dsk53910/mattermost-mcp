from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from mattermost_mcp.playwright_auth import BrowserSession
from mattermost_mcp.session_store import load_session, save_session


class SessionStoreTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".mm-session"
            save_session(
                path,
                BrowserSession(
                    session_token="session-cookie",
                    csrf_token="csrf-cookie",
                    user_id="user-id",
                ),
            )

            loaded = load_session(path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.session_token, "session-cookie")
            self.assertEqual(loaded.csrf_token, "csrf-cookie")
            self.assertEqual(loaded.user_id, "user-id")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_load_missing_or_invalid_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing"
            self.assertIsNone(load_session(path))
            self.assertIsNone(load_session(None))
            bad = Path(tmp) / "bad"
            bad.write_text("{", encoding="utf-8")
            self.assertIsNone(load_session(bad))
