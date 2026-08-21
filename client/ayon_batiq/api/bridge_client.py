"""Bounded JSON-RPC client for the authenticated BATIQ localhost bridge."""
from __future__ import annotations

import json
import socket
from typing import Any, Mapping

MAX_MESSAGE_BYTES = 64 * 1024


class BridgeError(RuntimeError):
    """A bridge transport or remote-command failure."""


class BridgeClient:
    def __init__(self, host: str, port: int, token: str, *, timeout: float = 5.0):
        self.host, self.port, self.token, self.timeout = host, int(port), token, timeout
        self._next_id = 1

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        request_id = self._next_id
        self._next_id += 1
        payload = json.dumps({
            "jsonrpc": "2.0", "id": request_id, "method": method,
            "params": dict(params or {}), "token": self.token,
        }).encode("utf-8") + b"\n"
        if len(payload) > MAX_MESSAGE_BYTES:
            raise BridgeError("bridge request exceeds 64 KiB")
        try:
            with socket.create_connection((self.host, self.port), self.timeout) as conn:
                conn.settimeout(self.timeout)
                conn.sendall(payload)
                response = self._read_line(conn)
        except OSError as exc:
            raise BridgeError(f"BATIQ bridge unavailable: {exc}") from exc
        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            raise BridgeError("BATIQ bridge returned invalid JSON") from exc
        if data.get("jsonrpc") != "2.0" or data.get("id") != request_id:
            raise BridgeError("BATIQ bridge returned a mismatched response")
        if "error" in data:
            raise BridgeError(str(data["error"].get("message", "bridge command failed")))
        if "result" not in data:
            raise BridgeError("BATIQ bridge returned no result")
        return data["result"]

    def _read_line(self, conn: socket.socket) -> bytes:
        data = bytearray()
        while True:
            chunk = conn.recv(min(4096, MAX_MESSAGE_BYTES - len(data) + 1))
            if not chunk:
                raise BridgeError("BATIQ bridge closed before a response")
            data.extend(chunk)
            if len(data) > MAX_MESSAGE_BYTES:
                raise BridgeError("bridge response exceeds 64 KiB")
            if data.endswith(b"\n"):
                return bytes(data)
