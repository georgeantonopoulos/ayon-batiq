"""Render, Prerender and Image creators, each backed by a BATIQ Write node.

Like Nuke's write creators, each one makes a Write fed by the selected node.
A Write carries its instance in its ``ayon_publish`` metadata; plain Writes
without one (made by hand, or by add-on versions before 0.1.7) are published
as renders, as before.
"""
from abc import abstractmethod

from ayon_core.lib import BoolDef, NumberDef
from ayon_core.pipeline.create import CreatedInstance, Creator, CreatorError

# Instances stored by 0.1.6 and earlier used this identifier for every Write.
LEGACY_IDENTIFIER = "write"


class BatiqWriteCreator(Creator):
    """Shared behaviour; subclasses set the product type and frame handling."""

    product_base_type = "render"
    product_type = "render"
    icon = "sign-out"
    review_default = True
    # Also collect plain Writes that no creator has claimed.
    claims_unmarked_writes = False

    @property
    @abstractmethod
    def identifier(self):
        """Abstract, so plugin discovery skips this base class."""

    def get_pre_create_attr_defs(self):
        return [BoolDef("use_selection", default=True, label="Use selection")]

    def get_instance_attr_defs(self):
        return [BoolDef("review", default=self.review_default, label="Review")]

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

        data = dict(instance_data)
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
        return {"review": self.review_default}

    def _write_params(self, instance):
        """Write parameters the instance controls; renders keep the Write's own range."""
        return {}

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
            product_name = self.get_product_name(
                project_name=project_entity["name"], project_entity=project_entity,
                folder_entity=folder_entity, task_entity=task_entity, variant=variant,
                host_name=self.create_context.host_name,
            )
            data = stored
            data.update({
                "productType": self.product_type,
                "productBaseType": self.product_base_type,
                "productName": product_name,
                "folderPath": folder_entity["path"], "task": task_entity["name"],
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
        for instance, _changes in update_list:
            self._store(instance, **self._write_params(instance))

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
    description = "Render the full frame range through a Write node."
    default_variants = ["Main", "Mask"]
    default_variant = "Main"
    claims_unmarked_writes = True

    def create(self, product_name, instance_data, pre_create_data):
        instance_data = dict(instance_data, madeByCreator=True)
        return super().create(product_name, instance_data, pre_create_data)


class CreateWritePrerender(BatiqWriteCreator):
    identifier = "create_write_prerender"
    label = "Prerender (write)"
    product_base_type = product_type = "prerender"
    description = "Render the full frame range as an intermediate for other comps."
    default_variants = ["Key01", "Bg01", "Fg01", "Branch01", "Part01"]
    default_variant = "Key01"
    review_default = False

    def create(self, product_name, instance_data, pre_create_data):
        instance_data = dict(instance_data, madeByCreator=True)
        return super().create(product_name, instance_data, pre_create_data)


class CreateWriteImage(BatiqWriteCreator):
    identifier = "create_write_image"
    label = "Image (write)"
    product_base_type = product_type = "image"
    description = "Render a single still frame through a Write node."
    default_variants = ["StillFrame", "MPFrame", "LayoutFrame"]
    default_variant = "StillFrame"
    review_default = False

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

    def create(self, product_name, instance_data, pre_create_data):
        instance_data = dict(instance_data, madeByCreator=True)
        return super().create(product_name, instance_data, pre_create_data)

    def _creator_attributes(self, pre_create_data):
        frame = pre_create_data.get("active_frame")
        return {"active_frame": int(frame if frame is not None else self._default_frame())}

    def _write_params(self, instance):
        frame = int(instance["creator_attributes"]["active_frame"])
        return {"write_limit_range": True, "write_first": frame, "write_last": frame}
