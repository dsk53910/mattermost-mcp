#!/usr/bin/env python3
"""Delta of DMs/mentions. Cheap metadata ticks; posts+local history only when needed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mattermost_mcp.config import Settings, load_dotenv
from mattermost_mcp.history_store import apply_snapshot
from mattermost_mcp.mattermost_client import MattermostClient
from mattermost_mcp.session_store import load_session

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / ".mm-watch-state.json"
CHANNEL_TYPES = {"O": "open", "P": "private", "D": "dm", "G": "group"}


def client() -> MattermostClient:
    load_dotenv()
    settings = Settings.from_env()
    stored = load_session(settings.session_file)
    if stored is None:
        print("session_expired_or_missing", file=sys.stderr)
        raise SystemExit(2)
    return MattermostClient(
        base_url=settings.base_url,
        session_token=stored.session_token,
        csrf_token=stored.csrf_token,
        user_id=stored.user_id,
        timeout_seconds=settings.timeout_seconds,
        verify_ssl=settings.verify_ssl,
    )


def load_state() -> dict:
    if not STATE_PATH.is_file():
        return {"channels": {}}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def clean_msg(msg: str | None) -> str:
    text = (msg or "").strip().replace("\n", " ")
    if "Cookie:" in text or "ssh-" in text:
        return "<omitted>"
    if len(text) > 180:
        return text[:180] + "…"
    return text


def names_for(c: MattermostClient, user_ids: list[str]) -> dict[str, str]:
    ids = [uid for uid in dict.fromkeys(user_ids) if uid]
    if not ids:
        return {}
    users = c._request("POST", "/users/ids", payload=ids)
    out = {}
    if isinstance(users, list):
        for user in users:
            uid = user.get("id")
            if uid:
                out[uid] = user.get("username") or uid
    return out


def label_channel(ch: dict, me_id: str, usernames: dict[str, str]) -> str:
    if ch.get("type") in {"D", "G"}:
        name = ch.get("name") or ""
        other_ids = [part for part in name.split("__") if part and part != me_id]
        people = [usernames.get(oid, oid[-6:]) for oid in other_ids]
        prefix = "DM" if ch.get("type") == "D" else "GM"
        return f"{prefix} {' / '.join(people) if people else name}"
    return ch.get("display_name") or ch.get("name") or ch.get("id")


def unread_count(ch: dict) -> int:
    total = ch.get("total_msg_count")
    seen = ch.get("member_msg_count")
    if isinstance(total, int) and isinstance(seen, int):
        return max(0, total - seen)
    return 0


def needs_posts(ch: dict, prev: dict, init: bool) -> bool:
    if init:
        return False
    if (ch.get("mention_count") or 0) > 0:
        return True
    if unread_count(ch) > 0:
        return True
    prev_total = prev.get("total_msg_count")
    total = ch.get("total_msg_count")
    if isinstance(prev_total, int) and isinstance(total, int) and total != prev_total:
        return True
    return False


def collect_channels(c: MattermostClient, me_id: str) -> list[dict]:
    teams = c.list_teams()
    collected = []
    for team in teams:
        team_id = team.get("id")
        channels = c.list_channels(team_id)
        members = c._request("GET", f"/users/{me_id}/teams/{team_id}/channels/members")
        if not isinstance(members, list):
            members = []
        member_by_id = {m.get("channel_id"): m for m in members if isinstance(m, dict)}
        for ch in channels:
            cid = ch.get("id")
            member = member_by_id.get(cid) or {}
            collected.append(
                {
                    "id": cid,
                    "name": ch.get("name"),
                    "display_name": ch.get("display_name"),
                    "type": ch.get("type"),
                    "team": team.get("name"),
                    "mention_count": member.get("mention_count") or 0,
                    "last_viewed_at": member.get("last_viewed_at") or 0,
                    "total_msg_count": ch.get("total_msg_count") or 0,
                    "member_msg_count": member.get("msg_count"),
                }
            )
    return collected


def recent_posts(c: MattermostClient, channel_id: str) -> list[dict]:
    resp = c.get_channel_posts(channel_id=channel_id, page=0, per_page=60)
    order = list(reversed(resp.get("order") or []))
    posts = resp.get("posts") or {}
    return [posts[pid] for pid in order if isinstance(posts.get(pid), dict)]


def sync_channel(
    c: MattermostClient,
    ch: dict,
    *,
    me_id: str,
    usernames: dict[str, str],
    prev: dict,
    event_at: int,
) -> dict:
    cid = ch["id"]
    label = prev.get("label") or label_channel(ch, me_id, usernames)
    raw = recent_posts(c, cid)
    delta = apply_snapshot(cid, label=label, posts=raw, event_at=event_at)
    latest = max((post.get("create_at") or 0) for post in raw) if raw else prev.get("last_create_at") or 0
    return {
        "id": cid,
        "label": label,
        "latest": latest,
        "created": delta["created"],
        "edited": delta["edited"],
        "deleted": delta["deleted"],
        "raw": raw,
    }


def annotate(posts: list[dict], me_id: str, usernames: dict[str, str]) -> list[dict]:
    out = []
    for post in posts:
        out.append(
            {
                "id": post.get("id"),
                "who": "ты" if post.get("user_id") == me_id else usernames.get(post.get("user_id"), (post.get("user_id") or "")[-6:]),
                "create_at": post.get("create_at"),
                "message": clean_msg(post.get("message")),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="baseline counters without fetching posts")
    parser.add_argument("--deep", action="store_true", help="refresh last 60 posts for all DMs/GMs into local history")
    args = parser.parse_args()

    c = client()
    me = c.get_me()
    me_id = me["id"]
    state = load_state()
    channels_state = state.setdefault("channels", {})
    all_channels = collect_channels(c, me_id)
    event_at = __import__("time").time_ns() // 1_000_000

    dm_like = [ch for ch in all_channels if ch.get("type") in {"D", "G"}]
    mentioned = [ch for ch in all_channels if (ch.get("mention_count") or 0) > 0]
    to_fetch = []
    seen: set[str] = set()
    for ch in dm_like + mentioned:
        cid = ch["id"]
        if cid in seen:
            continue
        if args.deep or (not args.init and needs_posts(ch, channels_state.get(cid) or {}, False)):
            to_fetch.append(ch)
            seen.add(cid)
        elif args.init and (unread_count(ch) > 0 or (ch.get("mention_count") or 0) > 0):
            seen.add(cid)

    user_ids = [me_id]
    for ch in to_fetch + [ch for ch in dm_like + mentioned if unread_count(ch) > 0 or (ch.get("mention_count") or 0) > 0]:
        user_ids.extend(part for part in (ch.get("name") or "").split("__") if part)
    usernames = names_for(c, user_ids) if user_ids else {}

    report = []
    fetched_ids: set[str] = set()
    for ch in to_fetch:
        cid = ch["id"]
        prev = channels_state.get(cid) or {}
        synced = sync_channel(c, ch, me_id=me_id, usernames=usernames, prev=prev, event_at=event_at)
        fetched_ids.add(cid)
        channels_state[cid] = {
            "last_create_at": synced["latest"],
            "total_msg_count": ch.get("total_msg_count"),
            "type": CHANNEL_TYPES.get(ch["type"], ch["type"]),
            "label": synced["label"],
        }
        if args.init:
            continue
        if not (synced["created"] or synced["edited"] or synced["deleted"]):
            continue
        kind = "mention" if (ch.get("mention_count") or 0) > 0 and ch.get("type") not in {"D", "G"} else "dm"
        item = {
            "kind": kind,
            "id": cid,
            "label": synced["label"],
            "created": annotate(synced["created"], me_id, usernames),
            "edited": annotate(synced["edited"], me_id, usernames),
            "deleted": [{"id": post.get("id"), "message": clean_msg(post.get("message"))} for post in synced["deleted"]],
        }
        if kind == "mention":
            item["mentions"] = ch.get("mention_count")
        report.append(item)

    for ch in dm_like + mentioned:
        cid = ch["id"]
        if cid in fetched_ids:
            continue
        prev = channels_state.get(cid) or {}
        channels_state[cid] = {
            "last_create_at": prev.get("last_create_at") or 0,
            "total_msg_count": ch.get("total_msg_count"),
            "type": CHANNEL_TYPES.get(ch["type"], ch["type"]),
            "label": prev.get("label") or label_channel(ch, me_id, usernames),
        }

    state["mode"] = "dms-and-mentions"
    save_state(state)

    payload = {
        "init": args.init,
        "deep": args.deep,
        "dm_count": len(dm_like),
        "mention_channels": len(mentioned),
        "fetched_channels": len(to_fetch),
        "new_items": len(report),
        "items": report,
        "open_mentions": [
            {
                "id": ch["id"],
                "label": label_channel(ch, me_id, usernames),
                "mentions": ch["mention_count"],
                "type": CHANNEL_TYPES.get(ch["type"], ch["type"]),
            }
            for ch in mentioned
        ],
        "unread_dms": [
            {
                "id": ch["id"],
                "label": label_channel(ch, me_id, usernames),
                "mentions": ch["mention_count"],
            }
            for ch in dm_like
            if unread_count(ch) > 0 or (ch.get("mention_count") or 0) > 0
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
