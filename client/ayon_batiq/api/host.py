"""The AYON Core host implementation backed by BATIQ's narrow bridge."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ayon_core.host import HostBase, ILoadHost, IPublishHost, IWorkfileHost
from ayon_core.pipeline import (
    deregister_creator_plugin_path, deregister_inventory_action_path,
    deregister_loader_plugin_path, register_creator_plugin_path,
    register_inventory_action_path, register_loader_plugin_path,
)


class RemoteBatiqHost(HostBase, IWorkfileHost, ILoadHost, IPublishHost):
    """Maps AYON host calls onto the already-running BATIQ process."""

    name = "batiq"

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self._plugin_paths: list[str] = []

    def get_current_workfile(self):
        return self.bridge.call("workfile.get") or None

    def open_workfile(self, filepath):
        return self.bridge.call("workfile.open", {"path": str(filepath)})

    def save_workfile(self, filepath=None):
        params = {} if filepath is None else {"path": str(filepath)}
        return self.bridge.call("workfile.save", params)

    def workfile_has_unsaved_changes(self):
        return bool(self.bridge.call("workfile.modified"))

    def get_workfile_extensions(self):
        return [".batiq"]

    def work_root(self, session):
        return str(Path(session.get("AYON_WORKDIR") or session.get("AVALON_WORKDIR") or "."))

    def get_context_data(self):
        return self.bridge.call("project.get_metadata", {"namespace": "ayon_publish_context"}) or {}

    def update_context_data(self, data, changes=None):
        return self.bridge.call(
            "project.set_metadata",
            {"namespace": "ayon_publish_context", "data": dict(data or {})},
        )

    def get_context_title(self):
        path = self.get_current_workfile()
        return Path(path).name if path else "Untitled BATIQ Project"

    def get_batiq_project_info(self) -> dict[str, Any]:
        return self.bridge.call("project.info") or {}

    def get_containers(self):
        containers = []
        for node in self.bridge.call("nodes.list") or []:
            data = (node.get("metadata") or {}).get("ayon")
            if isinstance(data, dict) and data.get("schema") == "ayon:container-3.0":
                containers.append({**data, "objectName": str(node["id"]), "_node": node})
        return containers

    def install(self):
        import pyblish.api

        plugins = Path(__file__).resolve().parents[1] / "plugins"
        paths = {
            register_creator_plugin_path: plugins / "create",
            register_loader_plugin_path: plugins / "load",
            register_inventory_action_path: plugins / "inventory",
        }
        pyblish.api.register_host(self.name)
        pyblish.api.register_plugin_path(str(plugins / "publish"))
        for register, path in paths.items():
            register(str(path))
            self._plugin_paths.append(str(path))
        self._plugin_paths.append(str(plugins / "publish"))

    def uninstall(self):
        import pyblish.api

        deregister_creator_plugin_path(str(Path(self._plugin_paths[0]))) if self._plugin_paths else None
        if len(self._plugin_paths) > 1:
            deregister_loader_plugin_path(self._plugin_paths[1])
        if len(self._plugin_paths) > 2:
            deregister_inventory_action_path(self._plugin_paths[2])
        if len(self._plugin_paths) > 3:
            pyblish.api.deregister_plugin_path(self._plugin_paths[3])
        pyblish.api.deregister_host(self.name)
        self._plugin_paths.clear()
