"""Qt-free embedded BATIQ startup entry point supplied by the AYON add-on."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Mapping

from ..context import ALL_KEYS, ENV_KEY
from .bridge_server import BridgeServer
from .menu import register_menu

# Write parameters the creators may set; paths are left to the headless extractor.
WRITE_KEYS = ("write_format", "write_limit_range", "write_first", "write_last", "write_channels")
# Graph units between a node and the Write created below it.
WRITE_OFFSET = 120.0

_bridge: BridgeServer | None = None
_helper: subprocess.Popen[str] | None = None


def _node(node) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "name": node.name,
        "enabled": node.enabled,
        "position": list(node.position),
    }


def dispatch(method: str, params: Mapping[str, Any]):
    """Map the bridge allowlist to specific built-in ``batiq`` API operations."""
    import batiq

    if method == "workfile.get":
        return batiq.project.path
    if method == "workfile.open":
        return batiq.project.open(params["path"])
    if method == "workfile.save":
        return batiq.project.save_as(params["path"]) if params.get("path") else batiq.project.save()
    if method == "workfile.modified":
        return batiq.project.modified
    if method == "project.info":
        return {
            "currentFile": batiq.project.path,
            "frameStart": batiq.project.frame_start,
            "frameEnd": batiq.project.frame_end,
            "frame_start": batiq.project.frame_start,
            "frame_end": batiq.project.frame_end,
            "fps": batiq.project.fps,
            "resolutionWidth": batiq.project.width,
            "resolutionHeight": batiq.project.height,
            "pixelAspect": batiq.project.pixel_aspect,
            "executable": batiq.app.executable,
            "host": "batiq",
            "hostVersion": batiq.app.version,
        }
    if method == "project.set_settings":
        return _set_project_settings(batiq.project, params)
    if method == "project.get_metadata":
        return batiq.project.get_metadata(params["namespace"])
    if method == "project.set_metadata":
        return batiq.project.set_metadata(params["namespace"], params["data"])
    if method == "nodes.create_read":
        node = batiq.nodes.create("Read")
        node.name = params.get("name", "Read")
        node["path"] = params["path"]
        for key in ("read_first", "read_last", "frame_offset", "input_space"):
            if params.get(key) is not None:
                node[key] = params[key]
        for namespace, data in params.get("metadata", {}).items():
            node.set_metadata(namespace, data)
        return _node(node)
    if method == "nodes.create_write":
        return _node(_create_write(batiq.nodes, params))
    if method == "nodes.get":
        node = batiq.nodes.by_id(int(params["id"]))
        return _node(node) if node else None
    if method == "nodes.update":
        node = batiq.nodes.by_id(int(params["id"]))
        if node is None:
            raise ValueError("node not found")
        if "path" in params:
            node["path"] = params["path"]
        keys = WRITE_KEYS if node.kind == "Write" else ("read_first", "read_last", "frame_offset", "input_space")
        for key in keys:
            if params.get(key) is not None:
                node[key] = params[key]
        for namespace, data in params.get("metadata", {}).items():
            node.set_metadata(namespace, data)
        return _node(node)
    if method == "nodes.remove":
        node = batiq.nodes.by_id(int(params["id"]))
        if node is None:
            raise ValueError("node not found")
        return node.delete()
    if method == "nodes.list":
        selected = {node.id for node in batiq.nodes.selected()}
        return [
            {
                **_node(node),
                "selected": node.id in selected,
                "metadata": {
                    "ayon": node.get_metadata("ayon"),
                    "ayon_publish": node.get_metadata("ayon_publish"),
                },
                "path": node["path"] if node.kind in {"Read", "Write"} else None,
                "output_format": node["output_format"] if node.kind == "Write" else None,
                "write_format": node["write_format"] if node.kind == "Write" else None,
                "output_space": node["output_space"] if node.kind == "Write" else None,
                "write_limit_range": node["write_limit_range"] if node.kind == "Write" else None,
                "write_first": node["write_first"] if node.kind == "Write" else None,
                "write_last": node["write_last"] if node.kind == "Write" else None,
                "write_channels": node["write_channels"] if node.kind == "Write" else None,
            }
            for node in batiq.nodes.all()
        ]
    if method == "nodes.select":
        return batiq.nodes.select([int(value) for value in params["ids"]])
    if method == "ui.show":
        return _show_helper(str(params["tool"]))
    if method == "render.request":
        raise ValueError("render is handled by the isolated headless extractor")
    raise ValueError("method is not allowed")


def _create_write(nodes, params: Mapping[str, Any]):
    """A Write node fed by ``input`` (a node id) and placed just below it."""
    source = None
    if params.get("input") is not None:
        source = nodes.by_id(int(params["input"]))
        if source is None:
            raise ValueError("input node not found")
    node = nodes.create("Write")
    node.name = params.get("name", "Write")
    if source is not None:
        node.set_input(0, source)
        x, y = source.position
        node.position = (x, y + WRITE_OFFSET)
    for key in WRITE_KEYS:
        if params.get(key) is not None:
            node[key] = params[key]
    for namespace, data in params.get("metadata", {}).items():
        node.set_metadata(namespace, data)
    nodes.select([node.id])
    return node


def _set_project_settings(project, values: Mapping[str, Any]) -> dict[str, Any]:
    """Apply validated frame range, fps and format values to the open project."""
    unknown = set(values) - set(ALL_KEYS)
    if unknown:
        raise ValueError(f"unsupported project settings: {sorted(unknown)}")
    converted = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        converted[key] = float(value) if key in ("fps", "pixel_aspect") else int(value)
    start = converted.get("frame_start", project.frame_start)
    end = converted.get("frame_end", project.frame_end)
    if end < start:
        raise ValueError("frame_end must not be before frame_start")
    # Move the end first when the new range starts after the current end.
    order = ["frame_end", "frame_start"] if start > project.frame_end else ["frame_start", "frame_end"]
    for key in order + ["fps", "width", "height", "pixel_aspect"]:
        if key in converted:
            setattr(project, key, converted[key])
    return {key: getattr(project, key) for key in ALL_KEYS}


def _apply_launch_context() -> None:
    """Give a fresh, unsaved project the task's settings passed by the launch hook."""
    import batiq

    raw = os.environ.pop(ENV_KEY, None)
    if not raw or batiq.project.path or batiq.project.modified:
        return
    try:
        _set_project_settings(batiq.project, json.loads(raw))
    except Exception as exc:  # never block BATIQ startup
        print(f"AYON could not apply the task settings: {exc}")


def _show_helper(tool: str) -> dict[str, Any]:
    global _helper
    executable = os.environ.get("AYON_EXECUTABLE")
    if not executable:
        raise RuntimeError("AYON_EXECUTABLE is required to launch the AYON helper")
    started = False
    if _helper is None or _helper.poll() is not None:
        assert _bridge is not None
        host, port = _bridge.address
        _helper = subprocess.Popen(
            [executable, "addon", "batiq", "ui-helper", "--host", host, "--port", str(port)],
            shell=False,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        started = True
    if _helper.stdin is None:
        raise RuntimeError("AYON Batiq helper has no command channel")
    try:
        if started:
            _helper.stdin.write(json.dumps({"token": _bridge.token}) + "\n")
        _helper.stdin.write(json.dumps({"tool": tool}) + "\n")
        _helper.stdin.flush()
    except BrokenPipeError as exc:
        raise RuntimeError("AYON Batiq helper stopped unexpectedly") from exc
    return {"tool": tool, "started": started}


def bootstrap():
    """Start the local bridge once, then register BATIQ's native AYON menu."""
    global _bridge
    if _bridge is None:
        _bridge = BridgeServer(dispatch)
        _bridge.start()
        import batiq

        register_menu(batiq.ui, _show_helper)
        _apply_launch_context()
    return _bridge


def shutdown() -> None:
    """Bounded helper cleanup followed by bridge closure during BATIQ shutdown."""
    global _bridge, _helper
    helper, _helper = _helper, None
    if helper is not None:
        if helper.stdin is not None:
            helper.stdin.close()
        try:
            helper.wait(timeout=2)
        except subprocess.TimeoutExpired:
            helper.terminate()
            try:
                helper.wait(timeout=2)
            except subprocess.TimeoutExpired:
                helper.kill()
                helper.wait(timeout=2)
    bridge, _bridge = _bridge, None
    if bridge is not None:
        bridge.close()


bootstrap()
