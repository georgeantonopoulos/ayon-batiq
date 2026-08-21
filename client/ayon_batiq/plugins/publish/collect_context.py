import pyblish.api
from ayon_core.pipeline import registered_host


class CollectBatiqContext(pyblish.api.ContextPlugin):
    label = "Collect BATIQ Context"
    hosts = ["batiq"]
    order = pyblish.api.CollectorOrder

    def process(self, context):
        host = registered_host()
        context.data["hostName"] = "batiq"
        context.data["hostVersion"] = context.data.get("hostVersion", "unknown")
        if host is not None:
            info = host.get_batiq_project_info()
            context.data.update({
                "currentFile": host.get_current_workfile(),
                "frameStart": info.get("frame_start", 1), "frameEnd": info.get("frame_end", 1),
                "fps": info.get("fps"), "resolutionWidth": info.get("resolutionWidth"),
                "resolutionHeight": info.get("resolutionHeight"), "pixelAspect": info.get("pixelAspect"),
                "hostVersion": info.get("hostVersion", context.data["hostVersion"]),
                "batiqExecutable": info.get("executable"),
            })
