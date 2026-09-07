from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from mcp.server import Server as McpSdkServer
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .errors import JsonRpcError, MattermostApiError, MattermostConnectionError
from .mattermost_client import MattermostClient


ToolHandler = Callable[[dict[str, Any]], Any]


def _json_schema_for_tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


class MattermostMcpServer:
    def __init__(self, client: MattermostClient) -> None:
        self.client = client
        self.tools = self._build_tools()
        self._sdk = McpSdkServer("mattermost-mcp")
        self._register_sdk()

    def serve_forever(self) -> None:
        asyncio.run(self._serve_stdio())

    async def _serve_stdio(self) -> None:
        async with stdio_server() as (read_stream, write_stream):
            await self._sdk.run(
                read_stream,
                write_stream,
                self._sdk.create_initialization_options(),
            )

    def _register_sdk(self) -> None:
        @self._sdk.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name=spec["name"],
                    description=spec["description"],
                    inputSchema=spec["inputSchema"],
                )
                for spec in self.tools.values()
            ]

        @self._sdk.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            result = self._call_tool({"name": name, "arguments": arguments or {}})
            text = result["content"][0]["text"]
            return [TextContent(type="text", text=text)]

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if message.get("jsonrpc") != "2.0":
            raise JsonRpcError(-32600, "Only JSON-RPC 2.0 is supported")

        method = message.get("method")
        params = message.get("params", {})
        request_id = message.get("id")

        try:
            if method == "initialize":
                return self._result_response(request_id, self._initialize(params))
            if method == "notifications/initialized":
                return None
            if method == "ping":
                return self._result_response(request_id, {})
            if method == "tools/list":
                return self._result_response(request_id, {"tools": list(self.tools.values())})
            if method == "resources/list":
                return self._result_response(request_id, {"resources": []})
            if method == "prompts/list":
                return self._result_response(request_id, {"prompts": []})
            if method == "tools/call":
                return self._result_response(request_id, self._call_tool(params))
            raise JsonRpcError(-32601, f"Method not found: {method}")
        except JsonRpcError as exc:
            if request_id is None:
                return None
            return self._error_response(request_id, exc.code, str(exc), exc.data)

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        protocol_version = params.get("protocolVersion", "2024-11-05")
        return {
            "protocolVersion": protocol_version,
            "capabilities": {
                "tools": {
                    "listChanged": False,
                },
            },
            "serverInfo": {
                "name": "mattermost-mcp",
                "version": "0.1.0",
            },
        }

    def _build_tools(self) -> dict[str, dict[str, Any]]:
        return {
            "mattermost_get_me": _json_schema_for_tool(
                "mattermost_get_me",
                "Get the currently authenticated Mattermost user.",
                {},
            ),
            "mattermost_list_teams": _json_schema_for_tool(
                "mattermost_list_teams",
                "List teams available to the current Mattermost user.",
                {},
            ),
            "mattermost_list_channels": _json_schema_for_tool(
                "mattermost_list_channels",
                "List channels for the current user within a team.",
                {
                    "team_id": {"type": "string", "description": "Mattermost team ID"},
                },
                ["team_id"],
            ),
            "mattermost_get_channel_by_name": _json_schema_for_tool(
                "mattermost_get_channel_by_name",
                "Get channel metadata by team ID and channel name.",
                {
                    "team_id": {"type": "string", "description": "Mattermost team ID"},
                    "channel_name": {"type": "string", "description": "Channel name, for example town-square"},
                },
                ["team_id", "channel_name"],
            ),
            "mattermost_get_channel_posts": _json_schema_for_tool(
                "mattermost_get_channel_posts",
                "Fetch posts from a Mattermost channel.",
                {
                    "channel_id": {"type": "string", "description": "Mattermost channel ID"},
                    "page": {"type": "integer", "minimum": 0, "default": 0},
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 200, "default": 60},
                    "since": {"type": "integer", "minimum": 0, "description": "Unix time in milliseconds"},
                },
                ["channel_id"],
            ),
            "mattermost_create_post": _json_schema_for_tool(
                "mattermost_create_post",
                "Create a new Mattermost post in a channel.",
                {
                    "channel_id": {"type": "string", "description": "Mattermost channel ID"},
                    "message": {"type": "string", "description": "Post body"},
                    "root_id": {"type": "string", "description": "Root post ID for threaded replies"},
                    "file_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Attached file IDs",
                    },
                    "props": {
                        "type": "object",
                        "description": "Additional Mattermost post properties",
                    },
                },
                ["channel_id", "message"],
            ),
            "mattermost_search_posts": _json_schema_for_tool(
                "mattermost_search_posts",
                "Search posts inside a Mattermost team.",
                {
                    "team_id": {"type": "string", "description": "Mattermost team ID"},
                    "terms": {"type": "string", "description": "Search expression"},
                    "is_or_search": {"type": "boolean", "default": False},
                    "page": {"type": "integer", "minimum": 0, "default": 0},
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 200, "default": 60},
                },
                ["team_id", "terms"],
            ),
        }

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = self._expect_string(params, "name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, "Tool arguments must be an object")

        try:
            if name == "mattermost_get_me":
                result = self.client.get_me()
            elif name == "mattermost_list_teams":
                result = self.client.list_teams()
            elif name == "mattermost_list_channels":
                result = self.client.list_channels(self._expect_string(arguments, "team_id"))
            elif name == "mattermost_get_channel_by_name":
                result = self.client.get_channel_by_name(
                    self._expect_string(arguments, "team_id"),
                    self._expect_string(arguments, "channel_name"),
                )
            elif name == "mattermost_get_channel_posts":
                result = self.client.get_channel_posts(
                    channel_id=self._expect_string(arguments, "channel_id"),
                    page=self._expect_int(arguments, "page", 0, minimum=0),
                    per_page=self._expect_int(arguments, "per_page", 60, minimum=1),
                    since=self._expect_optional_int(arguments, "since", minimum=0),
                )
            elif name == "mattermost_create_post":
                result = self.client.create_post(
                    channel_id=self._expect_string(arguments, "channel_id"),
                    message=self._expect_string(arguments, "message"),
                    root_id=self._expect_optional_string(arguments, "root_id"),
                    file_ids=self._expect_optional_string_list(arguments, "file_ids"),
                    props=self._expect_optional_object(arguments, "props"),
                )
            elif name == "mattermost_search_posts":
                result = self.client.search_posts(
                    team_id=self._expect_string(arguments, "team_id"),
                    terms=self._expect_string(arguments, "terms"),
                    is_or_search=self._expect_bool(arguments, "is_or_search", False),
                    page=self._expect_int(arguments, "page", 0, minimum=0),
                    per_page=self._expect_int(arguments, "per_page", 60, minimum=1),
                )
            else:
                raise JsonRpcError(-32602, f"Unknown tool: {name}")
        except (MattermostApiError, MattermostConnectionError) as exc:
            payload = {
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            }
            if isinstance(exc, MattermostApiError):
                payload["error"]["status_code"] = exc.status_code
                payload["error"]["details"] = exc.details
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, ensure_ascii=False, indent=2),
                    }
                ],
                "structuredContent": payload,
            }

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ],
            "structuredContent": result,
        }

    @staticmethod
    def _expect_string(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise JsonRpcError(-32602, f"{key} must be a non-empty string")
        return value

    @staticmethod
    def _expect_optional_string(payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise JsonRpcError(-32602, f"{key} must be a non-empty string when provided")
        return value

    @staticmethod
    def _expect_int(payload: dict[str, Any], key: str, default: int, minimum: int | None = None) -> int:
        value = payload.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise JsonRpcError(-32602, f"{key} must be an integer")
        if minimum is not None and value < minimum:
            raise JsonRpcError(-32602, f"{key} must be >= {minimum}")
        return value

    @staticmethod
    def _expect_optional_int(payload: dict[str, Any], key: str, minimum: int | None = None) -> int | None:
        value = payload.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise JsonRpcError(-32602, f"{key} must be an integer when provided")
        if minimum is not None and value < minimum:
            raise JsonRpcError(-32602, f"{key} must be >= {minimum}")
        return value

    @staticmethod
    def _expect_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
        value = payload.get(key, default)
        if not isinstance(value, bool):
            raise JsonRpcError(-32602, f"{key} must be a boolean")
        return value

    @staticmethod
    def _expect_optional_string_list(payload: dict[str, Any], key: str) -> list[str] | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            raise JsonRpcError(-32602, f"{key} must be an array of non-empty strings")
        return value

    @staticmethod
    def _expect_optional_object(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise JsonRpcError(-32602, f"{key} must be an object when provided")
        return value

    @staticmethod
    def _result_response(request_id: Any, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    @staticmethod
    def _error_response(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
        if data is not None:
            payload["error"]["data"] = data
        return payload
