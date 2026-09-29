from __future__ import annotations
from typing import Any
from pathlib import Path

from ayon_core.pipeline import AVALON_CONTAINER_ID, registered_host
from ayon_core.pipeline.load import LoaderPlugin
from ayon_core.settings import get_project_settings

from ayon_batiq.colorspace import to_batiq

# Formats BATIQ 0.2.26's Read decodes (checked with headless renders; TIFF and DPX fail).
IMAGE_EXTENSIONS = {"exr", "png", "jpg", "jpeg"}
VIDEO_EXTENSIONS = {"mov", "mp4", "m4v", "mkv"}


class LoadImage(LoaderPlugin):
    product_base_types = {"plate", "source", "image", "render", "render2d", "prerender", "review"}
    product_types = product_base_types
    representations = {"*"}
    extensions = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    label = "Load Image or Movie"
    def _path(self, context: dict[str, Any]) -> str:
        path = self.filepath_from_context(context)
        if not path or Path(path).suffix.lower().lstrip(".") not in self.extensions:
            raise ValueError("unsupported image representation")
        return str(path)
    def _metadata(self, context, name, namespace=None):
        representation = context.get("representation", {})
        return {"schema":"ayon:container-3.0", "id":AVALON_CONTAINER_ID, "name":name, "namespace":namespace or context.get("namespace", ""), "loader":"LoadImage", "representation":str(representation.get("id", "")), "project_name":context.get("project", {}).get("name", "")}
    @staticmethod
    def _frame_range(context):
        """First and last frame including handles, from the version or representation."""
        representation = context.get("representation", {})
        sources = (
            context.get("version", {}).get("attrib", {}),
            representation.get("context", {}),
            representation.get("attrib", {}),
        )
        def value(key):
            return next((source[key] for source in sources if source.get(key) is not None), None)
        start, end = value("frameStart"), value("frameEnd")
        if start is None or end is None:
            return None, None
        return int(start) - int(value("handleStart") or 0), int(end) + int(value("handleEnd") or 0)
    @staticmethod
    def _source_colorspace(representation):
        data = representation.get("data", {})
        colorspace_data = data.get("colorspaceData") or {}
        return (
            colorspace_data.get("colorspace") or data.get("colorspace")
            or representation.get("attrib", {}).get("colorspace")
            or representation.get("context", {}).get("colorspace")
        )
    def _read_params(self, context, path):
        representation = context.get("representation", {})
        first, last = self._frame_range(context)
        is_video = Path(path).suffix.lower().lstrip(".") in VIDEO_EXTENSIONS
        is_sequence = len(representation.get("files") or []) > 1 or "frame" in representation.get("context", {})
        if is_video and first is not None:
            # Video frames count from 1; BATIQ reads source frame = project frame + offset.
            params = {"read_first": 1, "read_last": last - first + 1, "frame_offset": 1 - first}
        elif is_sequence and first is not None:
            params = {"read_first": first, "read_last": last, "frame_offset": 0}
        else:
            params = {"frame_offset": 0}
        project_name = context.get("project", {}).get("name")
        rules = get_project_settings(project_name).get("batiq", {}).get("colorspace", {}).get("rules") if project_name else None
        params["input_space"] = to_batiq(self._source_colorspace(representation), rules)
        return params
    def load(self, context, name=None, namespace=None, options=None):
        path = self._path(context); name = name or context.get("product", {}).get("name", "image")
        params = {"path":path, "name":name, "metadata":{"ayon":self._metadata(context, name, namespace)}}
        params.update(self._read_params(context, path))
        return self._bridge().call("nodes.create_read", params)
    def update(self, container, context):
        representation = context["representation"]
        path = self._path(context); node_id = str(container["objectName"])
        data = dict(container); data["representation"] = str(representation.get("id", "")); data.pop("objectName", None); data.pop("_node", None)
        params = {"id":node_id, "path":path, "metadata":{"ayon":data}}
        params.update(self._read_params(context, path))
        return self._bridge().call("nodes.update", params)
    def switch(self, container, context): return self.update(container, context)
    def remove(self, container): return self._bridge().call("nodes.remove", {"id":str(container["objectName"])})
    @staticmethod
    def _bridge():
        host = registered_host()
        if host is None or not hasattr(host, "bridge"):
            raise RuntimeError("BATIQ host bridge is unavailable")
        return host.bridge
