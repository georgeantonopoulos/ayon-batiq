"""Small, self-contained client for BATIQ's versioned JSONL protocol."""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any, Mapping

MAX_OUTPUT_BYTES = 8 * 1024 * 1024
PROTOCOL_MAJOR = 1


class HeadlessRenderError(RuntimeError):
    """BATIQ could not produce a validated successful render result."""


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise HeadlessRenderError(f"{label} must be an object")
    return value


def _response(message: Mapping[str, Any], request_id: int, method: str) -> Mapping[str, Any]:
    if message.get("jsonrpc") != "2.0" or message.get("id") != request_id:
        raise HeadlessRenderError(f"{method} returned a mismatched JSON-RPC response")
    if "error" in message:
        raise HeadlessRenderError(f"{method} failed: {message['error']!r}")
    return _object(message.get("result"), f"{method} result")


def render(
    *,
    executable: str,
    project: str,
    output: str,
    frames: tuple[int, int, int],
    write_node: int,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Render one explicit Write node and validate the complete protocol."""
    if isinstance(write_node, bool) or not isinstance(write_node, int) or write_node <= 0:
        raise HeadlessRenderError("a positive integer Write node id is required")
    start, end, step = frames
    if end < start or step <= 0:
        raise HeadlessRenderError("frames require end >= start and a positive step")
    if timeout <= 0:
        raise HeadlessRenderError("timeout must be positive")

    requests = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocol_version": {"major": PROTOCOL_MAJOR, "minor": 0},
                "client": {"name": "ayon-batiq", "version": "0.1.0"},
                "capabilities": {},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "render",
            "params": {
                "project": str(Path(project).expanduser().resolve()),
                "output": str(Path(output).expanduser().resolve()),
                "frames": {"start": start, "end": end, "step": step},
                "write_node": write_node,
            },
        },
    )
    payload = "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in requests).encode()
    try:
        process = subprocess.Popen(
            [executable, "--headless"],
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise HeadlessRenderError(f"could not start BATIQ headless mode: {exc}") from exc

    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    state = {"bytes": 0, "overflow": False}
    lock = threading.Lock()

    def capture(name: str, stream: Any) -> None:
        with stream:
            while chunk := stream.read(64 * 1024):
                with lock:
                    remaining = MAX_OUTPUT_BYTES - state["bytes"]
                    if remaining > 0:
                        kept = chunk[:remaining]
                        buffers[name].extend(kept)
                        state["bytes"] += len(kept)
                    if len(chunk) > remaining:
                        state["overflow"] = True
                        process.kill()

    assert process.stdout is not None and process.stderr is not None
    readers = [
        threading.Thread(target=capture, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=capture, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        assert process.stdin is not None
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except BrokenPipeError:
            pass
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise HeadlessRenderError(f"BATIQ headless render timed out after {timeout:g}s") from exc
    finally:
        for reader in readers:
            reader.join()

    stderr = bytes(buffers["stderr"]).decode("utf-8", "replace")[:4096]
    if state["overflow"]:
        raise HeadlessRenderError(f"BATIQ headless output exceeded {MAX_OUTPUT_BYTES} bytes")
    if process.returncode:
        raise HeadlessRenderError(
            f"BATIQ headless mode exited with status {process.returncode}: {stderr}"
        )
    try:
        messages = [json.loads(line) for line in bytes(buffers["stdout"]).splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HeadlessRenderError("BATIQ headless mode returned malformed JSON") from exc
    if not messages:
        raise HeadlessRenderError("BATIQ headless mode returned no response")

    init = _response(_object(messages[0], "initialize response"), 1, "initialize")
    version = _object(init.get("protocol_version"), "protocol_version")
    if version.get("major") != PROTOCOL_MAJOR:
        raise HeadlessRenderError(f"unsupported BATIQ protocol major {version.get('major')!r}")
    capabilities = _object(init.get("capabilities"), "capabilities")
    if capabilities.get("render") is not True:
        raise HeadlessRenderError("BATIQ headless mode does not advertise render support")

    result: Mapping[str, Any] | None = None
    events: list[tuple[int, str, Mapping[str, Any]]] = []
    for raw in messages[1:]:
        message = _object(raw, "JSON-RPC message")
        if message.get("method") == "render_event" and "id" not in message:
            if message.get("jsonrpc") != "2.0":
                raise HeadlessRenderError("render_event has an invalid JSON-RPC version")
            params = _object(message.get("params"), "render_event params")
            sequence = params.get("sequence", params.get("seq"))
            event = params.get("event", params.get("state", params.get("status")))
            if isinstance(sequence, bool) or not isinstance(sequence, int) or not isinstance(event, str):
                raise HeadlessRenderError("render_event requires an integer sequence and string event")
            events.append((sequence, event, params))
        elif message.get("id") == 2:
            if result is not None:
                raise HeadlessRenderError("BATIQ returned more than one render response")
            result = _response(message, 2, "render")
        else:
            raise HeadlessRenderError("BATIQ returned an unexpected JSON-RPC message")

    if result is None:
        raise HeadlessRenderError("BATIQ returned no render response")
    terminals = {"finished", "failed", "canceled"}
    terminal_events = [item for item in events if item[1] in terminals]
    if len(terminal_events) != 1:
        raise HeadlessRenderError(f"expected one terminal render_event, got {len(terminal_events)}")
    if events[-1] != terminal_events[0]:
        raise HeadlessRenderError("the terminal render_event must be last")
    if any(current[0] <= previous[0] for previous, current in zip(events, events[1:])):
        raise HeadlessRenderError("render_event sequences must be strictly increasing")
    terminal = terminal_events[0]
    if terminal[1] != "finished":
        detail = terminal[2].get("data")
        error = detail.get("error") if isinstance(detail, dict) else None
        raise HeadlessRenderError(str(error or f"render {terminal[1]}"))
    return dict(result)
