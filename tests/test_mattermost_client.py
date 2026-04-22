from __future__ import annotations

import io
import json
import unittest
from email.message import Message
from urllib.error import HTTPError

from mattermost_mcp.errors import MattermostApiError
from mattermost_mcp.mattermost_client import MattermostClient
from mattermost_mcp.playwright_auth import BrowserSession


class DummyResponse:
    def __init__(self, payload: object, headers: dict[str, str | list[str]] | None = None) -> None:
        self.payload = payload
        self.headers = Message()
        for name, value in (headers or {}).items():
            if isinstance(value, list):
                for item in value:
                    self.headers.add_header(name, item)
            else:
                self.headers.add_header(name, value)

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class MattermostClientTests(unittest.TestCase):
    def test_get_me_uses_bearer_token_and_api_prefix(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout, context):
            captured["url"] = req.full_url
            captured["auth"] = req.headers["Authorization"]
            captured["timeout"] = timeout
            captured["context"] = context
            return DummyResponse({"id": "user-1"})

        client = MattermostClient(
            base_url="https://mattermost.example.com",
            token="secret-token",
            timeout_seconds=12,
            urlopen=fake_urlopen,
        )

        response = client.get_me()

        self.assertEqual(response["id"], "user-1")
        self.assertEqual(captured["url"], "https://mattermost.example.com/api/v4/users/me")
        self.assertEqual(captured["auth"], "Bearer secret-token")
        self.assertEqual(captured["timeout"], 12)

    def test_create_post_serializes_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout, context):
            captured["method"] = req.get_method()
            captured["body"] = req.data.decode("utf-8")
            return DummyResponse({"id": "post-1"})

        client = MattermostClient(
            base_url="https://mattermost.example.com/api/v4",
            token="secret-token",
            urlopen=fake_urlopen,
        )

        response = client.create_post(
            channel_id="channel-1",
            message="hello",
            file_ids=["file-1"],
        )

        self.assertEqual(response["id"], "post-1")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            json.loads(captured["body"]),
            {
                "channel_id": "channel-1",
                "message": "hello",
                "file_ids": ["file-1"],
            },
        )

    def test_browser_session_auth_sets_cookie_and_csrf_headers(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout, context):
            captured["cookie"] = req.headers["Cookie"]
            captured["csrf"] = req.headers["X-csrf-token"]
            captured["requested_with"] = req.headers["X-requested-with"]
            return DummyResponse({"id": "user-1"})

        client = MattermostClient(
            base_url="https://mattermost.example.com",
            session_token="session-cookie",
            csrf_token="csrf-cookie",
            user_id="user-id",
            urlopen=fake_urlopen,
        )

        response = client.get_me()

        self.assertEqual(response["id"], "user-1")
        self.assertEqual(
            captured["cookie"],
            "MMAUTHTOKEN=session-cookie; MMCSRF=csrf-cookie; MMUSERID=user-id",
        )
        self.assertEqual(captured["csrf"], "csrf-cookie")
        self.assertEqual(captured["requested_with"], "XMLHttpRequest")

    def test_login_mode_logs_in_on_start_and_uses_received_tokens(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout, context):
            if req.full_url.endswith("/users/login"):
                captured["login_body"] = json.loads(req.data.decode("utf-8"))
                return DummyResponse(
                    {"id": "user-1"},
                    headers={
                        "Token": "fresh-token",
                        "Set-Cookie": [
                            "MMAUTHTOKEN=session-cookie; Path=/; HttpOnly",
                            "MMCSRF=csrf-cookie; Path=/",
                            "MMUSERID=user-1; Path=/",
                        ],
                    },
                )

            captured["auth"] = req.headers.get("Authorization")
            captured["cookie"] = req.headers.get("Cookie")
            captured["csrf"] = req.headers.get("X-csrf-token")
            return DummyResponse({"id": "user-1"})

        client = MattermostClient(
            base_url="https://mattermost.example.com",
            login_id="bot@example.com",
            password="secret",
            urlopen=fake_urlopen,
        )

        response = client.get_me()

        self.assertEqual(response["id"], "user-1")
        self.assertEqual(
            captured["login_body"],
            {
                "login_id": "bot@example.com",
                "password": "secret",
            },
        )
        self.assertEqual(captured["auth"], "Bearer fresh-token")
        self.assertEqual(
            captured["cookie"],
            "MMAUTHTOKEN=session-cookie; MMCSRF=csrf-cookie; MMUSERID=user-1",
        )
        self.assertEqual(captured["csrf"], "csrf-cookie")

    def test_login_mode_reauthenticates_after_unauthorized(self) -> None:
        state = {"login_calls": 0, "me_calls": 0}

        def fake_urlopen(req, timeout, context):
            if req.full_url.endswith("/users/login"):
                state["login_calls"] += 1
                token = f"token-{state['login_calls']}"
                return DummyResponse(
                    {"id": "user-1"},
                    headers={
                        "Token": token,
                        "Set-Cookie": [
                            f"MMAUTHTOKEN=session-{state['login_calls']}; Path=/; HttpOnly",
                            f"MMCSRF=csrf-{state['login_calls']}; Path=/",
                            "MMUSERID=user-1; Path=/",
                        ],
                    },
                )

            state["me_calls"] += 1
            if state["me_calls"] == 1:
                raise HTTPError(
                    url=req.full_url,
                    code=401,
                    msg="Unauthorized",
                    hdrs={},
                    fp=io.BytesIO(
                        json.dumps(
                            {
                                "message": "api.context.session_expired.app_error",
                                "detailed_error": "Session expired",
                            }
                        ).encode("utf-8")
                    ),
                )
            self.assertEqual(req.headers.get("Authorization"), "Bearer token-2")
            return DummyResponse({"id": "user-1"})

        client = MattermostClient(
            base_url="https://mattermost.example.com",
            login_id="bot@example.com",
            password="secret",
            urlopen=fake_urlopen,
        )

        response = client.get_me()

        self.assertEqual(response["id"], "user-1")
        self.assertEqual(state["login_calls"], 2)
        self.assertEqual(state["me_calls"], 2)

    def test_session_provider_uses_browser_cookies(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(req, timeout, context):
            captured["cookie"] = req.headers["Cookie"]
            captured["csrf"] = req.headers["X-csrf-token"]
            return DummyResponse({"id": "user-1"})

        client = MattermostClient(
            base_url="https://mattermost.example.com",
            session_provider=lambda: BrowserSession(
                session_token="session-cookie",
                csrf_token="csrf-cookie",
                user_id="user-id",
            ),
            urlopen=fake_urlopen,
        )

        response = client.get_me()

        self.assertEqual(response["id"], "user-1")
        self.assertEqual(
            captured["cookie"],
            "MMAUTHTOKEN=session-cookie; MMCSRF=csrf-cookie; MMUSERID=user-id",
        )
        self.assertEqual(captured["csrf"], "csrf-cookie")

    def test_session_provider_reauthenticates_after_unauthorized(self) -> None:
        state = {"provider_calls": 0, "me_calls": 0}

        def provider() -> BrowserSession:
            state["provider_calls"] += 1
            return BrowserSession(
                session_token=f"session-{state['provider_calls']}",
                csrf_token=f"csrf-{state['provider_calls']}",
                user_id="user-id",
            )

        def fake_urlopen(req, timeout, context):
            state["me_calls"] += 1
            if state["me_calls"] == 1:
                raise HTTPError(
                    url=req.full_url,
                    code=401,
                    msg="Unauthorized",
                    hdrs={},
                    fp=io.BytesIO(
                        json.dumps(
                            {
                                "message": "api.context.session_expired.app_error",
                                "detailed_error": "Session expired",
                            }
                        ).encode("utf-8")
                    ),
                )
            self.assertIn("MMAUTHTOKEN=session-2", req.headers.get("Cookie"))
            return DummyResponse({"id": "user-1"})

        client = MattermostClient(
            base_url="https://mattermost.example.com",
            session_provider=provider,
            urlopen=fake_urlopen,
        )

        response = client.get_me()

        self.assertEqual(response["id"], "user-1")
        self.assertEqual(state["provider_calls"], 2)
        self.assertEqual(state["me_calls"], 2)

    def test_http_error_is_converted_to_api_error(self) -> None:
        def fake_urlopen(req, timeout, context):
            raise HTTPError(
                url=req.full_url,
                code=403,
                msg="Forbidden",
                hdrs={},
                fp=io.BytesIO(
                    json.dumps(
                        {
                            "message": "api.context.invalid_token.app_error",
                            "detailed_error": "Token is invalid",
                        }
                    ).encode("utf-8")
                ),
            )

        client = MattermostClient(
            base_url="https://mattermost.example.com",
            token="bad-token",
            urlopen=fake_urlopen,
        )

        with self.assertRaises(MattermostApiError) as exc_info:
            client.get_me()

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(exc_info.exception.details["detailed_error"], "Token is invalid")
