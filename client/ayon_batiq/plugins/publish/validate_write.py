"""Write node validators, as in Nuke: node setup, frame range and folder context."""
import pyblish.api
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import (
    OptionalPyblishPluginMixin,
    PublishValidationError,
    RepairAction,
)

WRITE_FAMILIES = ["render", "prerender", "image"]
# Write parameters compared with the creator's settings (the range has its own validator).
SETUP_KEYS = ("write_format", "write_datatype", "write_compression", "write_channels", "output_space", "path")
LABELS = {
    "write_format": "File format", "write_datatype": "Data type", "write_compression": "Compression",
    "write_channels": "Channels", "output_space": "Colorspace", "path": "Render path",
}
# BATIQ treats "16" as half float for EXR.
_DATATYPES = {"16": "half"}


def _bridge():
    host = registered_host()
    if host is None:
        raise PublishValidationError("The BATIQ host is not available.")
    return host.bridge


def _write_node(instance):
    write_id = (instance.data.get("transientData") or {}).get("write_node_id")
    node = next((item for item in _bridge().call("nodes.list") or []
                 if int(item["id"]) == int(write_id)), None)
    if node is None:
        raise PublishValidationError("The instance's Write node no longer exists.")
    return node


def _creator_and_instance(instance):
    """The instance's creator and CreatedInstance, from the Publisher's create context."""
    create_context = instance.context.data.get("create_context")
    if create_context is None:
        return None, None
    created = create_context.get_instance_by_id(instance.data.get("instance_id"))
    creator = create_context.creators.get(instance.data.get("creator_identifier"))
    return creator, created


def _normalized(key, value):
    if value is None:
        return None
    value = str(value).strip()
    if key == "path":
        return value.replace("\\", "/")
    value = value.lower()
    return _DATATYPES.get(value, value) if key == "write_datatype" else value


class ValidateBatiqWrite(pyblish.api.InstancePlugin, OptionalPyblishPluginMixin):
    """The Write is set up as its creator's settings say (format, colorspace, path...)."""

    label = "Validate Write Node"
    hosts = ["batiq"]
    families = WRITE_FAMILIES
    order = pyblish.api.ValidatorOrder
    actions = [RepairAction]
    settings_category = "batiq"
    optional = True

    def process(self, instance):
        if not self.is_active(instance.data):
            return
        if not instance.data.get("madeByCreator"):
            self.log.debug("A plain Write keeps its own settings.")
            return
        expected = self._expected(instance)
        if expected is None:
            self.log.debug("No create context; nothing to compare.")
            return
        node = _write_node(instance)
        compared = [key for key in SETUP_KEYS if key in expected]
        if _normalized("write_format", expected.get("write_format")) != "exr":
            compared = [key for key in compared if key != "write_compression"]
        wrong = {
            key: (node.get(key), expected[key]) for key in compared
            if _normalized(key, node.get(key)) != _normalized(key, expected[key])
        }
        if wrong:
            rows = "\n".join(f"- {LABELS[key]}: Write {have!r}, expected {want!r}"
                             for key, (have, want) in wrong.items())
            raise PublishValidationError(
                f"Write {node.get('name')!r} differs from its creator settings:\n{rows}",
                title="Write node settings",
                description=(
                    "### Write node differs from the creator settings\n\n"
                    f"{rows}\n\nUse **Repair** to apply the settings from"
                    " *batiq/create* again."
                ),
            )

    @staticmethod
    def _expected(instance):
        creator, created = _creator_and_instance(instance)
        if creator is None or created is None:
            return None
        return creator._write_params(created)

    @classmethod
    def repair(cls, instance):
        expected = cls._expected(instance)
        if expected is None:
            raise PublishValidationError("Repair needs the Publisher's create context.")
        params = {key: value for key, value in expected.items() if key in SETUP_KEYS + ("create_directories",)}
        write_id = instance.data["transientData"]["write_node_id"]
        _bridge().call("nodes.update", {"id": str(write_id), **params})


class ValidateBatiqWriteFrameRange(pyblish.api.InstancePlugin, OptionalPyblishPluginMixin):
    """Renders cover the task range with handles, or a valid custom range."""

    label = "Validate Frame Range"
    hosts = ["batiq"]
    families = ["render", "prerender"]
    # After CollectWrites has worked out the range.
    order = pyblish.api.ValidatorOrder
    actions = [RepairAction]
    settings_category = "batiq"
    optional = True

    def process(self, instance):
        if not self.is_active(instance.data):
            return
        first, last = int(instance.data["frameStartHandle"]), int(instance.data["frameEndHandle"])
        if instance.data.get("customFrameRange"):
            if last < first:
                raise PublishValidationError(
                    f"Custom frame range {first}-{last} ends before it starts.",
                    title="Custom frame range",
                    description="### Custom frame range is empty\n\nSet *Last frame* to or after *First frame*.",
                )
            return
        from ayon_batiq.plugins.publish.collect_writes import CollectWrites
        task_range = CollectWrites._task_range(instance)
        if task_range is None:
            self.log.debug("The task has no frame range; nothing to compare.")
            return
        start, end, handle_start, handle_end = task_range
        want = (start - handle_start, end + handle_end)
        if (first, last) != want:
            raise PublishValidationError(
                f"The Write renders {first}-{last}; the task with handles is {want[0]}-{want[1]}.",
                title="Frame range differs from the task",
                description=(
                    f"### Frame range differs from the task\n\nThe Write renders {first}-{last}, the"
                    f" task range with handles is {want[0]}-{want[1]}.\n\nUse **Repair** to render the"
                    " task range, or turn on *Custom frame range* for this instance to publish"
                    " a different range on purpose."
                ),
            )

    @classmethod
    def repair(cls, instance):
        from ayon_batiq.plugins.publish.collect_writes import CollectWrites
        task_range = CollectWrites._task_range(instance)
        if task_range is None:
            raise PublishValidationError("The task has no frame range to repair to.")
        start, end, handle_start, handle_end = task_range
        write_id = instance.data["transientData"]["write_node_id"]
        _bridge().call("nodes.update", {
            "id": str(write_id), "write_limit_range": True,
            "write_first": start - handle_start, "write_last": end + handle_end,
        })


class ValidateBatiqInstanceContext(pyblish.api.InstancePlugin, OptionalPyblishPluginMixin):
    """The instance publishes to the folder and task the workfile is opened in."""

    label = "Validate Folder Context"
    hosts = ["batiq"]
    families = WRITE_FAMILIES
    order = pyblish.api.ValidatorOrder
    actions = [RepairAction]
    settings_category = "batiq"
    optional = True

    def process(self, instance):
        if not self.is_active(instance.data):
            return
        current = (instance.context.data.get("folderPath"), instance.context.data.get("task"))
        target = (instance.data.get("folderPath"), instance.data.get("task"))
        if None in current or target == current:
            return
        raise PublishValidationError(
            f"Instance publishes to {target[0]} / {target[1]}, but the workfile is in"
            f" {current[0]} / {current[1]}.",
            title="Folder context",
            description=(
                "### Instance context differs from the workfile\n\n"
                f"The instance publishes to **{target[0]} / {target[1]}**, the workfile is in"
                f" **{current[0]} / {current[1]}**.\n\nUse **Repair** to publish to the workfile's"
                " context, or turn this validator off to publish elsewhere on purpose."
            ),
        )

    @classmethod
    def repair(cls, instance):
        _creator, created = _creator_and_instance(instance)
        if created is None:
            raise PublishValidationError("Repair needs the Publisher's create context.")
        created["folderPath"] = instance.context.data["folderPath"]
        created["task"] = instance.context.data["task"]
        instance.context.data["create_context"].save_changes()
