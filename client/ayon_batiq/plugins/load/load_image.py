from __future__ import annotations
from typing import Any
from pathlib import Path
import warnings

from ayon_core.pipeline import AVALON_CONTAINER_ID, registered_host
from ayon_core.pipeline.load import LoaderPlugin

class LoadImage(LoaderPlugin):
    product_base_types = {"plate", "source", "image", "render", "render2d", "prerender", "review"}
    product_types = product_base_types
    representations = {"*"}
    extensions = {"exr", "png", "jpg", "jpeg"}
    label = "Load Image"
    def _path(self, context: dict[str, Any]) -> str:
        path = self.filepath_from_context(context)
        if not path or Path(path).suffix.lower().lstrip(".") not in self.extensions:
            raise ValueError("unsupported image representation")
        return str(path)
    def _metadata(self, context, name, namespace=None):
        representation = context.get("representation", {})
        return {"schema":"ayon:container-3.0", "id":AVALON_CONTAINER_ID, "name":name, "namespace":namespace or context.get("namespace", ""), "loader":"LoadImage", "representation":str(representation.get("id", "")), "project_name":context.get("project", {}).get("name", "")}
    @staticmethod
    def _input_space(value):
        if not value:
            return None
        normalized = "".join(
            character for character in str(value).strip().lower()
            if character not in " _-"
        )
        spaces = {
            "acescg": "ACEScg", "acesacescg": "ACEScg", "ap1": "ACEScg",
            "aces20651": "ACES2065-1", "aces": "ACES2065-1", "ap0": "ACES2065-1",
            "linearsrgb": "Linear sRGB", "linrec709": "Linear sRGB", "scenelinear": "Linear sRGB",
            "srgb": "sRGB - Texture", "srgbtexture": "sRGB - Texture",
            "srgbdisplay": "sRGB - Display", "outputsrgb": "sRGB - Display",
            "rec709": "Rec.709", "bt709": "Rec.709",
        }
        mapped = spaces.get(normalized)
        if mapped is None:
            warnings.warn(
                f"AYON colorspace {value!r} has no BATIQ v0.1 mapping; using the Read default",
                RuntimeWarning,
                stacklevel=2,
            )
        return mapped
    def _read_params(self, representation):
        data = representation.get("data", {})
        context = representation.get("context", {})
        attrib = representation.get("attrib", {})
        return {
            "read_first": context.get("frameStart", attrib.get("frameStart")),
            "read_last": context.get("frameEnd", attrib.get("frameEnd")),
            "frame_offset": data.get("frameOffset"),
            "input_space": self._input_space(
                data.get("colorspace") or attrib.get("colorspace") or context.get("colorspace")
            ),
        }
    def load(self, context, name=None, namespace=None, options=None):
        path = self._path(context); name = name or context.get("product", {}).get("name", "image")
        params = {"path":path, "name":name, "metadata":{"ayon":self._metadata(context, name, namespace)}}
        params.update(self._read_params(context.get("representation", {})))
        return self._bridge().call("nodes.create_read", params)
    def update(self, container, context):
        representation = context["representation"]
        path = self._path(context); node_id = str(container["objectName"])
        data = dict(container); data["representation"] = str(representation.get("id", "")); data.pop("objectName", None); data.pop("_node", None)
        params = {"id":node_id, "path":path, "metadata":{"ayon":data}}
        params.update(self._read_params(representation))
        return self._bridge().call("nodes.update", params)
    def switch(self, container, context): return self.update(container, context)
    def remove(self, container): return self._bridge().call("nodes.remove", {"id":str(container["objectName"])})
    @staticmethod
    def _bridge():
        host = registered_host()
        if host is None or not hasattr(host, "bridge"):
            raise RuntimeError("BATIQ host bridge is unavailable")
        return host.bridge
