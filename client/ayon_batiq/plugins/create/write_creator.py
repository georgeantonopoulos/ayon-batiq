from ayon_core.pipeline.create import AutoCreator, CreatedInstance

class WriteCreator(AutoCreator):
    identifier = "write"
    product_base_type = "render"
    product_type = "render"
    default_variant = "Main"
    def create(self, options=None):
        return None
    def collect_instances(self):
        host = self.create_context.host
        project_entity = self.create_context.get_current_project_entity()
        folder_entity = self.create_context.get_current_folder_entity()
        task_entity = self.create_context.get_current_task_entity()
        nodes = host.bridge.call("nodes.list") or []
        instances = []
        for node in nodes:
            if node.get("kind") != "Write" or not node.get("enabled", True):
                continue
            variant = str(node.get("name") or self.default_variant)
            product_name = self.get_product_name(
                project_name=project_entity["name"], project_entity=project_entity,
                folder_entity=folder_entity, task_entity=task_entity, variant=variant,
                host_name=self.create_context.host_name,
            )
            stored = node.get("metadata", {}).get("ayon_publish") or {}
            data = dict(stored)
            data.update({
                "productType": self.product_type,
                "productBaseType": self.product_base_type,
                "productName": product_name,
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
                product_name=product_name, data=data, creator=self,
            )
            instance.transient_data["write_node_id"] = int(node["id"])
            self._add_instance_to_context(instance)
            if not stored.get("instance_id"):
                host.bridge.call("nodes.update", {
                    "id": str(node["id"]),
                    "metadata": {"ayon_publish": instance.data_to_store()},
                })
            instances.append(instance)
        return instances

    def update_instances(self, update_list):
        for instance, _changes in update_list:
            write_id = instance.transient_data["write_node_id"]
            self.create_context.host.bridge.call("nodes.update", {
                "id": str(write_id),
                "metadata": {"ayon_publish": instance.data_to_store()},
            })
