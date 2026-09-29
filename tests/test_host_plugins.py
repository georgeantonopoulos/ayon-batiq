"""Core-contract tests; run with the checked-out AYON Core on PYTHONPATH."""
from __future__ import annotations

import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ayon_core.pipeline import (
    discover_inventory_actions, discover_loader_plugins, register_host,
    register_inventory_action_path, register_loader_plugin_path,
)

from ayon_batiq.api.host import RemoteBatiqHost
from ayon_batiq.api.headless import HeadlessRenderError, render as headless_render
from ayon_batiq.plugins.create.workfile_creator import WorkfileCreator
from ayon_batiq.plugins.create.write_creator import WriteCreator
from ayon_batiq.plugins.inventory.select_containers import SelectInGraph
from ayon_batiq.plugins.load.load_image import LoadImage
from ayon_batiq.plugins.publish.extract_render import ExtractRender
from ayon_batiq.plugins.publish.collect_writes import CollectWrites
from ayon_batiq.plugins.publish.extract_save_workfile import ExtractSaveWorkfile


class Bridge:
    def __init__(self):
        self.calls, self.nodes, self.project_metadata = [], [], {}

    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == "nodes.create_read":
            node = {"id": 8, "kind": "Read", "metadata": params["metadata"]}
            self.nodes.append(node)
            return node
        if method == "nodes.list":
            return self.nodes
        if method == "nodes.update":
            node = next(item for item in self.nodes if int(item["id"]) == int(params["id"]))
            node.setdefault("metadata", {}).update(params.get("metadata", {}))
            return node
        if method == "project.get_metadata":
            return self.project_metadata.get(params["namespace"], {})
        if method == "project.set_metadata":
            self.project_metadata[params["namespace"]] = params["data"]
            return True
        if method == "project.info":
            return {"frame_start": 1001, "frame_end": 1010, "executable": "/batiq"}
        return True


class CreateContext:
    host_name = "batiq"
    def __init__(self, host):
        self.host, self.instances = host, []
    def get_current_project_entity(self): return {"name": "Demo"}
    def get_current_project_name(self): return "Demo"
    def get_current_folder_entity(self): return {"name": "shot", "path": "/assets/shot", "folderType": "Shot"}
    def get_current_task_entity(self): return {"name": "comp", "taskType": "compositing"}
    def creator_adds_instance(self, instance): self.instances.append(instance)
    def creator_removed_instance(self, instance): self.instances.remove(instance)
    def instance_create_attr_defs_changed(self, instance_id): pass


class HostPluginsTest(unittest.TestCase):
    def setUp(self):
        self.previous_env = {key: os.environ.get(key) for key in ("AYON_PROJECT_NAME", "AYON_FOLDER_PATH", "AYON_TASK_NAME")}
        os.environ.update(AYON_PROJECT_NAME="Demo", AYON_FOLDER_PATH="/assets/shot", AYON_TASK_NAME="comp")
        self.bridge = Bridge()
        self.host = RemoteBatiqHost(self.bridge)
        register_host(self.host)

    def tearDown(self):
        for key, value in self.previous_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value

    def test_host_context_is_launch_environment_and_publish_data_is_separate(self):
        self.assertEqual(self.host.get_current_context(), {"project_name": "Demo", "folder_path": "/assets/shot", "task_name": "comp"})
        self.host.update_context_data({"comment": "publisher only"})
        self.assertEqual(self.bridge.calls[-1][1]["namespace"], "ayon_publish_context")

    def test_loader_core_contract_and_inventory_discovery(self):
        context = {"project": {"name": "Demo"}, "product": {"name": "plate", "productBaseType": "plate"}, "representation": {"id": "rep", "name": "main", "context": {"ext": "exr"}}}
        with patch.object(LoadImage, "filepath_from_context", return_value="/show/plate.exr"), \
                patch("ayon_batiq.plugins.load.load_image.get_project_settings", return_value={}):
            self.assertTrue(LoadImage.is_compatible_loader(context))
            loaded = LoadImage().load(context, name="plate")
        self.assertEqual(loaded["id"], 8)
        self.assertEqual(self.host.get_containers()[0]["representation"], "rep")
        plugins = Path(__file__).parents[1] / "client" / "ayon_batiq" / "plugins"
        register_loader_plugin_path(str(plugins / "load"))
        register_inventory_action_path(str(plugins / "inventory"))
        with patch("ayon_core.pipeline.load.plugins.get_project_settings", return_value={}):
            self.assertIn("LoadImage", {item.__name__ for item in discover_loader_plugins()})
        self.assertIn("SelectInGraph", {item.__name__ for item in discover_inventory_actions()})
        self.assertIsInstance(SelectInGraph(), SelectInGraph)

    def test_creators_store_real_context_and_stable_data(self):
        self.bridge.nodes = [{"id": 31, "kind": "Write", "name": "beauty", "enabled": True, "metadata": {}}]
        context = CreateContext(self.host)
        settings = {"core": {"tools": {"creator": {"product_name_profiles": []}}}}
        workfile = WorkfileCreator(settings, context)
        self.host.get_current_workfile = lambda: "/work/shot_comp_v001.batiq"
        work_instances = workfile.collect_instances()
        write = WriteCreator(settings, context)
        write_instances = write.collect_instances()
        for instance in work_instances + write_instances:
            self.assertEqual(instance["folderPath"], "/assets/shot")
            self.assertEqual(instance["task"], "comp")
            self.assertTrue(instance["variant"])
            self.assertTrue(instance["productName"])
        self.assertEqual(write_instances[0].transient_data["write_node_id"], 31)
        write.update_instances([(write_instances[0], Mock())])
        first_write_id = write_instances[0].id
        self.assertEqual(
            self.bridge.nodes[0]["metadata"]["ayon_publish"]["instance_id"],
            first_write_id,
        )
        reset_instances = WriteCreator(settings, CreateContext(self.host)).collect_instances()
        self.assertEqual(reset_instances[0].id, first_write_id)
        reset_workfiles = WorkfileCreator(settings, CreateContext(self.host)).collect_instances()
        self.assertEqual(reset_workfiles[0].id, work_instances[0].id)

    def test_extractor_passes_explicit_write_id_and_failure_clears_representation(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        instance = Mock()
        instance.context.data = {"batiqExecutable": "/batiq"}
        instance.data = {"stagingDir": directory.name, "currentFile": "scene.batiq", "frameStart": 1, "frameEnd": 1, "transientData": {"write_node_id": 77}, "representations": [{"old": True}]}
        with patch("ayon_batiq.plugins.publish.extract_render.render", side_effect=HeadlessRenderError("no render")) as render:
            with self.assertRaisesRegex(RuntimeError, "headless render failed"):
                ExtractRender().process(instance)
        self.assertEqual(render.call_args.kwargs["write_node"], 77)
        self.assertNotIn("representations", instance.data)

    def _render_instance(self, staging, frame_start, frame_end, **extra):
        instance = Mock()
        instance.context.data = {"batiqExecutable": "/batiq"}
        instance.data = {
            "stagingDir": str(staging), "currentFile": "scene.batiq",
            "frameStart": frame_start, "frameEnd": frame_end,
            "output": "beauty.####.exr", "outputFormat": "exr",
            "transientData": {"write_node_id": 77}, **extra,
        }
        return instance

    def _fake_render(self, staging, frames, stray=()):
        def render(**_kwargs):
            frame_files = {}
            for frame in frames:
                path = Path(staging) / f"beauty.{frame:04d}.exr"
                path.write_bytes(b"exr")
                frame_files[frame] = str(path)
            for name in stray:
                (Path(staging) / name).write_bytes(b"old")
            return {"written": len(frames), "frame_files": frame_files}
        return render

    def test_extractor_publishes_exactly_the_rendered_frames_with_frame_range(self):
        staging = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(staging))
        instance = self._render_instance(staging, 1001, 1003, colorspace="ACEScg")
        render = self._fake_render(staging, [1001, 1002, 1003], stray=["beauty.0999.exr", "notes.txt"])
        instance.context.data.update(imageioSettings=({"path": "/config.ocio"}, None), project_settings={})
        config = {"colorspaces": {"ACES - ACEScg": {"aliases": []}}}
        with patch("ayon_batiq.plugins.publish.extract_render.render", side_effect=render), \
                patch("ayon_batiq.plugins.publish.extract_render.get_ocio_config_colorspaces", return_value=config), \
                patch.object(ExtractRender, "set_representation_colorspace") as set_colorspace:
            ExtractRender().process(instance)
        representation = instance.data["representations"][0]
        self.assertEqual(representation["files"], ["beauty.1001.exr", "beauty.1002.exr", "beauty.1003.exr"])
        self.assertEqual((representation["frameStart"], representation["frameEnd"]), (1001, 1003))
        self.assertEqual(representation["ext"], "exr")
        # BATIQ's "ACEScg" is published under the config's own name (ACES 1.2 here).
        self.assertEqual(set_colorspace.call_args.kwargs["colorspace"], "ACES - ACEScg")

    def test_extractor_skips_colorspace_missing_from_config_or_without_management(self):
        staging = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(staging))
        for imageio, config in (
            (({"path": "/config.ocio"}, None), {"colorspaces": {"Raw": {}}}),
            ((None, None), None),
        ):
            instance = self._render_instance(staging, 1001, 1001, colorspace="ACEScg")
            instance.context.data.update(imageioSettings=imageio, project_settings={})
            with patch("ayon_batiq.plugins.publish.extract_render.render", side_effect=self._fake_render(staging, [1001])), \
                    patch("ayon_batiq.plugins.publish.extract_render.get_ocio_config_colorspaces", return_value=config), \
                    patch.object(ExtractRender, "set_representation_colorspace") as set_colorspace:
                ExtractRender().process(instance)
            set_colorspace.assert_not_called()

    def test_loader_places_movies_and_sequences_with_handles_and_maps_colorspace(self):
        version = {"attrib": {"frameStart": 1001, "frameEnd": 1100, "handleStart": 8, "handleEnd": 8}}
        movie = {"project": {"name": "Demo"}, "version": version, "representation": {
            "files": [{}], "context": {}, "data": {"colorspaceData": {"colorspace": "Output - Rec.709"}}}}
        sequence = {"project": {"name": "Demo"}, "version": version, "representation": {
            "files": [{}, {}], "context": {"frame": "1001"}, "data": {"colorspaceData": {"colorspace": "ACES - ACEScg"}}}}
        with patch("ayon_batiq.plugins.load.load_image.get_project_settings", return_value={}):
            movie_params = LoadImage()._read_params(movie, "/show/plate.mov")
            sequence_params = LoadImage()._read_params(sequence, "/show/plate.1001.exr")
        # BATIQ reads source frame = project frame + frame_offset; movies start at 1.
        self.assertEqual(movie_params, {"read_first": 1, "read_last": 116, "frame_offset": -992, "input_space": "Rec.709"})
        self.assertEqual(sequence_params, {"read_first": 993, "read_last": 1108, "frame_offset": 0, "input_space": "ACEScg"})

    def test_extractor_single_frame_is_one_file_and_no_colorspace_is_skipped(self):
        staging = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(staging))
        instance = self._render_instance(staging, 1001, 1001)
        with patch("ayon_batiq.plugins.publish.extract_render.render", side_effect=self._fake_render(staging, [1001])), \
                patch.object(ExtractRender, "set_representation_colorspace") as set_colorspace:
            ExtractRender().process(instance)
        self.assertEqual(instance.data["representations"][0]["files"], "beauty.1001.exr")
        set_colorspace.assert_not_called()

    def test_extractor_rejects_missing_frames_and_files_outside_staging(self):
        staging = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(staging))
        instance = self._render_instance(staging, 1001, 1003)
        with patch("ayon_batiq.plugins.publish.extract_render.render", side_effect=self._fake_render(staging, [1001, 1003])):
            with self.assertRaisesRegex(RuntimeError, r"missing \[1002\]"):
                ExtractRender().process(instance)
        elsewhere = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(elsewhere))
        with patch("ayon_batiq.plugins.publish.extract_render.render", side_effect=self._fake_render(elsewhere, [1001, 1002, 1003])):
            with self.assertRaisesRegex(RuntimeError, "outside the staging directory"):
                ExtractRender().process(instance)

    def test_save_workfile_runs_before_render_and_only_when_modified(self):
        self.assertLess(ExtractSaveWorkfile.order, ExtractRender.order)
        state = {"modified": True}
        self.host.get_current_workfile = lambda: "/work/shot.batiq"
        self.host.workfile_has_unsaved_changes = lambda: state["modified"]
        self.host.save_workfile = Mock(side_effect=lambda filepath=None: state.update(modified=False))
        ExtractSaveWorkfile().process(Mock())
        self.host.save_workfile.assert_called_once_with()
        ExtractSaveWorkfile().process(Mock())
        self.host.save_workfile.assert_called_once_with()
        state["modified"] = True
        self.host.save_workfile = Mock()
        with self.assertRaisesRegex(RuntimeError, "unsaved changes after saving"):
            ExtractSaveWorkfile().process(Mock())

    def test_write_collector_uses_real_publish_transient_data(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bridge.nodes = [{
            "id": 77, "kind": "Write", "write_limit_range": True,
            "write_first": 1002, "write_last": 1008, "write_format": "exr",
            "output_space": "ACEScg",
        }]
        self.host.get_current_workfile = lambda: "/work/shot.batiq"
        instance = Mock()
        instance.data = {
            "productType": "render", "productName": "beauty",
            "stagingDir": directory.name,
            "transientData": {"write_node_id": 77},
        }
        CollectWrites().process(instance)
        self.assertEqual(instance.data["frameStart"], 1002)
        self.assertEqual(instance.data["frameEnd"], 1008)
        self.assertEqual(instance.data["currentFile"], "/work/shot.batiq")

    def test_headless_client_sends_versioned_protocol_and_accepts_real_event_shape(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        executable = directory / "fake-batiq"
        executable.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, sys
            init, render = [json.loads(sys.stdin.readline()) for _ in range(2)]
            assert init["params"]["protocol_version"]["major"] == 1
            assert render["params"]["write_node"] == 77
            print(json.dumps({"jsonrpc":"2.0","id":1,"result":{"protocol_version":{"major":1,"minor":0},"capabilities":{"render":True}}}))
            print(json.dumps({"jsonrpc":"2.0","method":"render_event","params":{"sequence":1,"event":"progress","data":{"completed":1,"total":1,"frame":1,"path":"/stage/render.exr"}}}))
            print(json.dumps({"jsonrpc":"2.0","method":"render_event","params":{"sequence":2,"event":"finished","data":{"written":1}}}))
            print(json.dumps({"jsonrpc":"2.0","id":2,"result":{"written":1}}))
        """))
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        result = headless_render(
            executable=str(executable), project="scene.batiq", output="render.exr",
            frames=(1, 1, 1), write_node=77, timeout=2,
        )
        self.assertEqual(result, {"written": 1, "frame_files": {1: "/stage/render.exr"}})


if __name__ == "__main__":
    unittest.main()
