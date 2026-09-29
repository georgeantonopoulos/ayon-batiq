"""Display-referred review frames baked by BATIQ's own view transform.

The review project reads the EXRs the publish already rendered and writes them
through BATIQ's built-in output transform, so reviews show exactly the
published pixels. BATIQ 0.2.26 writes display-referred PNG/JPEG with the ACES 2.0
output transform, matching the ACES 2.0 studio OCIO config (v3.0.0,
sRGB - Display / ACES 2.0 - SDR 100 nits) to within one 8-bit code value. The
project view does not change Write output in 0.2.26 ("Aces13" gives identical
pixels), so it is not offered as a setting.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

REVIEW_VIEW = "Aces20"
EXTENSIONS = {"png": "png", "jpg": "jpeg"}
# Display-referred output; sRGB - Texture would skip the output transform.
DISPLAY_OUTPUT_SPACE = "sRGB - Display"
READ_NODE_ID, WRITE_NODE_ID = 1, 2


class ReviewProjectError(RuntimeError):
    """The source project cannot be turned into a review project."""


def build_project(
    source: Mapping[str, Any],
    *,
    write_node: int,
    first_file: str,
    input_space: str,
    frames: tuple[int, int],
    extension: str,
) -> dict[str, Any]:
    """A Read -> Write project baking ``first_file``'s sequence for review."""
    if extension not in EXTENSIONS:
        raise ReviewProjectError(f"unsupported review extension {extension!r}")
    if source.get("format") != "BATIQ Node Compositor":
        raise ReviewProjectError("not a BATIQ project")
    try:
        template = next(n for n in source["graph"]["nodes"] if int(n["id"]) == int(write_node))
        settings = source["project_settings"]
        color = source["color"]
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise ReviewProjectError(f"BATIQ project has no Write node {write_node}") from exc

    start, end = frames
    read = copy.deepcopy(template)
    read.update(id=READ_NODE_ID, kind="Read", name="ReviewSource", inputs=[], enabled=True)
    read["params"].update(
        path=str(first_file), read_first=start, read_last=end, frame_offset=0,
        input_space=input_space, missing_frame="hold",
    )
    write = copy.deepcopy(template)
    write.update(id=WRITE_NODE_ID, kind="Write", name="ReviewWrite", inputs=[READ_NODE_ID], enabled=True)
    write["params"].update(
        path="", write_format=EXTENSIONS[extension], output_space=DISPLAY_OUTPUT_SPACE,
        write_limit_range=False, write_channels="all",
    )
    for node in (read, write):
        node.pop("metadata", None)

    project = copy.deepcopy(dict(source))
    project["graph"] = dict(
        project["graph"], nodes=[read, write], selected=None,
        next_id=WRITE_NODE_ID + 1,
        # Viewer slots may point at nodes that no longer exist; the active slot index stays.
        viewers=[None] * len(project["graph"].get("viewers") or []),
    )
    project["project_settings"] = dict(settings, frame_range=[start, end])
    # Only the view transform: the artist's viewer exposure/gamma must not bake in.
    project["color"] = dict(color, view=REVIEW_VIEW, exposure=0.0, gamma=1.0)
    project["timeline"] = dict(project.get("timeline") or {}, custom_range=None)
    project["current_frame"] = start
    return project


def write_project(source_path: str, destination: Path, **kwargs) -> Path:
    with open(source_path, encoding="utf-8") as stream:
        source = json.load(stream)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build_project(source, **kwargs), indent=1), encoding="utf-8")
    return destination
