from __future__ import annotations

import json
from typing import Any, BinaryIO

from .errors import JsonRpcError


class JsonRpcReader:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream

    def read_message(self) -> dict[str, Any] | None:
        line = self.stream.readline()
        if not line:
            return None

        stripped = line.lstrip()
        if stripped.startswith(b"{") or stripped.startswith(b"["):
            try:
                payload = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise JsonRpcError(-32700, f"Invalid JSON payload: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise JsonRpcError(-32700, "JSON-RPC payload must be an object")
            return payload

        headers: dict[str, str] = {}
        while True:
            if line in {b"\r\n", b"\n"}:
                break

            decoded = line.decode("ascii").strip()
            if ":" not in decoded:
                raise JsonRpcError(-32700, f"Malformed header line: {decoded!r}")

            name, value = decoded.split(":", 1)
            headers[name.lower()] = value.strip()

            line = self.stream.readline()
            if not line:
                raise JsonRpcError(-32700, "Unexpected end of input")

        if "content-length" not in headers:
            raise JsonRpcError(-32700, "Missing Content-Length header")

        try:
            length = int(headers["content-length"])
        except ValueError as exc:
            raise JsonRpcError(-32700, "Invalid Content-Length header") from exc

        body = self.stream.read(length)
        if len(body) != length:
            raise JsonRpcError(-32700, "Unexpected end of input")

        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise JsonRpcError(-32700, f"Invalid JSON payload: {exc.msg}") from exc


class JsonRpcWriter:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream

    def write_message(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.stream.write(header)
        self.stream.write(body)
        self.stream.flush()
