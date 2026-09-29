"""Task settings, colorspace mapping, the context validator and launch hook."""
from __future__ import annotations

import json
import sys
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

CLIENT_ROOT = Path(__file__).parents[1] / "client"
if str(CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIENT_ROOT))

from ayon_batiq.colorspace import to_batiq, to_ocio
from ayon_batiq.context import ENV_KEY, differences, settings_from_attrib

ATTRIB = {
    "frameStart": 1001, "frameEnd": 1100, "handleStart": 8, "handleEnd": 8,
    "fps": 25, "resolutionWidth": 3840, "resolutionHeight": 2160, "pixelAspect": 1,
}
ACES_12 = {name: {"aliases": []} for name in (
    "ACES - ACEScg", "ACES - ACES2065-1", "Utility - Linear - sRGB",
    "Utility - sRGB - Texture", "Output - Rec.709",
)}
ACES_13 = {
    "ACEScg": {"aliases": ["ACES - ACEScg", "lin_ap1"]},
    "Linear Rec.709 (sRGB)": {"aliases": ["Utility - Linear - sRGB", "lin_rec709"]},
}


class ContextSettingsTest(unittest.TestCase):
    def test_task_attributes_include_handles_like_nuke_root(self):
        self.assertEqual(settings_from_attrib(ATTRIB), {
            "frame_start": 993, "frame_end": 1108, "fps": 25.0,
            "width": 3840, "height": 2160, "pixel_aspect": 1.0,
        })
        self.assertEqual(settings_from_attrib({"fps": 24}), {"fps": 24.0})

    def test_differences_tolerate_float_noise(self):
        expected = settings_from_attrib(ATTRIB)
        current = dict(expected, fps=25.0000001, width=1920)
        self.assertEqual(differences(expected, current), {"width": (1920, 3840)})


class ColorspaceTest(unittest.TestCase):
    def test_batiq_names_resolve_to_names_in_the_config(self):
        self.assertEqual(to_ocio("ACEScg", ACES_12), "ACES - ACEScg")
        self.assertEqual(to_ocio("Linear sRGB", ACES_12), "Utility - Linear - sRGB")
        self.assertEqual(to_ocio("ACEScg", ACES_13), "ACEScg")
        self.assertEqual(to_ocio("Linear sRGB", ACES_13), "Linear Rec.709 (sRGB)")
        self.assertIsNone(to_ocio("ACES2065-1", ACES_13))

    def test_studio_rules_take_priority(self):
        rules = [{"batiq_name": "ACEScg", "ocio_name": "Utility - Linear - sRGB"}]
        self.assertEqual(to_ocio("ACEScg", ACES_12, rules), "Utility - Linear - sRGB")
        self.assertEqual(to_batiq("Utility - Linear - sRGB", rules), "ACEScg")

    def test_ocio_names_map_to_batiq_inputs_only(self):
        cases = {
            "ACES - ACEScg": "ACEScg", "Utility - sRGB - Texture": "sRGB - Texture",
            "Output - Rec.709": "Rec.709", "Linear Rec.709 (sRGB)": "Linear sRGB",
            # BATIQ rejects display-referred sRGB as an input.
            "sRGB - Display": "sRGB - Texture", "scene_linear": "ACEScg",
        }
        for name, expected in cases.items():
            self.assertEqual(to_batiq(name), expected, name)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertIsNone(to_batiq("Input - ARRI - V3 LogC (EI800) - Wide Gamut"))
        self.assertEqual(len(caught), 1)
        self.assertIsNone(to_batiq(None))


class FakeProject:
    def __init__(self):
        self.frame_start, self.frame_end, self.fps = 1, 100, 24.0
        self.width, self.height, self.pixel_aspect = 1920, 1080, 1.0
        self.path, self.modified = None, False

    def __setattr__(self, key, value):
        # BATIQ refuses a start after the end, so the order of writes matters.
        if key == "frame_start" and hasattr(self, "frame_end") and value > self.frame_end:
            raise ValueError("frame_start after frame_end")
        object.__setattr__(self, key, value)


class BootstrapSettingsTest(unittest.TestCase):
    def setUp(self):
        self.previous = sys.modules.get("batiq")
        self.project = FakeProject()
        sys.modules["batiq"] = SimpleNamespace(
            project=self.project, ui=SimpleNamespace(add_menu_action=lambda *a: None)
        )
        sys.modules.pop("ayon_batiq.startup.bootstrap", None)
        with patch("ayon_batiq.startup.bridge_server.BridgeServer.start"):
            from ayon_batiq.startup import bootstrap
        self.bootstrap = bootstrap

    def tearDown(self):
        self.bootstrap._bridge = None
        sys.modules.pop("ayon_batiq.startup.bootstrap", None)
        if self.previous is None:
            sys.modules.pop("batiq", None)
        else:
            sys.modules["batiq"] = self.previous

    def test_set_settings_moves_range_past_current_end_and_validates(self):
        result = self.bootstrap.dispatch("project.set_settings", {"frame_start": 2001, "frame_end": 2010, "fps": 25})
        self.assertEqual((result["frame_start"], result["frame_end"], result["fps"]), (2001, 2010, 25.0))
        for bad in ({"colour": 1}, {"fps": "25"}, {"frame_start": 10, "frame_end": 5}, {"width": True}):
            with self.assertRaises(ValueError):
                self.bootstrap.dispatch("project.set_settings", bad)

    def test_launch_settings_apply_only_to_a_fresh_project(self):
        values = settings_from_attrib(ATTRIB)
        with patch.dict("os.environ", {ENV_KEY: json.dumps(values)}):
            self.bootstrap._apply_launch_context()
        self.assertEqual((self.project.frame_start, self.project.width), (993, 3840))
        self.project.path = "/work/shot.batiq"
        with patch.dict("os.environ", {ENV_KEY: json.dumps({"frame_start": 1, "frame_end": 2})}):
            self.bootstrap._apply_launch_context()
        self.assertEqual(self.project.frame_start, 993)


class ValidatorAndHookTest(unittest.TestCase):
    def test_validator_reports_differences_and_repairs(self):
        from ayon_core.pipeline.publish import PublishValidationError
        from ayon_batiq.plugins.publish import validate_context_settings as module

        class Host:
            repaired = False
            def get_batiq_project_info(self):
                return {"frame_start": 1, "frame_end": 100, "fps": 24.0,
                        "resolutionWidth": 3840, "resolutionHeight": 2160, "pixelAspect": 1.0}
            def apply_context_settings(self, keys=None):
                Host.repaired = True

        context = SimpleNamespace(data={"taskEntity": {"attrib": ATTRIB}})
        with patch.object(module, "registered_host", return_value=Host()):
            with self.assertRaises(PublishValidationError) as raised:
                module.ValidateBatiqContextSettings().process(context)
            module.ValidateBatiqContextSettings.repair(context)
        self.assertIn("First frame", str(raised.exception))
        self.assertNotIn("Width", str(raised.exception))
        self.assertTrue(Host.repaired)

    def test_launch_hook_passes_task_settings_unless_disabled(self):
        from ayon_batiq.hooks.pre_context_settings import BatiqContextSettingsHook

        hook = BatiqContextSettingsHook.__new__(BatiqContextSettingsHook)
        hook.launch_context = SimpleNamespace(env={}, data={
            "task_entity": {"attrib": ATTRIB},
            "project_settings": {"batiq": {"workfile": {"apply_context_on_launch": True}}},
        })
        hook.log = SimpleNamespace(info=lambda *a: None)
        with patch.object(BatiqContextSettingsHook, "data", property(lambda self: self.launch_context.data)):
            hook.execute()
            self.assertEqual(json.loads(hook.launch_context.env[ENV_KEY])["frame_start"], 993)
            hook.launch_context.env.clear()
            hook.launch_context.data["project_settings"]["batiq"]["workfile"]["apply_context_on_launch"] = False
            hook.execute()
        self.assertEqual(hook.launch_context.env, {})


if __name__ == "__main__":
    unittest.main()
