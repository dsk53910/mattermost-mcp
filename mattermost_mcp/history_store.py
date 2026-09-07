from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HISTORY_DIR = Path(__file__).resolve().parent.parent / ".mm-history"
MAX_EVENTS = 500


def _sanitize(message: str | None) -> str:
    text = message or ""
    lowered = text.lower()
    if "cookie:" in lowered or "ssh-rsa" in text or "ssh-ed25519" in text or "begin openssh" in lowered:
        return "<omitted>"
    return text


def _record(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": post.get("id"),
        "user_id": post.get("user_id"),
        "message": _sanitize(post.get("message")),
        "create_at": post.get("create_at") or 0,
        "update_at": post.get("update_at") or 0,
        "delete_at": post.get("delete_at") or 0,
        "root_id": post.get("root_id") or "",
    }


def channel_path(channel_id: str) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{channel_id}.json"


def load_channel(channel_id: str) -> dict[str, Any]:
    path = channel_path(channel_id)
    if not path.is_file():
        return {"channel_id": channel_id, "label": "", "posts": {}, "events": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"channel_id": channel_id, "label": "", "posts": {}, "events": []}
    if not isinstance(payload, dict):
        return {"channel_id": channel_id, "label": "", "posts": {}, "events": []}
    payload.setdefault("posts", {})
    payload.setdefault("events", [])
    payload["channel_id"] = channel_id
    return payload


def save_channel(payload: dict[str, Any]) -> None:
    path = channel_path(payload["channel_id"])
    events = payload.get("events") or []
    if len(events) > MAX_EVENTS:
        payload["events"] = events[-MAX_EVENTS:]
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def apply_snapshot(
    channel_id: str,
    *,
    label: str,
    posts: list[dict[str, Any]],
    event_at: int,
) -> dict[str, Any]:
    store = load_channel(channel_id)
    store["label"] = label or store.get("label") or ""
    known: dict[str, Any] = store.get("posts") or {}
    fetched_ids = {post.get("id") for post in posts if post.get("id")}
    created: list[dict[str, Any]] = []
    edited: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    prev_window = set(store.get("last_window_ids") or [])
    window_start = min((post.get("create_at") or 0) for post in posts) if posts else 0

    for post in posts:
        rec = _record(post)
        pid = rec["id"]
        if not pid:
            continue
        prev = known.get(pid)
        if prev is None:
            known[pid] = rec
            if rec["delete_at"]:
                continue
            created.append(rec)
            store.setdefault("events", []).append(
                {"at": event_at, "type": "created", "post_id": pid}
            )
            continue
        if rec["delete_at"] and not prev.get("delete_at"):
            known[pid] = rec
            deleted.append(rec)
            store.setdefault("events", []).append(
                {"at": event_at, "type": "deleted", "post_id": pid}
            )
            continue
        if rec["message"] != prev.get("message") or rec["update_at"] != prev.get("update_at"):
            rec["previous_message"] = prev.get("message")
            known[pid] = {k: rec[k] for k in ("id", "user_id", "message", "create_at", "update_at", "delete_at", "root_id")}
            edited.append(rec)
            store.setdefault("events", []).append(
                {"at": event_at, "type": "edited", "post_id": pid}
            )

    if posts and window_start:
        for pid in prev_window:
            if pid in fetched_ids:
                continue
            prev = known.get(pid)
            if not prev or prev.get("delete_at"):
                continue
            if (prev.get("create_at") or 0) < window_start:
                continue
            marked = dict(prev)
            marked["delete_at"] = event_at
            known[pid] = marked
            deleted.append(marked)
            store.setdefault("events", []).append(
                {"at": event_at, "type": "deleted", "post_id": pid}
            )

    store["posts"] = known
    if posts:
        store["last_window_ids"] = [pid for pid in fetched_ids if pid]
    save_channel(store)
    return {"created": created, "edited": edited, "deleted": deleted}
