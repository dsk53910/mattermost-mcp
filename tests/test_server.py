from __future__ import annotations

import unittest

from mattermost_mcp.server import MattermostMcpServer


class FakeClient:
    def get_me(self):
        return {"id": "user-1"}

    def list_teams(self):
        return [{"id": "team-1"}]

    def list_channels(self, team_id: str):
        return [{"id": "channel-1", "team_id": team_id}]

    def get_channel_by_name(self, team_id: str, channel_name: str):
        return {"id": "channel-1", "team_id": team_id, "name": channel_name}

    def get_channel_posts(self, channel_id: str, page: int, per_page: int, since=None):
        return {"order": ["post-1"], "channel_id": channel_id, "page": page, "per_page": per_page, "since": since}

    def create_post(self, channel_id: str, message: str, root_id=None, file_ids=None, props=None):
        return {"id": "post-1", "channel_id": channel_id, "message": message, "root_id": root_id, "file_ids": file_ids, "props": props}

    def search_posts(self, team_id: str, terms: str, is_or_search: bool, page: int, per_page: int):
        return {"team_id": team_id, "terms": terms, "is_or_search": is_or_search, "page": page, "per_page": per_page}


class MattermostMcpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MattermostMcpServer(FakeClient())

    def test_initialize(self) -> None:
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )

        self.assertEqual(response["result"]["serverInfo"]["name"], "mattermost-mcp")
        self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")

    def test_tools_list(self) -> None:
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            }
        )

        tool_names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("mattermost_create_post", tool_names)
        self.assertIn("mattermost_get_me", tool_names)

    def test_create_post_tool_call(self) -> None:
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "mattermost_create_post",
                    "arguments": {
                        "channel_id": "channel-1",
                        "message": "hello",
                    },
                },
            }
        )

        self.assertEqual(response["result"]["structuredContent"]["id"], "post-1")
        self.assertIn("hello", response["result"]["content"][0]["text"])
