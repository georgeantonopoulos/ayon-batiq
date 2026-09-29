"""Review project building and the review-intermediates extractor."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

CLIENT_ROOT = Path(__file__).parents[1] / "client"
if str(CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIENT_ROOT))

from ayon_batiq.api import review
from ayon_batiq.plugins.publish.extract_review_intermediates import ExtractReviewIntermediates


def batiq_project():
    params = {"path": "/out/beauty.####.exr", "write_format": "exr", "output_space": "ACEScg",
              "read_first": 1, "read_last": 1, "frame_offset": 0, "input_space": "ACEScg"}
    return {
        "format": "BATIQ Node Compositor", "version": 32,
        "graph": {"nodes": [
            {"id": 4, "kind": "Grade", "name": "Grade1", "inputs": [], "enabled": True, "params": dict(params)},
            {"id": 7, "kind": "Write", "name": "Main", "inputs": [4], "enabled": True,
             "params": dict(params), "metadata": {"ayon_publish": {"x": 1}}},
        ], "selected": 7, "next_id": 8, "active_viewer": 1, "viewers": [7, None, None]},
        "color": {"working_space": "AcesCg", "view": "Aces13", "exposure": 2.0, "gamma": 1.2},
        "project_settings": {"width": 1920, "height": 1080, "frame_range": [1, 100]},
        "timeline": {"rate_source": "project", "custom_range": [5, 9]},
        "current_frame": 50,
    }


class ReviewProjectTest(unittest.TestCase):
    def test_review_project_reads_the_render_and_writes_display_frames(self):
        project = review.build_project(
            batiq_project(), write_node=7, first_file="/stage/beauty.1001.exr",
            input_space="ACEScg", frames=(1001, 1010), extension="png",
        )
        read, write = project["graph"]["nodes"]
        self.assertEqual((read["id"], read["kind"], read["inputs"]), (1, "Read", []))
        self.assertEqual(read["params"]["path"], "/stage/beauty.1001.exr")
        self.assertEqual((read["params"]["read_first"], read["params"]["read_last"]), (1001, 1010))
        self.assertEqual(read["params"]["input_space"], "ACEScg")
        self.assertEqual((write["id"], write["kind"], write["inputs"]), (2, "Write", [1]))
        self.assertEqual((write["params"]["write_format"], write["params"]["output_space"]), ("png", "sRGB - Display"))
        self.assertNotIn("metadata", write)
        self.assertEqual(project["graph"]["viewers"], [None, None, None])
        self.assertEqual(project["graph"]["active_viewer"], 1)  # a slot index, must stay a number
        self.assertEqual(project["project_settings"]["frame_range"], [1001, 1010])
        # The artist's viewer exposure/gamma never bake into the review.
        self.assertEqual(project["color"], {"working_space": "AcesCg", "view": "Aces20", "exposure": 0.0, "gamma": 1.0})
        self.assertIsNone(project["timeline"]["custom_range"])

    def test_invalid_sources_are_rejected(self):
        kwargs = dict(first_file="/s/a.exr", input_space="ACEScg", frames=(1, 2), extension="png")
        with self.assertRaises(review.ReviewProjectError):
            review.build_project(batiq_project(), write_node=99, **kwargs)
        with self.assertRaises(review.ReviewProjectError):
            review.build_project({"format": "other"}, write_node=7, **kwargs)
        with self.assertRaises(review.ReviewProjectError):
            review.build_project(batiq_project(), write_node=7, **dict(kwargs, extension="tif"))


class ExtractReviewIntermediatesTest(unittest.TestCase):
    def setUp(self):
        self.staging = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.staging)
        self.workfile = self.staging / "shot.batiq"
        self.workfile.write_text(json.dumps(batiq_project()))

    def _instance(self, **extra):
        instance = Mock()
        instance.context.data = {"batiqExecutable": "/batiq"}
        instance.data = {
            "productName": "renderMain", "currentFile": str(self.workfile), "colorspace": "ACEScg",
            "transientData": {"write_node_id": 7}, "families": ["render"], "fps": 25.0,
            "representations": [{
                "name": "exr", "ext": "exr", "stagingDir": str(self.staging),
                "files": ["beauty.1001.exr", "beauty.1002.exr"], "frameStart": 1001, "frameEnd": 1002,
            }],
            **extra,
        }
        return instance

    def _fake_render(self, calls):
        def render(**kwargs):
            calls.append(kwargs)
            output = Path(kwargs["output"])
            start, end, _step = kwargs["frames"]
            frame_files = {}
            for frame in range(start, end + 1):
                path = output.parent / output.name.replace("####", f"{frame:04d}")
                path.write_bytes(b"png")
                frame_files[frame] = str(path)
            return {"frame_files": frame_files}
        return render

    def test_bakes_review_frames_for_core_extract_review(self):
        calls, instance = [], self._instance()
        with patch("ayon_batiq.plugins.publish.extract_review_intermediates.render", side_effect=self._fake_render(calls)):
            ExtractReviewIntermediates().process(instance)
        baked = instance.data["representations"][1]
        self.assertEqual(baked["files"], ["renderMain_aces20.1001.png", "renderMain_aces20.1002.png"])
        self.assertEqual((baked["name"], baked["ext"], baked["tags"]), ("aces20", "png", ["review", "delete"]))
        self.assertEqual((baked["frameStart"], baked["frameEnd"]), (1001, 1002))
        self.assertIn("review", instance.data["families"])
        self.assertEqual(calls[0]["write_node"], review.WRITE_NODE_ID)
        project = json.loads(Path(calls[0]["project"]).read_text())
        self.assertEqual(project["graph"]["nodes"][0]["params"]["path"], str(self.staging / "beauty.1001.exr"))

    def test_published_output_and_custom_tags(self):
        plugin = ExtractReviewIntermediates()
        plugin.outputs = [dict(ExtractReviewIntermediates.outputs[0], name="jpeg", extension="jpg", publish=True, add_custom_tags=["client"])]
        instance = self._instance()
        with patch("ayon_batiq.plugins.publish.extract_review_intermediates.render", side_effect=self._fake_render([])):
            plugin.process(instance)
        baked = instance.data["representations"][1]
        self.assertEqual((baked["ext"], baked["tags"], baked["custom_tags"]), ("jpg", ["review"], ["client"]))

    def test_skips_when_review_is_off_or_filtered_out(self):
        render = Mock()
        with patch("ayon_batiq.plugins.publish.extract_review_intermediates.render", render):
            ExtractReviewIntermediates().process(self._instance(review=False))
            plugin = ExtractReviewIntermediates()
            plugin.outputs = [dict(ExtractReviewIntermediates.outputs[0], filter={"task_types": [], "product_names": ["^plate"]})]
            instance = self._instance()
            plugin.process(instance)
        render.assert_not_called()
        self.assertEqual(len(instance.data["representations"]), 1)

    def test_display_referred_write_is_reviewed_directly(self):
        instance = self._instance()
        instance.data["representations"] = [{"name": "png", "ext": "png", "files": "a.1001.png", "stagingDir": str(self.staging)}]
        render = Mock()
        with patch("ayon_batiq.plugins.publish.extract_review_intermediates.render", render):
            ExtractReviewIntermediates().process(instance)
        render.assert_not_called()
        self.assertEqual(instance.data["representations"][0]["tags"], ["review"])
        self.assertIn("review", instance.data["families"])

    def test_runs_after_the_render_and_before_core_extract_review(self):
        from ayon_batiq.plugins.publish.extract_render import ExtractRender
        self.assertGreater(ExtractReviewIntermediates.order, ExtractRender.order)
        self.assertLess(ExtractReviewIntermediates.order, ExtractRender.order + 0.02)


if __name__ == "__main__":
    unittest.main()
