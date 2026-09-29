"""AYON task attributes expressed as BATIQ project settings.

Standard-library only: the launch hook, the Qt helper and the publish
validator all share it, and BATIQ's embedded startup receives its output
as JSON.
"""
from __future__ import annotations

from typing import Any, Mapping

ENV_KEY = "BATIQ_AYON_CONTEXT_SETTINGS"
FRAME_KEYS = ("frame_start", "frame_end")
FORMAT_KEYS = ("width", "height", "pixel_aspect")
ALL_KEYS = FRAME_KEYS + ("fps",) + FORMAT_KEYS


def settings_from_attrib(attrib: Mapping[str, Any]) -> dict[str, Any]:
    """BATIQ project values for a task, with handles included like Nuke's root."""
    values: dict[str, Any] = {}
    start, end = attrib.get("frameStart"), attrib.get("frameEnd")
    if start is not None and end is not None:
        values["frame_start"] = int(start) - int(attrib.get("handleStart") or 0)
        values["frame_end"] = int(end) + int(attrib.get("handleEnd") or 0)
    if attrib.get("fps") is not None:
        values["fps"] = float(attrib["fps"])
    if attrib.get("resolutionWidth") is not None:
        values["width"] = int(attrib["resolutionWidth"])
    if attrib.get("resolutionHeight") is not None:
        values["height"] = int(attrib["resolutionHeight"])
    if attrib.get("pixelAspect") is not None:
        values["pixel_aspect"] = float(attrib["pixelAspect"])
    return values


def differences(expected: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, tuple]:
    """Keys whose BATIQ value differs from the expected one: {key: (current, expected)}."""
    changed = {}
    for key, value in expected.items():
        actual = current.get(key)
        if isinstance(value, float):
            same = actual is not None and abs(float(actual) - value) < 1e-3
        else:
            same = actual == value
        if not same:
            changed[key] = (actual, value)
    return changed
