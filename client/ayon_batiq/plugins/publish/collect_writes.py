import pyblish.api
from pathlib import Path
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import get_instance_staging_dir


class CollectWrites(pyblish.api.InstancePlugin):
    label = "Collect BATIQ Write"
    hosts = ["batiq"]
    families = ["render", "prerender", "image"]
    order = pyblish.api.CollectorOrder + 0.2

    def process(self, instance):
        if instance.data.get("productType") not in self.families:
            return
        write_id = (instance.data.get("transientData") or {}).get("write_node_id")
        if not isinstance(write_id, int) or isinstance(write_id, bool):
            raise RuntimeError("render instance requires explicit Write node ID")
        host = registered_host()
        if host is None:
            raise RuntimeError("BATIQ publish host is unavailable")
        info = host.get_batiq_project_info() or {}
        node = next((item for item in host.bridge.call("nodes.list") or [] if int(item["id"]) == write_id), None)
        if not node:
            raise RuntimeError("BATIQ Write node no longer exists")
        current_file = host.get_current_workfile()
        if not current_file:
            raise RuntimeError("save the BATIQ workfile before publishing")
        staging = instance.data.get("stagingDir") or get_instance_staging_dir(instance)
        limited = bool(node.get("write_limit_range"))
        output_format = node.get("write_format") or node.get("output_format") or "exr"
        write_path = str(node.get("path") or "")
        output = (
            instance.data.get("output")
            or (Path(write_path).name if write_path else None)
            or f"{instance.data.get('productName', 'render')}.####.{output_format}"
        )
        frame_start = int(node.get("write_first") if limited else info.get("frame_start", 1))
        frame_end = int(node.get("write_last") if limited else info.get("frame_end", 1))
        creator_attributes = instance.data.get("creator_attributes") or {}
        if instance.data["productType"] == "image":
            # A still: the creator's active frame, whatever the Write range says.
            active = creator_attributes.get("active_frame")
            frame_start = frame_end = int(active if active is not None else frame_start)
        instance.data.update({
            "writeNodeId": write_id,
            "writeNodeName": node.get("name"),
            "writePath": write_path,
            "currentFile": current_file,
            "stagingDir": staging,
            "frameStart": frame_start,
            "frameEnd": frame_end,
            # The Write range already is the full range; there are no extra handles.
            "handleStart": 0,
            "handleEnd": 0,
            "frameStartHandle": frame_start,
            "frameEndHandle": frame_end,
            "fps": info.get("fps") or instance.context.data.get("fps"),
            "resolutionWidth": info.get("resolutionWidth"),
            "resolutionHeight": info.get("resolutionHeight"),
            "pixelAspect": info.get("pixelAspect"),
            "review": bool(creator_attributes.get("review", instance.data["productType"] == "render")),
            "step": 1,
            "output": output,
            "outputFormat": output_format,
            "outputColorspace": node.get("output_space"),
            "colorspace": node.get("output_space"),
            "writeChannels": node.get("write_channels"),
        })
