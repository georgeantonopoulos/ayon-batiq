"""Render, Prerender and Image creators, each backed by a BATIQ Write node.

Like Nuke's write creators, each one makes a Write fed by the selected node and
sets it up from ``batiq/create/<Creator>`` settings: the local render path from
the anatomy work directory, file format, data type, compression, channels, the
output colorspace (an OCIO role or name resolved in the project's config) and
the frame range (the task's range with handles, or the Image's active frame).

A Write carries its instance in its ``ayon_publish`` metadata. Plain Writes
without one (made by hand, or by add-on versions before 0.1.7) are published as
renders, as before, and their settings are never touched.
"""
from abc import abstractmethod

import ayon_api
from ayon_core.lib import BoolDef, NumberDef, StringTemplate, get_version_from_path
from ayon_core.pipeline.colorspace import get_imageio_config_preset, get_ocio_config_colorspaces
from ayon_core.pipeline.create import CreatedInstance, Creator, CreatorError
from ayon_core.pipeline.template_data import get_template_data_with_names

# Instances stored by 0.1.6 and earlier used this identifier for every Write.
LEGACY_IDENTIFIER = "write"
# Creator settings -> BATIQ Write parameters.
WRITE_PARAMS = {
    "file_format": "write_format",
    "datatype": "write_datatype",
    "compression": "write_compression",
    "channels": "write_channels",
}
EXTENSIONS = {"exr": "exr", "tif": "tif", "dpx": "dpx", "png": "png", "jpeg": "jpg"}
# BATIQ's built-in names, used only when the project has no colour management.
UNMANAGED_COLORSPACES = {"scene_linear": "ACEScg", "rendering": "ACEScg", "compositing_linear": "ACEScg"}
# Instance changes that move the Write's render path or frame range.
CONTEXT_KEYS = ("productName", "folderPath", "task", "variant")


class BatiqWriteCreator(Creator):
    """Shared behaviour; subclasses set the product type and settings defaults."""

    settings_category = "batiq"
    product_base_type = "render"
    product_type = "render"
    icon = "sign-out"
    # Also collect plain Writes that no creator has claimed.
    claims_unmarked_writes = False

    # Overridden by batiq/create/<class name> settings.
    temp_rendering_path_template = "{work}/renders/batiq/{product[name]}/{product[name]}.{frame}.{ext}"
    review = True
    write = {"file_format": "exr", "datatype": "half", "compression": "zip",
             "channels": "rgba", "colorspace": "scene_linear"}

    @property
    @abstractmethod
    def identifier(self):
        """Abstract, so plugin discovery skips this base class."""

    def get_pre_create_attr_defs(self):
        return [BoolDef("use_selection", default=True, label="Use selection")]

    def get_instance_attr_defs(self):
        first, last = self._default_range()
        return [
            BoolDef("review", default=self.review, label="Review"),
            BoolDef(
                "use_custom_range", default=False, label="Custom frame range",
                tooltip="Render and publish First to Last instead of the task range with handles.",
            ),
            NumberDef("frame_start", label="First frame", decimals=0, default=first),
            NumberDef("frame_end", label="Last frame", decimals=0, default=last),
        ]

    def _default_range(self):
        """The current task's frame range with handles, for attribute defaults."""
        try:
            task = self.create_context.get_current_task_entity() or {}
        except Exception:  # an attribute default must not break the Publisher
            task = {}
        attrib = task.get("attrib") or {}
        if attrib.get("frameStart") is None or attrib.get("frameEnd") is None:
            return 1001, 1001
        return (int(attrib["frameStart"]) - int(attrib.get("handleStart") or 0),
                int(attrib["frameEnd"]) + int(attrib.get("handleEnd") or 0))

    # -- create ---------------------------------------------------------------
    def create(self, product_name, instance_data, pre_create_data):
        bridge = self.create_context.host.bridge
        input_id = None
        if pre_create_data.get("use_selection", True):
            selected = [node for node in bridge.call("nodes.list") or [] if node.get("selected")]
            if len(selected) > 1:
                raise CreatorError("Select a single node to write from.")
            if selected:
                if selected[0].get("kind") == "Write":
                    raise CreatorError("Select the node to render, not a Write node.")
                input_id = int(selected[0]["id"])
        taken = {inst.get("productName") for inst in self.create_context.instances}
        if product_name in taken:
            raise CreatorError(f"A product named {product_name!r} already exists in this workfile.")

        data = dict(instance_data, madeByCreator=True)
        data["creator_attributes"] = self._creator_attributes(pre_create_data)
        instance = CreatedInstance(
            product_base_type=self.product_base_type, product_type=self.product_type,
            product_name=product_name, data=data, creator=self,
        )
        params = {
            "name": product_name,
            "input": input_id,
            "metadata": {"ayon_publish": instance.data_to_store()},
        }
        params.update(self._write_params(instance))
        node = bridge.call("nodes.create_write", params)
        instance.transient_data["write_node_id"] = int(node["id"])
        self._add_instance_to_context(instance)
        return instance

    def _creator_attributes(self, pre_create_data):
        first, last = self._default_range()
        return {"review": self.review, "use_custom_range": False, "frame_start": first, "frame_end": last}

    # -- Write node setup -----------------------------------------------------
    def _write_params(self, instance):
        """Every Write parameter the instance's settings and context determine."""
        folder_path, task_name = instance["folderPath"], instance["task"]
        params = {WRITE_PARAMS[key]: str(value) for key, value in self.write.items()
                  if key in WRITE_PARAMS and value}
        params["path"] = self._render_path(instance["productName"], folder_path, task_name)
        params["create_directories"] = True
        output_space = self._output_space(folder_path, task_name)
        if output_space:
            params["output_space"] = output_space
        first, last = self._frame_range(instance)
        params.update(write_limit_range=True, write_first=first, write_last=last)
        return params

    def _extension(self):
        return EXTENSIONS[self.write.get("file_format") or "exr"]

    def _render_path(self, product_name, folder_path, task_name):
        project_name = self.create_context.get_current_project_name()
        anatomy = self.project_anatomy
        data = get_template_data_with_names(
            project_name, folder_path, task_name, self.create_context.host_name,
            settings=self.project_settings,
        )
        workfile = self.create_context.host.get_current_workfile()
        version = get_version_from_path(workfile) if workfile else None
        if version:
            data["version"] = int(version)
        data.update({
            "product": {"name": product_name, "type": self.product_type},
            "ext": self._extension(),
            # BATIQ numbers frames with '#' like Nuke; one per digit of padding.
            "frame": "#" * anatomy.templates_obj.frame_padding,
        })
        work = anatomy.get_template_item("work", "default", "directory").format_strict(data)
        data["work"] = str(work.normalized()).replace("\\", "/")
        path = StringTemplate(self.temp_rendering_path_template).format_strict(data)
        return str(path.normalized()).replace("\\", "/")

    def _output_space(self, folder_path, task_name):
        """The configured role or colorspace as a name in the project's OCIO config."""
        value = (self.write.get("colorspace") or "").strip()
        if not value:
            return None
        config = get_imageio_config_preset(
            self.create_context.get_current_project_name(), folder_path, task_name,
            self.create_context.host_name, anatomy=self.project_anatomy,
            project_settings=self.project_settings,
        )
        if not config or not config.get("path"):
            return UNMANAGED_COLORSPACES.get(value)
        colorspaces = get_ocio_config_colorspaces(config["path"])
        role = (colorspaces.get("roles") or {}).get(value)
        if role:
            return role["colorspace"]
        if value in colorspaces.get("colorspaces", {}):
            return value
        raise CreatorError(
            f"Colorspace {value!r} from batiq/create settings is neither a role nor a"
            f" colorspace in {config['path']}."
        )

    def _frame_range(self, instance):
        """The custom range when chosen, else the task's frame range including handles."""
        attributes = instance["creator_attributes"]
        if attributes.get("use_custom_range"):
            return int(attributes["frame_start"]), int(attributes["frame_end"])
        attrib = self._task_attributes(instance["folderPath"], instance["task"])
        if attrib.get("frameStart") is not None and attrib.get("frameEnd") is not None:
            return (int(attrib["frameStart"]) - int(attrib.get("handleStart") or 0),
                    int(attrib["frameEnd"]) + int(attrib.get("handleEnd") or 0))
        info = self.create_context.host.get_batiq_project_info() or {}
        return int(info.get("frame_start") or 1), int(info.get("frame_end") or 1)

    def _task_attributes(self, folder_path, task_name):
        context = self.create_context
        current = context.get_current_folder_entity() or {}
        if folder_path == current.get("path"):
            task = context.get_current_task_entity() or {}
            if task.get("name") == task_name:
                return task.get("attrib") or {}
        project_name = context.get_current_project_name()
        folder = ayon_api.get_folder_by_path(project_name, folder_path, fields={"id"})
        task = folder and ayon_api.get_task_by_name(project_name, folder["id"], task_name, fields={"attrib"})
        return (task or {}).get("attrib") or {}

    # -- collect --------------------------------------------------------------
    def collect_instances(self):
        host = self.create_context.host
        project_entity = self.create_context.get_current_project_entity()
        folder_entity = self.create_context.get_current_folder_entity()
        task_entity = self.create_context.get_current_task_entity()
        instances = []
        for node in host.bridge.call("nodes.list") or []:
            if node.get("kind") != "Write" or not node.get("enabled", True):
                continue
            stored = dict(node.get("metadata", {}).get("ayon_publish") or {})
            if stored.get("removed"):
                continue
            owner = stored.get("creator_identifier")
            if owner in (None, LEGACY_IDENTIFIER):
                if not self.claims_unmarked_writes:
                    continue
                # Unmarked Writes keep their node name as variant, as before 0.1.7.
                stored["variant"] = str(node.get("name") or self.default_variant)
            elif owner != self.identifier:
                continue
            variant = stored.get("variant") or self.default_variant
            data = stored
            data.setdefault("folderPath", folder_entity["path"])
            data.setdefault("task", task_entity["name"])
            product_name = self.get_product_name(
                project_name=project_entity["name"], project_entity=project_entity,
                folder_entity=folder_entity, task_entity=task_entity, variant=variant,
                host_name=self.create_context.host_name,
            )
            data.update({
                "productType": self.product_type,
                "productBaseType": self.product_base_type,
                "productName": product_name,
                "variant": variant,
                "creator_identifier": self.identifier,
            })
            instance = CreatedInstance(
                product_base_type=self.product_base_type, product_type=self.product_type,
                product_name=product_name, data=data, creator=self,
            )
            instance.transient_data["write_node_id"] = int(node["id"])
            self._add_instance_to_context(instance)
            if not stored.get("instance_id") or owner != self.identifier:
                self._store(instance)
            instances.append(instance)
        return instances

    def _store(self, instance, **write_params):
        self.create_context.host.bridge.call("nodes.update", {
            "id": str(instance.transient_data["write_node_id"]),
            "metadata": {"ayon_publish": instance.data_to_store()},
            **write_params,
        })

    def update_instances(self, update_list):
        for instance, changes in update_list:
            params = {}
            # Only Writes this creator set up follow the instance; plain Writes keep theirs.
            if instance.data.get("madeByCreator") and self._affects_write(changes):
                params = self._write_params(instance)
            self._store(instance, **params)

    @staticmethod
    def _affects_write(changes):
        try:
            changed = set(changes.changed_keys)
        except (AttributeError, TypeError):
            return True
        return bool(changed & set(CONTEXT_KEYS)) or "creator_attributes" in changed

    def remove_instances(self, instances):
        """Delete Writes this creator made; plain Writes are only unmarked."""
        bridge = self.create_context.host.bridge
        for instance in instances:
            write_id = str(instance.transient_data["write_node_id"])
            if instance.data.get("madeByCreator"):
                bridge.call("nodes.remove", {"id": write_id})
            else:
                bridge.call("nodes.update", {"id": write_id, "metadata": {"ayon_publish": {"removed": True}}})
            self._remove_instance_from_context(instance)


class CreateWriteRender(BatiqWriteCreator):
    identifier = "create_write_render"
    label = "Render (write)"
    product_base_type = product_type = "render"
    description = "Render the task's frame range through a Write node."
    default_variants = ["Main", "Mask"]
    default_variant = "Main"
    claims_unmarked_writes = True
    write = {"file_format": "exr", "datatype": "half", "compression": "zip",
             "channels": "rgb", "colorspace": "scene_linear"}


class CreateWritePrerender(BatiqWriteCreator):
    identifier = "create_write_prerender"
    label = "Prerender (write)"
    product_base_type = product_type = "prerender"
    description = "Render the task's frame range as an intermediate for other comps."
    default_variants = ["MOCKUP", "FLAT", "BG", "CONTAINER", "FG"]
    default_variant = "MOCKUP"


class CreateWriteImage(BatiqWriteCreator):
    identifier = "create_write_image"
    label = "Image (write)"
    product_base_type = product_type = "image"
    description = "Render a single still frame through a Write node."
    default_variants = ["StillFrame", "MPFrame", "LayoutFrame"]
    default_variant = "StillFrame"
    temp_rendering_path_template = "{work}/renders/batiq/{product[name]}/{product[name]}.{ext}"
    review = False
    write = {"file_format": "png", "datatype": "8", "compression": "zip",
             "channels": "rgba", "colorspace": "color_picking"}

    def _default_frame(self):
        try:
            info = self.create_context.host.get_batiq_project_info() or {}
        except Exception:  # the attribute default must not break the Publisher
            info = {}
        return int(info.get("frame_start") or info.get("frameStart") or 1)

    def get_pre_create_attr_defs(self):
        return super().get_pre_create_attr_defs() + [
            NumberDef("active_frame", label="Active frame", decimals=0, default=self._default_frame()),
        ]

    def get_instance_attr_defs(self):
        return [NumberDef("active_frame", label="Active frame", decimals=0, default=self._default_frame())]

    def _creator_attributes(self, pre_create_data):
        frame = pre_create_data.get("active_frame")
        return {"active_frame": int(frame if frame is not None else self._default_frame())}

    def _frame_range(self, instance):
        frame = int(instance["creator_attributes"]["active_frame"])
        return frame, frame
