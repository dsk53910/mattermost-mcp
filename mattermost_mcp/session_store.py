from __future__ import annotations

import json
import os
from pathlib import Path

from .playwright_auth import BrowserSession


def load_session(path: Path | None) -> BrowserSession | None:
    if path is None or not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    session_token = payload.get("mmauthtoken")
    csrf_token = payload.get("mmcsrf")
    user_id = payload.get("mmuserid")
    if not isinstance(session_token, str) or not session_token.strip():
        return None
    if not isinstance(csrf_token, str) or not csrf_token.strip():
        return None
    if user_id is not None and not isinstance(user_id, str):
        return None

    return BrowserSession(
        session_token=session_token.strip(),
        csrf_token=csrf_token.strip(),
        user_id=user_id.strip() if isinstance(user_id, str) and user_id.strip() else None,
    )


def save_session(path: Path | None, session: BrowserSession) -> None:
    if path is None:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mmauthtoken": session.session_token,
        "mmcsrf": session.csrf_token,
        "mmuserid": session.user_id,
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(path)
    os.chmod(path, 0o600)
