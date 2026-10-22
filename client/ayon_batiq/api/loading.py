"""Helpers the BATIQ loaders share: the container record, frame range, paths and the host bridge."""
from __future__ import annotations

from typing import Any

from ayon_core.pipeline import AVALON_CONTAINER_ID, registered_host


def container_metadata(context: dict[str, Any], name: str, namespace: str | None, loader: str) -> dict[str, Any]:
    """The ``ayon`` metadata that makes a node a loaded container."""
    representation = context.get("representation", {})
    return {
        "schema": "ayon:container-3.0", "id": AVALON_CONTAINER_ID, "name": name,
        "namespace": namespace or context.get("namespace", ""), "loader": loader,
        "representation": str(representation.get("id", "")),
        "project_name": context.get("project", {}).get("name", ""),
    }


def updated_metadata(container: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """The container's metadata pointing at the representation in ``context``."""
    data = dict(container)
    data["representation"] = str(context["representation"].get("id", ""))
    data.pop("objectName", None)
    data.pop("_node", None)
    return data


def frame_range(context: dict[str, Any]) -> tuple[int | None, int | None]:
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


def normalize_path(path: str) -> str:
    """The path with forward slashes, which BATIQ reads on every platform."""
    return str(path).replace("\\", "/")


def bridge():
    host = registered_host()
    if host is None or not hasattr(host, "bridge"):
        raise RuntimeError("BATIQ host bridge is unavailable")
    return host.bridge
