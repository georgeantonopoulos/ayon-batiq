"""Thumbnail from the display-referred review frames.

Core's Extract Thumbnail only runs for hosts in its hard-coded list, which does
not include BATIQ. This makes the same representation Core would: a JPEG from
the middle review frame (already ACES 2.0 sRGB), ``thumbnailPath`` for the AYON
version thumbnail, and a ``thumbnail`` representation for ftrack.
"""
from pathlib import Path

import pyblish.api
from ayon_core.lib import get_ffmpeg_tool_args, run_subprocess

DISPLAY_EXTENSIONS = {"png", "jpg", "jpeg"}


class ExtractBatiqThumbnail(pyblish.api.InstancePlugin):
    label = "Extract BATIQ Thumbnail"
    hosts = ["batiq"]
    families = ["render", "prerender", "image"]
    # After the review frames are baked, before Extract Review deletes them.
    order = pyblish.api.ExtractorOrder + 0.015
    # Longest side of the thumbnail, as Core's default target size.
    max_size = 1920

    def process(self, instance):
        if instance.data.get("thumbnailPath"):
            self.log.debug("The instance already has a thumbnail.")
            return
        source = self._source(instance)
        if source is None:
            self.log.debug("No display-referred frames to make a thumbnail from.")
            return
        staging = Path(instance.data.get("stagingDir") or source.parent)
        staging.mkdir(parents=True, exist_ok=True)
        output = staging / "thumbnail.jpg"
        run_subprocess(
            get_ffmpeg_tool_args(
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-frames:v", "1",
                "-vf", f"scale='min({self.max_size},iw)':-2", "-q:v", "2", str(output),
            ),
            logger=self.log,
        )
        tags = ["thumbnail"]
        core = (instance.context.data.get("project_settings") or {}).get("core", {})
        if not core.get("publish", {}).get("ExtractThumbnail", {}).get("integrate_thumbnail", False):
            tags.append("delete")  # as Core: thumbnail for AYON/ftrack only, not a published file
        instance.data["thumbnailPath"] = str(output)
        instance.data.setdefault("representations", []).append({
            "name": "thumbnail",
            "ext": "jpg",
            "files": output.name,
            "stagingDir": str(staging),
            "thumbnail": True,
            "tags": tags,
            "outputName": "thumbnail",
        })
        self.log.info(f"Thumbnail from {source.name}")

    @staticmethod
    def _source(instance):
        """Middle frame of the first display-referred representation (review bake or PNG/JPEG Write)."""
        for representation in instance.data.get("representations") or []:
            if str(representation.get("ext", "")).lower() not in DISPLAY_EXTENSIONS:
                continue
            files = representation["files"]
            files = files if isinstance(files, list) else [files]
            return Path(representation["stagingDir"]) / files[len(files) // 2]
        return None
