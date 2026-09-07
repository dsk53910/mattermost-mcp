from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mattermost_mcp import history_store


class HistoryStoreTests(unittest.TestCase):
    def test_detects_create_edit_and_delete(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch.object(history_store, "HISTORY_DIR", Path(tmp)):
                first = history_store.apply_snapshot(
                    "ch-1",
                    label="DM x",
                    event_at=100,
                    posts=[
                        {
                            "id": "p1",
                            "user_id": "u1",
                            "message": "hello",
                            "create_at": 10,
                            "update_at": 10,
                            "delete_at": 0,
                        }
                    ],
                )
                self.assertEqual(len(first["created"]), 1)

                second = history_store.apply_snapshot(
                    "ch-1",
                    label="DM x",
                    event_at=200,
                    posts=[
                        {
                            "id": "p1",
                            "user_id": "u1",
                            "message": "hello edited",
                            "create_at": 10,
                            "update_at": 20,
                            "delete_at": 0,
                        }
                    ],
                )
                self.assertEqual(len(second["edited"]), 1)
                self.assertEqual(second["edited"][0]["previous_message"], "hello")

                third = history_store.apply_snapshot(
                    "ch-1",
                    label="DM x",
                    event_at=300,
                    posts=[],
                )
                self.assertEqual(third["deleted"], [])

                fourth = history_store.apply_snapshot(
                    "ch-1",
                    label="DM x",
                    event_at=400,
                    posts=[
                        {
                            "id": "p1",
                            "user_id": "u1",
                            "message": "hello edited",
                            "create_at": 10,
                            "update_at": 20,
                            "delete_at": 0,
                        },
                        {
                            "id": "p2",
                            "user_id": "u1",
                            "message": "newer",
                            "create_at": 50,
                            "update_at": 50,
                            "delete_at": 0,
                        },
                    ],
                )
                self.assertEqual(len(fourth["created"]), 1)

                fifth = history_store.apply_snapshot(
                    "ch-1",
                    label="DM x",
                    event_at=500,
                    posts=[
                        {
                            "id": "p1",
                            "user_id": "u1",
                            "message": "hello edited",
                            "create_at": 10,
                            "update_at": 20,
                            "delete_at": 0,
                        }
                    ],
                )
                self.assertEqual([item["id"] for item in fifth["deleted"]], ["p2"])
