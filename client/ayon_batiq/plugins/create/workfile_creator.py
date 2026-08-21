from ayon_core.pipeline.create import AutoCreator, CreatedInstance

class WorkfileCreator(AutoCreator):
    identifier = "workfile"
    product_base_type = "workfile"
    product_type = "workfile"
    default_variant = "Main"
    def create(self, options=None):
        return None
    def collect_instances(self):
        host = self.create_context.host
        path = host.get_current_workfile()
        if not path: return []
        project_entity = self.create_context.get_current_project_entity()
        folder_entity = self.create_context.get_current_folder_entity()
        task_entity = self.create_context.get_current_task_entity()
        variant = self.default_variant
        product_name = self.get_product_name(
            project_name=project_entity["name"], project_entity=project_entity,
            folder_entity=folder_entity, task_entity=task_entity, variant=variant,
            host_name=self.create_context.host_name,
        )
        stored = host.bridge.call("project.get_metadata", {"namespace": "ayon_workfile"}) or {}
        data = dict(stored)
        data.update({
            "productType": self.product_type,
            "productBaseType": self.product_base_type,
            "productName": product_name,
            "path": path,
            "folderPath": folder_entity["path"], "task": task_entity["name"],
            "variant": variant,
            "creator_identifier": self.identifier,
        })
        data.update(self.get_dynamic_data(
            project_entity["name"], folder_entity, task_entity, variant,
            self.create_context.host_name, data,
        ))
        product_type = data.get("productType") or self.product_type
        instance = CreatedInstance(
            product_base_type=self.product_base_type, product_type=product_type,
            product_name=data["productName"], data=data, creator=self,
        )
        self._add_instance_to_context(instance)
        if not stored.get("instance_id"):
            host.bridge.call("project.set_metadata", {
                "namespace": "ayon_workfile", "data": instance.data_to_store(),
            })
        return [instance]

    def update_instances(self, update_list):
        for instance, _changes in update_list:
            self.create_context.host.bridge.call("project.set_metadata", {
                "namespace": "ayon_workfile", "data": instance.data_to_store(),
            })
