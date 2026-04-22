from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .mattermost_client import MattermostClient
from .playwright_auth import MattermostPlaywrightAuthenticator
from .server import MattermostMcpServer


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        settings = Settings.from_env()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    session_provider = None
    if settings.auth.mode == "playwright":
        authenticator = MattermostPlaywrightAuthenticator(
            base_url=settings.base_url,
            auth_url=settings.auth.sso_auth_url,
            login_id=settings.auth.login_id,
            password=settings.auth.password,
            verify_ssl=settings.verify_ssl,
            headless=settings.auth.playwright_headless,
            interactive=settings.auth.playwright_interactive,
            browser_name=settings.auth.playwright_browser,
            timeout_ms=settings.auth.playwright_timeout_ms,
            username_selector=settings.auth.playwright_username_selector,
            password_selector=settings.auth.playwright_password_selector,
            submit_selector=settings.auth.playwright_submit_selector,
            post_login_url_prefix=settings.auth.playwright_post_login_url_prefix,
            success_selector=settings.auth.playwright_success_selector,
        )
        session_provider = authenticator.login

    client = MattermostClient(
        base_url=settings.base_url,
        token=settings.auth.token,
        session_token=settings.auth.session_token,
        csrf_token=settings.auth.csrf_token,
        user_id=settings.auth.user_id,
        login_id=settings.auth.login_id,
        password=settings.auth.password,
        mfa_token=settings.auth.mfa_token,
        session_provider=session_provider,
        timeout_seconds=settings.timeout_seconds,
        verify_ssl=settings.verify_ssl,
    )

    if args.command == "read-channel":
        return _run_read_channel(
            client=client,
            channel_id=args.channel_id,
            per_page=args.per_page,
            max_pages=args.max_pages,
            as_json=args.json,
        )

    if args.command == "send-message":
        return _run_send_message(
            client=client,
            channel_id=args.channel_id,
            message=args.message,
            root_id=args.root_id,
            as_json=args.json,
        )

    if args.command == "auth-check" or settings.auth_test_only:
        return _run_auth_check(client)

    if sys.stdin.isatty() and sys.stdout.isatty():
        print(
            "Refusing to start MCP stdio server on an interactive terminal. "
            "Use `python -m mattermost_mcp auth-check`, `python -m mattermost_mcp read-channel --channel-id ...`, "
            "`python -m mattermost_mcp send-message --channel-id ... --message ...`, "
            "or run this process from an MCP client.",
            file=sys.stderr,
        )
        return 2

    server = MattermostMcpServer(client)
    server.serve_forever()
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m mattermost_mcp",
        description="Mattermost MCP server and CLI utilities",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("auth-check", help="authenticate and print the current Mattermost user")

    read_channel = subparsers.add_parser(
        "read-channel",
        help="read posts from a Mattermost channel through the Web API",
    )
    read_channel.add_argument("--channel-id", required=True, help="Mattermost channel ID")
    read_channel.add_argument("--per-page", type=int, default=200, help="posts page size, default: 200")
    read_channel.add_argument("--max-pages", type=int, default=20, help="maximum pages to fetch, default: 20")
    read_channel.add_argument("--json", action="store_true", help="print raw collected posts as JSON")

    send_message = subparsers.add_parser(
        "send-message",
        help="send a post to a Mattermost channel through the Web API",
    )
    send_message.add_argument("--channel-id", required=True, help="Mattermost channel ID")
    send_message.add_argument("--message", required=True, help="message text to send")
    send_message.add_argument("--root-id", help="optional root post ID for thread reply")
    send_message.add_argument("--json", action="store_true", help="print raw created post JSON")

    return parser.parse_args(argv)


def _run_auth_check(client: MattermostClient) -> int:
    me = client.get_me()
    user_id = me.get("id", "<unknown>")
    username = me.get("username", "<unknown>")
    print(
        f"Authentication succeeded: user_id={user_id} username={username}",
        file=sys.stderr,
    )
    return 0


def _run_read_channel(
    *,
    client: MattermostClient,
    channel_id: str,
    per_page: int,
    max_pages: int,
    as_json: bool,
) -> int:
    pages = []
    for page in range(max_pages):
        response = client.get_channel_posts(channel_id=channel_id, page=page, per_page=per_page)
        order = response.get("order") or []
        if not order:
            break
        pages.append(response)
        if len(order) < per_page:
            break

    posts = _flatten_posts(pages)

    if as_json:
        print(json.dumps(posts, ensure_ascii=False, indent=2))
        return 0

    if not posts:
        print("No posts found.", file=sys.stderr)
        return 0

    for post in posts:
        created_at = _format_timestamp(post.get("create_at"))
        user_id = post.get("user_id", "<unknown>")
        post_id = post.get("id", "<unknown>")
        root_id = post.get("root_id") or "-"
        message = (post.get("message") or "").strip()
        print(f"[{created_at}] user={user_id} post={post_id} root={root_id}")
        if message:
            print(message)
        else:
            print("<empty>")
        print()

    print(f"Total posts: {len(posts)}", file=sys.stderr)
    return 0


def _flatten_posts(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collected: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for page in pages:
        posts = page.get("posts") or {}
        page_order = page.get("order") or []
        for post_id in page_order:
            post = posts.get(post_id)
            if isinstance(post, dict) and post_id not in collected:
                collected[post_id] = post
                order.append(post_id)

    # Mattermost returns newest-first order; print oldest-first for reading.
    return [collected[post_id] for post_id in reversed(order)]


def _format_timestamp(value: Any) -> str:
    if not isinstance(value, int) or value <= 0:
        return "<unknown-time>"
    dt = datetime.fromtimestamp(value / 1000, tz=UTC)
    return dt.isoformat()


def _run_send_message(
    *,
    client: MattermostClient,
    channel_id: str,
    message: str,
    root_id: str | None,
    as_json: bool,
) -> int:
    post = client.create_post(
        channel_id=channel_id,
        message=message,
        root_id=root_id,
    )

    if as_json:
        print(json.dumps(post, ensure_ascii=False, indent=2))
        return 0

    created_at = _format_timestamp(post.get("create_at"))
    post_id = post.get("id", "<unknown>")
    user_id = post.get("user_id", "<unknown>")
    print(f"Sent post: id={post_id} user={user_id} created_at={created_at}", file=sys.stderr)
    print(post.get("message") or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
