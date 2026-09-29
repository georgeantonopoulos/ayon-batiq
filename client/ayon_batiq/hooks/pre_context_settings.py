import json

from ayon_applications import LaunchTypes, PreLaunchHook

from ayon_batiq.context import ENV_KEY, settings_from_attrib


class BatiqContextSettingsHook(PreLaunchHook):
    """Pass the task's frame range, fps and format to BATIQ's startup."""

    order = 10
    hosts = {"batiq"}
    launch_types = {LaunchTypes.local}

    def execute(self):
        task_entity = self.data.get("task_entity")
        if not task_entity:
            self.log.info("No task in the launch context; BATIQ keeps its defaults.")
            return
        settings = self.data["project_settings"].get("batiq", {}).get("workfile", {})
        if not settings.get("apply_context_on_launch", True):
            return
        values = settings_from_attrib(task_entity["attrib"])
        if values:
            self.launch_context.env[ENV_KEY] = json.dumps(values)
