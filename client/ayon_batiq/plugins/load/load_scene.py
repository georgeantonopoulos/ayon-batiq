"""Load a USD or Alembic product into a BATIQ Set, as Nuke's GeoReference loader does.

The Set references the published file (never copies it) and renders it through
the scene's first camera unless the artist picks another. Its own edits to the
file's prims are keyed by prim path, so they survive a version update.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ayon_core.pipeline.load import LoaderPlugin

from ayon_batiq.api.loading import bridge, container_metadata, updated_metadata

# The formats BATIQ's Set reads (`SCENE_FORMATS` in BATIQ's src/scene3d/mod.rs).
SCENE_EXTENSIONS = {"usd", "usda", "usdc", "usdz", "abc"}


class LoadScene(LoaderPlugin):
    # Any product: few hosts publish a dedicated USD product type, and USD
    # shots, layouts, cameras and models all load the same way (Nuke's
    # GeoImport, GeoReference and USD camera loaders take "*" too).
    product_base_types = {"*"}
    product_types = product_base_types
    representations = {"*"}
    extensions = SCENE_EXTENSIONS
    label = "Load USD into Set"
    icon = "cube"
    color = "orange"
    order = 2

    def _path(self, context: dict[str, Any]) -> str:
        path = self.filepath_from_context(context)
        if not path or Path(path).suffix.lower().lstrip(".") not in self.extensions:
            raise ValueError("unsupported scene representation")
        return str(path).replace("\\", "/")

    def load(self, context, name=None, namespace=None, options=None):
        name = name or context.get("product", {}).get("name", "scene")
        return bridge().call("nodes.create_set", {
            "path": self._path(context), "name": name,
            "metadata": {"ayon": container_metadata(context, name, namespace, "LoadScene")},
        })

    def update(self, container, context):
        return bridge().call("nodes.update", {
            "id": str(container["objectName"]), "path": self._path(context),
            "metadata": {"ayon": updated_metadata(container, context)},
        })

    def switch(self, container, context): return self.update(container, context)

    def remove(self, container): return bridge().call("nodes.remove", {"id": str(container["objectName"])})
