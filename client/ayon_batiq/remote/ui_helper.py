"""Persistent AYON Qt process; BATIQ itself never imports Qt."""
from __future__ import annotations
import json
import queue
import sys
import threading

from ayon_batiq.api.bridge_client import BridgeClient
from ayon_batiq.api.host import RemoteBatiqHost


def show_tool(tool: str) -> None:
    from ayon_core.pipeline import registered_host
    from ayon_core.tools.utils import host_tools

    from ayon_batiq.context import FORMAT_KEYS, FRAME_KEYS

    def apply(keys):
        return lambda: registered_host().apply_context_settings(keys)

    actions = {
        "set_frame_range": apply(FRAME_KEYS + ("fps",)),
        "set_resolution": apply(FORMAT_KEYS),
        "apply_settings": apply(None),
        "workfiles": lambda: host_tools.show_workfiles(parent=None, on_top=False),
        "load": lambda: host_tools.show_loader(parent=None, use_context=True),
        "manage": lambda: host_tools.show_scene_inventory(parent=None),
        "publish": lambda: host_tools.show_publisher(parent=None, tab="publish"),
    }
    try:
        action = actions[tool]
    except KeyError as exc:
        raise ValueError(f"unsupported AYON tool {tool!r}") from exc
    action()


def main(host: str, port: int):
    """AYON add-on CLI target; token is strictly the first stdin JSON line."""
    try:
        startup = json.loads(sys.stdin.readline())
        token = str(startup["token"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("BATIQ helper did not receive bridge authentication") from exc

    from ayon_core.pipeline import install_host
    from qtpy import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    remote_host = RemoteBatiqHost(BridgeClient(host, port, token))
    install_host(remote_host)
    pending: queue.Queue[str | None] = queue.Queue()

    def read_commands() -> None:
        for line in sys.stdin:
            try:
                command = json.loads(line)
                pending.put(str(command["tool"]))
            except (KeyError, TypeError, ValueError) as exc:
                print(f"AYON Batiq helper ignored invalid command: {exc}", file=sys.stderr)
        pending.put(None)

    threading.Thread(target=read_commands, daemon=True, name="ayon-batiq-ui-commands").start()
    timer = QtCore.QTimer()

    def drain() -> None:
        while True:
            try:
                tool = pending.get_nowait()
            except queue.Empty:
                return
            if tool is None:
                app.quit()
                return
            try:
                show_tool(tool)
            except Exception as exc:
                print(f"AYON Batiq could not show {tool}: {exc}", file=sys.stderr)

    timer.timeout.connect(drain)
    timer.start(50)
    try:
        app.exec()
    finally:
        remote_host.uninstall()
