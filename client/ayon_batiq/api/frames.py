"""Frames a BATIQ Write already rendered to its own path."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

# BATIQ numbers frames with a run of '#' (one per digit); printf-style is accepted too.
_HASHES = re.compile(r"#+")
_PRINTF = re.compile(r"%0?(\d*)d")


def frame_path(write_path: str, frame: int) -> Path:
    """The file a Write path names for ``frame``; a path without a frame token is one file."""
    if _HASHES.search(write_path):
        return Path(_HASHES.sub(lambda m: f"{frame:0{len(m.group())}d}", write_path, count=1))
    if _PRINTF.search(write_path):
        return Path(_PRINTF.sub(lambda m: f"{frame:0{int(m.group(1) or 1)}d}", write_path, count=1))
    return Path(write_path)


def existing_frames(write_path: str, frames: Iterable[int]) -> tuple[list[Path], list[int]]:
    """(files in frame order, missing frames) for the Write's rendered output."""
    files, missing = [], []
    for frame in frames:
        path = frame_path(write_path, frame)
        if path.is_file():
            if path not in files:
                files.append(path)
        else:
            missing.append(frame)
    return files, missing
