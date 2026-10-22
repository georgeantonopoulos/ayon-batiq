"""Load a USD or Alembic product into a BATIQ Set, as Nuke's GeoReference loader does.

The Set references the published file (never copies it) and renders it through
the scene's first camera unless the artist picks another. Its own edits to the
file's prims are keyed by prim path, so they survive a version update.

A Set reads the file at the project frame (checked with headless renders of an
animated USD in BATIQ 0.2.38) and has no frame offset or range parameters, so,
as in Nuke's Alembic loader, the version's frame range and fps are only recorded
on the container.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ayon_core.pipeline.load import LoaderPlugin

from ayon_batiq.api.loading import bridge, container_metadata, frame_range, normalize_path, updated_metadata

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
        return normalize_path(path)

    @staticmethod
    def _version_data(context: dict[str, Any], path: str) -> dict[str, Any]:
        """The loaded file and the version's frame range, fps and number, kept on the container."""
        version = context.get("version", {})
        first, last = frame_range(context)
        return {
            "path": path, "frameStart": first, "frameEnd": last,
            "fps": version.get("attrib", {}).get("fps"), "version": version.get("version"),
        }

    def load(self, context, name=None, namespace=None, options=None):
        name = name or context.get("product", {}).get("name", "scene")
        path = self._path(context)
        metadata = container_metadata(context, name, namespace, "LoadScene")
        metadata.update(self._version_data(context, path))
        return bridge().call("nodes.create_set", {"path": path, "name": name, "metadata": {"ayon": metadata}})

    def update(self, container, context):
        path = self._path(context)
        metadata = updated_metadata(container, context)
        metadata.update(self._version_data(context, path))
        params = {"id": str(container["objectName"]), "path": path, "metadata": {"ayon": metadata}}
        # The file this container loaded, so the Set swaps that one wherever the artist moved it.
        if container.get("path"):
            params["previous_path"] = container["path"]
        return bridge().call("nodes.update", params)

    def switch(self, container, context): return self.update(container, context)

    def remove(self, container): return bridge().call("nodes.remove", {"id": str(container["objectName"])})
