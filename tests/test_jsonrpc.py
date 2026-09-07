from __future__ import annotations

import io
import json
import unittest

from mattermost_mcp.jsonrpc import JsonRpcReader, JsonRpcWriter


class JsonRpcTests(unittest.TestCase):
    def test_reads_content_length_framing(self) -> None:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        body = json.dumps(payload).encode("utf-8")
        stream = io.BytesIO(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        self.assertEqual(JsonRpcReader(stream).read_message(), payload)

    def test_reads_newline_delimited_json(self) -> None:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        stream = io.BytesIO(json.dumps(payload).encode("utf-8") + b"\n")
        self.assertEqual(JsonRpcReader(stream).read_message(), payload)

    def test_writes_content_length_framing(self) -> None:
        stream = io.BytesIO()
        JsonRpcWriter(stream).write_message({"jsonrpc": "2.0", "id": 1, "result": {}})
        raw = stream.getvalue()
        self.assertTrue(raw.startswith(b"Content-Length: "))
        self.assertIn(b"\r\n\r\n", raw)
