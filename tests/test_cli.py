from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from mattermost_mcp.__main__ import (
    _flatten_posts,
    _format_timestamp,
    _run_auth_check,
    _run_read_channel,
    _run_send_message,
)


class FakeClient:
    def get_me(self):
        return {"id": "user-1", "username": "alice"}

    def get_channel_posts(self, channel_id: str, page: int, per_page: int):
        if page > 0:
            return {"order": [], "posts": {}}
        return {
            "order": ["post-2", "post-1"],
            "posts": {
                "post-1": {
                    "id": "post-1",
                    "user_id": "user-1",
                    "create_at": 1710000000000,
                    "message": "first",
                    "root_id": "",
                },
                "post-2": {
                    "id": "post-2",
                    "user_id": "user-2",
                    "create_at": 1710000001000,
                    "message": "second",
                    "root_id": "",
                },
            },
        }

    def create_post(self, channel_id: str, message: str, root_id=None, file_ids=None, props=None):
        return {
            "id": "post-3",
            "user_id": "user-1",
            "create_at": 1710000002000,
            "message": message,
            "channel_id": channel_id,
            "root_id": root_id or "",
        }


class CliHelpersTests(unittest.TestCase):
    def test_run_auth_check(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = _run_auth_check(FakeClient())
        self.assertEqual(code, 0)
        self.assertIn("Authentication succeeded", stderr.getvalue())

    def test_run_read_channel_prints_oldest_first(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = _run_read_channel(
                client=FakeClient(),
                channel_id="channel-1",
                per_page=200,
                max_pages=5,
                as_json=False,
            )

        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertLess(rendered.find("first"), rendered.find("second"))
        self.assertIn("Total posts: 2", stderr.getvalue())

    def test_flatten_posts_deduplicates_and_reverses(self) -> None:
        posts = _flatten_posts(
            [
                {
                    "order": ["post-2", "post-1"],
                    "posts": {
                        "post-1": {"id": "post-1"},
                        "post-2": {"id": "post-2"},
                    },
                }
            ]
        )
        self.assertEqual([post["id"] for post in posts], ["post-1", "post-2"])

    def test_format_timestamp(self) -> None:
        self.assertEqual(_format_timestamp(0), "<unknown-time>")
        self.assertIn("T", _format_timestamp(1710000000000))

    def test_run_send_message(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = _run_send_message(
                client=FakeClient(),
                channel_id="channel-1",
                message="hello world",
                root_id=None,
                as_json=False,
            )

        self.assertEqual(code, 0)
        self.assertIn("hello world", stdout.getvalue())
        self.assertIn("Sent post:", stderr.getvalue())
