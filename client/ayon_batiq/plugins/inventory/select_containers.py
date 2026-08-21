from ayon_core.pipeline import InventoryAction, registered_host


class SelectInGraph(InventoryAction):
    label = "Select in Graph"

    def process(self, containers):
        host = registered_host()
        ids = [str(item["objectName"]) for item in containers if self.is_compatible(item)]
        if not ids:
            return False
        host.bridge.call("nodes.select", {"ids": ids})
        return {"objectNames": ids, "options": {"clear": True}}
