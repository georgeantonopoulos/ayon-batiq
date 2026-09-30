"""Restricted, authenticated loopback JSON-RPC bridge for the AYON helper."""
from __future__ import annotations

import json
import secrets
import socket
import threading
from typing import Any, Callable, Mapping

MAX_MESSAGE_BYTES = 64 * 1024
ALLOWED_METHODS = frozenset({
    "workfile.get", "workfile.open", "workfile.save", "workfile.modified",
    "project.info", "project.set_settings", "project.get_metadata", "project.set_metadata",
    "nodes.create_read", "nodes.create_write", "nodes.get", "nodes.update", "nodes.remove", "nodes.list",
    "nodes.select", "render.request", "ui.show",
})


class BridgeError(RuntimeError):
    pass


class BridgeServer:
    """A finite, allowlisted adapter; it never executes caller-supplied code."""

    def __init__(self, dispatch: Callable[[str, Mapping[str, Any]], Any], *, timeout: float = 5.0):
        self.dispatch, self.timeout, self.token = dispatch, timeout, secrets.token_urlsafe(32)
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def address(self) -> tuple[str, int]:
        if self._socket is None:
            raise BridgeError("bridge is not started")
        host, port = self._socket.getsockname()
        return str(host), int(port)

    def start(self) -> None:
        if self._socket:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(0.2)
        except Exception:
            listener.close()
            raise
        self._socket = listener
        self._thread = threading.Thread(target=self._serve, daemon=True, name="ayon-batiq-bridge")
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._socket:
            self._socket.close()
            self._socket = None
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None

    def _serve(self) -> None:
        assert self._socket
        while not self._stop.is_set():
            try:
                conn, _ = self._socket.accept()
            except (TimeoutError, OSError):
                continue
            with conn:
                conn.settimeout(self.timeout)
                stream = conn.makefile("rwb")
                while not self._stop.is_set():
                    try:
                        line = stream.readline(MAX_MESSAGE_BYTES + 1)
                    except OSError:
                        break
                    if not line:
                        break
                    response = self.handle_line(line)
                    stream.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")
                    stream.flush()

    def handle_line(self, line: bytes) -> dict[str, Any]:
        request_id: Any = None
        try:
            if len(line) > MAX_MESSAGE_BYTES:
                raise BridgeError("message too large")
            request = json.loads(line)
            request_id = request.get("id") if isinstance(request, dict) else None
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise BridgeError("invalid JSON-RPC")
            method, params = request.get("method"), request.get("params", {})
            if request.get("token") != self.token:
                raise BridgeError("authentication failed")
            if method not in ALLOWED_METHODS:
                raise BridgeError("method is not allowed")
            if not isinstance(params, dict):
                raise BridgeError("params must be an object")
            return {"jsonrpc": "2.0", "id": request_id, "result": self.dispatch(method, params)}
        except (ValueError, BridgeError) as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": str(exc)}}
        except Exception:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": "host operation failed"}}
