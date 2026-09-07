#!/usr/bin/env python3
"""One-shot: post ECOM2RETRO-4348 draft to a Mattermost channel. No secrets in argv."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("/Users/dsk/projects/letech/mattermost-mcp")
sys.path.insert(0, str(ROOT))

from mattermost_mcp.config import Settings, load_dotenv  # noqa: E402
from mattermost_mcp.mattermost_client import MattermostClient  # noqa: E402
from mattermost_mcp.session_store import load_session  # noqa: E402

CHANNEL_ID = "9d39wddqcfb65dgbuccgncu7yr"
MESSAGE_FILE = ROOT / ".scheduled" / "4348.md"
LOG_FILE = ROOT / ".scheduled" / "4348.send.log"


def main() -> int:
    load_dotenv()
    settings = Settings.from_env()
    stored = None if settings.auth.token else load_session(settings.session_file)
    client = MattermostClient(
        base_url=settings.base_url,
        token=settings.auth.token,
        session_token=settings.auth.session_token or (stored.session_token if stored else None),
        csrf_token=settings.auth.csrf_token or (stored.csrf_token if stored else None),
        user_id=settings.auth.user_id or (stored.user_id if stored else None),
        login_id=settings.auth.login_id,
        password=settings.auth.password,
        mfa_token=settings.auth.mfa_token,
        timeout_seconds=settings.timeout_seconds,
        verify_ssl=settings.verify_ssl,
        lazy_session=True,
    )
    message = MESSAGE_FILE.read_text(encoding="utf-8")
    post = client.create_post(channel_id=CHANNEL_ID, message=message)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(
        f"ok id={post.get('id')} create_at={post.get('create_at')}\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.write_text(f"fail {type(exc).__name__}: {exc}\n", encoding="utf-8")
        raise
