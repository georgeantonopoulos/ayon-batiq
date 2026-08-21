from pathlib import Path
import pyblish.api


class CollectWorkfile(pyblish.api.InstancePlugin):
    label = "Collect BATIQ Workfile"
    hosts = ["batiq"]
    families = ["workfile"]
    order = pyblish.api.CollectorOrder + 0.1

    def process(self, instance):
        if instance.data.get("productType") != "workfile":
            return
        path = Path(instance.data["path"])
        instance.data["representations"] = [{
            "name": "batiq",
            "ext": "batiq",
            "files": path.name,
            "stagingDir": str(path.parent),
        }]
