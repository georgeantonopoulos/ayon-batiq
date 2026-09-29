import re
from pathlib import Path

import pyblish.api

from ayon_batiq.api import review
from ayon_batiq.api.headless import HeadlessRenderError, render, rendered_files

DISPLAY_EXTENSIONS = {"png", "jpg", "jpeg"}


class ExtractReviewIntermediates(pyblish.api.InstancePlugin):
    """Bake display-referred review frames for core ExtractReview.

    Like Nuke's intermediates, the host makes the review source and core
    ExtractReview encodes it (h264, burnins, ftrack) from its profiles.
    """

    label = "Extract Review Intermediates"
    hosts = ["batiq"]
    families = ["render"]
    order = pyblish.api.ExtractorOrder + 0.01
    settings_category = "batiq"

    outputs = [{
        "name": "aces20",
        "extension": "png",
        "publish": False,
        "filter": {"task_types": [], "product_names": []},
        "add_custom_tags": [],
    }]

    def process(self, instance):
        data = instance.data
        if not data.get("review", True):
            self.log.debug("Review is off for this instance.")
            return
        representations = data.get("representations") or []
        display = [r for r in representations if r.get("ext") in DISPLAY_EXTENSIONS]
        if display:
            # A PNG/JPEG Write is already display-referred (ACES 2.0): review it directly.
            for representation in display:
                self._tag(representation, {"publish": True, "add_custom_tags": []})
            self._add_review_family(instance)
            return
        source = next((r for r in representations if r.get("ext") == "exr"), None)
        if source is None:
            self.log.debug("No EXR render to bake a review from.")
            return

        outputs = [output for output in self.outputs if self._matches(output, instance)]
        if not outputs:
            self.log.debug("No review intermediate output matches this instance.")
            return
        files = source["files"] if isinstance(source["files"], list) else [source["files"]]
        start, end = int(source["frameStart"]), int(source["frameEnd"])
        step = int(data.get("step", 1))
        executable = data.get("batiqExecutable") or instance.context.data.get("batiqExecutable")
        product = data.get("productName", "render")

        for output in outputs:
            name, extension = output["name"], output["extension"]
            staging = Path(source["stagingDir"]) / f"review_{name}"
            project = review.write_project(
                data["currentFile"], staging / "review.batiq",
                write_node=int(data["transientData"]["write_node_id"]),
                first_file=str(Path(source["stagingDir"]) / files[0]),
                input_space=data.get("colorspace") or "ACEScg",
                frames=(start, end),
                extension=extension,
            )
            try:
                result = render(
                    executable=executable, project=str(project),
                    output=str(staging / f"{product}_{name}.####.{extension}"),
                    frames=(start, end, step), write_node=review.WRITE_NODE_ID,
                )
            except HeadlessRenderError as exc:
                raise RuntimeError(f"BATIQ review bake '{name}' failed: {exc}") from exc
            baked = rendered_files(result.get("frame_files") or {}, range(start, end + 1, step), staging)
            representation = {
                "name": name,
                "ext": extension,
                "files": baked if len(baked) > 1 else baked[0],
                "stagingDir": str(staging),
                "frameStart": start,
                "frameEnd": end,
                "fps": data.get("fps"),
            }
            self._tag(representation, output)
            representations.append(representation)
            self.log.info(f"Baked {len(baked)} ACES 2.0 review frame(s) as '{name}'.")
        data["representations"] = representations
        self._add_review_family(instance)

    @staticmethod
    def _tag(representation, output):
        tags = list(representation.get("tags") or [])
        for tag in ("review",) if output.get("publish") else ("review", "delete"):
            if tag not in tags:
                tags.append(tag)
        representation["tags"] = tags
        custom = list(representation.get("custom_tags") or [])
        custom += [tag for tag in output.get("add_custom_tags") or [] if tag not in custom]
        if custom:
            representation["custom_tags"] = custom

    @staticmethod
    def _matches(output, instance):
        output_filter = output.get("filter") or {}
        task_types = output_filter.get("task_types") or []
        if task_types:
            task = instance.data.get("taskEntity") or instance.context.data.get("taskEntity") or {}
            if task.get("taskType") not in task_types:
                return False
        patterns = output_filter.get("product_names") or []
        product = instance.data.get("productName", "")
        return not patterns or any(re.search(pattern, product) for pattern in patterns)

    @staticmethod
    def _add_review_family(instance):
        families = instance.data.setdefault("families", [])
        if "review" not in families:
            families.append("review")
