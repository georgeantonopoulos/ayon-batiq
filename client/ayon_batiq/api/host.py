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
        self._plugin_paths: dict = {}

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

    def apply_context_settings(self, keys=None) -> dict[str, Any]:
        """Set BATIQ's frame range, fps and format from the current AYON task."""
        from ayon_core.pipeline.context_tools import get_current_task_entity

        from ..context import settings_from_attrib

        task_entity = get_current_task_entity(fields={"attrib"})
        if not task_entity:
            raise RuntimeError("no current AYON task to take settings from")
        values = settings_from_attrib(task_entity["attrib"])
        if keys is not None:
            values = {key: value for key, value in values.items() if key in keys}
        return self.bridge.call("project.set_settings", values)

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
        self._plugin_paths = {
            register_creator_plugin_path: str(plugins / "create"),
            register_loader_plugin_path: str(plugins / "load"),
            register_inventory_action_path: str(plugins / "inventory"),
            pyblish.api.register_plugin_path: str(plugins / "publish"),
        }
        pyblish.api.register_host(self.name)
        for register, path in self._plugin_paths.items():
            register(path)

    def uninstall(self):
        import pyblish.api

        deregister = {
            register_creator_plugin_path: deregister_creator_plugin_path,
            register_loader_plugin_path: deregister_loader_plugin_path,
            register_inventory_action_path: deregister_inventory_action_path,
            pyblish.api.register_plugin_path: pyblish.api.deregister_plugin_path,
        }
        for register, path in self._plugin_paths.items():
            deregister[register](path)
        pyblish.api.deregister_host(self.name)
        self._plugin_paths.clear()
