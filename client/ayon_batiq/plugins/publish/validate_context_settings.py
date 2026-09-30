import pyblish.api
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import (
    OptionalPyblishPluginMixin,
    PublishValidationError,
    RepairAction,
)

from ayon_batiq.context import differences, settings_from_attrib

LABELS = {
    "frame_start": "First frame (with handles)",
    "frame_end": "Last frame (with handles)",
    "fps": "FPS",
    "width": "Width",
    "height": "Height",
    "pixel_aspect": "Pixel aspect",
}


def _current(info):
    return {
        "frame_start": info.get("frame_start"),
        "frame_end": info.get("frame_end"),
        "fps": info.get("fps"),
        "width": info.get("resolutionWidth"),
        "height": info.get("resolutionHeight"),
        "pixel_aspect": info.get("pixelAspect"),
    }


class ValidateBatiqContextSettings(pyblish.api.InstancePlugin, OptionalPyblishPluginMixin):
    """BATIQ project frame range, fps and format match the AYON task.

    On the workfile instance, like Nuke's Validate Script Attributes, so artists
    find its on/off toggle with the workfile.
    """

    label = "Validate Context Settings"
    hosts = ["batiq"]
    families = ["workfile"]
    order = pyblish.api.ValidatorOrder
    actions = [RepairAction]
    settings_category = "batiq"
    optional = True

    def process(self, instance):
        if not self.is_active(instance.data):
            return
        context = instance.context
        task_entity = context.data.get("taskEntity")
        if not task_entity:
            self.log.debug("No task in the publish context; nothing to compare.")
            return
        expected = settings_from_attrib(task_entity["attrib"])
        info = registered_host().get_batiq_project_info() or {}
        changed = differences(expected, _current(info))
        if changed:
            rows = "\n".join(
                f"- {LABELS[key]}: BATIQ {current!r}, task {wanted!r}"
                for key, (current, wanted) in changed.items()
            )
            raise PublishValidationError(
                f"BATIQ project settings differ from the task:\n{rows}",
                title="Project settings differ from the task",
                description=(
                    "### BATIQ project settings differ from the AYON task\n\n"
                    f"{rows}\n\nUse **Repair** or *AYON > Apply All Settings*."
                ),
            )

    @classmethod
    def repair(cls, instance):
        registered_host().apply_context_settings()
