"""Render / Prerender / Image creators and the bridge's Write creation."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ayon_core.pipeline import register_host
from ayon_core.pipeline.create import CreatorError

from ayon_batiq.api.host import RemoteBatiqHost
from ayon_batiq.plugins.create.write_creator import (
    CreateWriteImage, CreateWritePrerender, CreateWriteRender,
)
from ayon_core.lib import StringTemplate

from ayon_batiq.plugins.create import write_creator
from ayon_batiq.plugins.publish.collect_writes import CollectWrites

SETTINGS = {"core": {"tools": {"creator": {"product_name_profiles": []}}}}
WORK_DIR = "{root[work]}/{project[code]}/work/{hierarchy}/{folder[name]}/{task[name]}/"
CONFIG = "/mnt/studio/config/ocio/aces_1.2/config.ocio"
OCIO = {
    "roles": {"scene_linear": {"colorspace": "ACES - ACEScg"}, "color_picking": {"colorspace": "Output - sRGB"}},
    "colorspaces": {"ACES - ACEScg": {}, "Output - sRGB": {}, "Utility - sRGB - Texture": {}},
}
TASK = {"name": "comp", "taskType": "compositing",
        "attrib": {"frameStart": 1001, "frameEnd": 1010, "handleStart": 8, "handleEnd": 8}}


class Anatomy:
    templates_obj = SimpleNamespace(frame_padding=4)

    def get_template_item(self, category, name, key):
        assert (category, name, key) == ("work", "default", "directory")
        return StringTemplate(WORK_DIR)


def template_data(project_name, folder_path, task_name, host_name, settings=None):
    return {"root": {"work": "/mnt/production/project"}, "project": {"name": project_name, "code": "DEMO"},
            "hierarchy": "shots/sq01", "folder": {"name": folder_path.rsplit("/", 1)[-1]},
            "task": {"name": task_name}}


def core_fakes(test, config=CONFIG):
    """Replace Core's anatomy, template data and OCIO lookups for creator tests."""
    for target, value in (
        ("get_template_data_with_names", template_data),
        ("get_imageio_config_preset", lambda *a, **k: {"path": config} if config else {}),
        ("get_ocio_config_colorspaces", lambda path: OCIO),
        ("ayon_api", SimpleNamespace(get_folder_by_path=lambda *a, **k: {"id": "folder-id"},
                                     get_task_by_name=lambda *a, **k: TASK)),
    ):
        patcher = patch.object(write_creator, target, value)
        patcher.start()
        test.addCleanup(patcher.stop)
    patcher = patch.object(write_creator.BatiqWriteCreator, "project_anatomy", Anatomy())
    patcher.start()
    test.addCleanup(patcher.stop)


class Bridge:
    """The bridge as the creators see it, backed by a list of node dicts."""

    def __init__(self, nodes=()):
        self.nodes, self.calls, self.next_id = [dict(n) for n in nodes], [], 100

    def call(self, method, params=None):
        params = dict(params or {})
        self.calls.append((method, params))
        if method == "nodes.list":
            return self.nodes
        if method == "nodes.create_write":
            node = {"id": self.next_id, "kind": "Write", "name": params["name"], "enabled": True,
                    "input": params["input"], "metadata": params.get("metadata", {})}
            node.update({k: v for k, v in params.items() if k not in ("name", "input", "metadata")})
            self.next_id += 1
            self.nodes.append(node)
            return node
        if method == "nodes.update":
            node = self._node(params.pop("id"))
            node.setdefault("metadata", {}).update(params.pop("metadata", {}))
            node.update(params)
            return node
        if method == "nodes.remove":
            self.nodes.remove(self._node(params["id"]))
            return True
        if method == "project.info":
            return {"frame_start": 1001, "frame_end": 1010, "executable": "/batiq"}
        return True

    def _node(self, node_id):
        return next(n for n in self.nodes if int(n["id"]) == int(node_id))


class CreateContext:
    host_name = "batiq"
    headless = False

    def __init__(self, host):
        self.host, self.instances = host, []

    def get_current_project_entity(self): return {"name": "Demo"}
    def get_current_project_name(self): return "Demo"
    def get_current_folder_entity(self): return {"name": "shot", "path": "/assets/shot", "folderType": "Shot"}
    def get_current_task_entity(self): return TASK
    def creator_adds_instance(self, instance): self.instances.append(instance)
    def creator_removed_instance(self, instance): self.instances.remove(instance)
    def instance_create_attr_defs_changed(self, instance_id): pass
    def instance_values_changed(self, instance_id, changes): pass


class CreatorsTest(unittest.TestCase):
    def setUp(self):
        previous = {k: os.environ.get(k) for k in ("AYON_PROJECT_NAME", "AYON_FOLDER_PATH", "AYON_TASK_NAME")}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in previous.items()])
        os.environ.update(AYON_PROJECT_NAME="Demo", AYON_FOLDER_PATH="/assets/shot", AYON_TASK_NAME="comp")
        self.bridge = Bridge([
            {"id": 5, "kind": "Grade", "name": "Grade1", "enabled": True, "selected": True},
            {"id": 6, "kind": "Write", "name": "beauty", "enabled": True, "metadata": {}},
            {"id": 7, "kind": "Write", "name": "old", "enabled": True,
             "metadata": {"ayon_publish": {"creator_identifier": "write", "instance_id": "legacy-id"}}},
        ])
        self.host = RemoteBatiqHost(self.bridge)
        self.host.get_current_workfile = lambda: "/work/DEMO_sh010_comp_v007.batiq"
        register_host(self.host)
        core_fakes(self)

    def creators(self):
        context = CreateContext(self.host)
        return context, [cls(SETTINGS, context) for cls in (CreateWriteRender, CreateWritePrerender, CreateWriteImage)]

    def test_publisher_lists_three_creators_like_nuke(self):
        _context, creators = self.creators()
        self.assertEqual([c.product_type for c in creators], ["render", "prerender", "image"])
        self.assertEqual([c.label for c in creators], ["Render (write)", "Prerender (write)", "Image (write)"])
        self.assertTrue(all(c.default_variants for c in creators))

    def test_plain_and_legacy_writes_stay_renders(self):
        _context, (render, prerender, image) = self.creators()
        found = render.collect_instances()
        self.assertEqual({i.transient_data["write_node_id"] for i in found}, {6, 7})
        self.assertEqual({i["variant"] for i in found}, {"beauty", "old"})
        # Legacy instance ids survive, and the Write is re-tagged for the Render creator.
        self.assertIn("legacy-id", {i.id for i in found})
        self.assertEqual(self.bridge._node(7)["metadata"]["ayon_publish"]["creator_identifier"], "create_write_render")
        self.assertEqual(prerender.collect_instances(), [])
        self.assertEqual(image.collect_instances(), [])

    def test_render_write_is_set_up_like_nukes(self):
        _context, (render, _prerender, _image) = self.creators()
        instance = render.create("renderCompMain", {"variant": "Main", "folderPath": "/shots/sq01/sh010", "task": "comp"},
                                 {"use_selection": True})
        method, params = self.bridge.calls[-1]
        self.assertEqual(method, "nodes.create_write")
        self.assertEqual((params["name"], params["input"]), ("renderCompMain", 5))
        self.assertEqual(params["path"], "/mnt/production/project/DEMO/work/shots/sq01/sh010/comp"
                                         "/renders/batiq/renderCompMain/renderCompMain.####.exr")
        self.assertEqual({k: params[k] for k in ("write_format", "write_datatype", "write_compression",
                                                  "write_channels", "output_space", "create_directories")},
                         {"write_format": "exr", "write_datatype": "half", "write_compression": "zip",
                          "write_channels": "rgb", "output_space": "ACES - ACEScg", "create_directories": True})
        # The task's 1001-1010 with 8-frame handles.
        self.assertEqual((params["write_limit_range"], params["write_first"], params["write_last"]), (True, 993, 1018))
        self.assertTrue(instance["creator_attributes"]["review"])
        self.assertEqual(params["metadata"]["ayon_publish"]["creator_identifier"], "create_write_render")

    def test_prerender_creates_write_from_selection_and_is_collected_again(self):
        context, (_render, prerender, _image) = self.creators()
        instance = prerender.create("prerenderCompBG", {"variant": "BG", "folderPath": "/assets/shot", "task": "comp"}, {"use_selection": True})
        params = self.bridge.calls[-1][1]
        self.assertEqual(params["input"], 5)
        self.assertEqual((params["write_channels"], params["output_space"]), ("rgba", "ACES - ACEScg"))
        self.assertTrue(params["path"].endswith("/renders/batiq/prerenderCompBG/prerenderCompBG.####.exr"))
        self.assertEqual(instance.product_type, "prerender")
        self.assertTrue(instance["creator_attributes"]["review"])
        write_id = instance.transient_data["write_node_id"]
        # A fresh Publisher session finds it with the same id, and only the Prerender creator does.
        context2 = CreateContext(self.host)
        again = CreateWritePrerender(SETTINGS, context2).collect_instances()
        self.assertEqual([(i.id, i["variant"]) for i in again], [(instance.id, "BG")])
        renders = CreateWriteRender(SETTINGS, context2).collect_instances()
        self.assertNotIn(write_id, {i.transient_data["write_node_id"] for i in renders})

    def test_image_limits_write_to_active_frame_and_follows_changes(self):
        _context, (_render, _prerender, image) = self.creators()
        self.assertEqual(image.get_instance_attr_defs()[0].default, 1001)
        instance = image.create("imageCompStillFrame", {"variant": "StillFrame", "folderPath": "/assets/shot", "task": "comp"},
                                {"use_selection": False, "active_frame": 1005})
        params = self.bridge.calls[-1][1]
        self.assertIsNone(params["input"])
        self.assertEqual((params["write_limit_range"], params["write_first"], params["write_last"]), (True, 1005, 1005))
        self.assertEqual((params["write_format"], params["write_datatype"], params["output_space"]),
                         ("png", "8", "Output - sRGB"))
        self.assertTrue(params["path"].endswith("/renders/batiq/imageCompStillFrame/imageCompStillFrame.png"))
        instance["creator_attributes"]["active_frame"] = 1007
        image.update_instances([(instance, SimpleNamespace(changed_keys={"creator_attributes"}))])
        node = self.bridge._node(instance.transient_data["write_node_id"])
        self.assertEqual((node["write_first"], node["write_last"]), (1007, 1007))

    def test_context_change_moves_the_render_path(self):
        _context, (render, _prerender, _image) = self.creators()
        instance = render.create("renderCompMain", {"variant": "Main", "folderPath": "/assets/shot", "task": "comp"}, {})
        instance["productName"] = "renderCompBeauty"
        render.update_instances([(instance, SimpleNamespace(changed_keys={"productName"}))])
        node = self.bridge._node(instance.transient_data["write_node_id"])
        self.assertTrue(node["path"].endswith("/renders/batiq/renderCompBeauty/renderCompBeauty.####.exr"))
        # A comment-only change leaves the Write alone.
        calls = len(self.bridge.calls)
        render.update_instances([(instance, SimpleNamespace(changed_keys={"comment"}))])
        self.assertFalse(any(k.startswith(("write_", "path")) for k in self.bridge.calls[calls][1]))

    def test_settings_override_the_write_and_bad_colorspace_is_reported(self):
        settings = dict(SETTINGS, batiq={"create": {"CreateWriteRender": {
            "default_variants": ["Main"], "review": False,
            "write": {"file_format": "exr", "datatype": "float", "compression": "piz",
                      "channels": "all", "colorspace": "Utility - sRGB - Texture"}}}})
        render = CreateWriteRender(settings, CreateContext(self.host))
        render.create("renderCompMain", {"variant": "Main", "folderPath": "/assets/shot", "task": "comp"}, {})
        params = self.bridge.calls[-1][1]
        self.assertEqual((params["write_datatype"], params["write_compression"], params["write_channels"],
                          params["output_space"]), ("float", "piz", "all", "Utility - sRGB - Texture"))
        render.write = dict(render.write, colorspace="not_a_role")
        with self.assertRaisesRegex(CreatorError, "neither a role nor a colorspace"):
            render.create("renderCompOther", {"variant": "Other", "folderPath": "/assets/shot", "task": "comp"}, {})

    def test_without_colour_management_uses_batiq_builtin_space(self):
        core_fakes(self, config=None)
        _context, (render, _prerender, image) = self.creators()
        render.create("renderCompMain", {"variant": "Main", "folderPath": "/assets/shot", "task": "comp"}, {})
        self.assertEqual(self.bridge.calls[-1][1]["output_space"], "ACEScg")
        image.create("imageCompStill", {"variant": "Still", "folderPath": "/assets/shot", "task": "comp"},
                     {"use_selection": False})
        self.assertNotIn("output_space", self.bridge.calls[-1][1])

    def test_duplicate_product_name_is_refused(self):
        context, (render, _prerender, _image) = self.creators()
        render.create("renderCompMain", {"variant": "Main", "folderPath": "/assets/shot", "task": "comp"}, {})
        with self.assertRaisesRegex(CreatorError, "already exists"):
            render.create("renderCompMain", {"variant": "Main", "folderPath": "/assets/shot", "task": "comp"}, {})

    def test_render_update_does_not_touch_the_write_range(self):
        _context, (render, _prerender, _image) = self.creators()
        instance = render.collect_instances()[0]
        render.update_instances([(instance, Mock())])
        self.assertFalse(any(k.startswith("write_") for k in self.bridge.calls[-1][1]))

    def test_selection_errors(self):
        _context, (render, _prerender, _image) = self.creators()
        self.bridge._node(6)["selected"] = True
        with self.assertRaisesRegex(CreatorError, "single node"):
            render.create("renderCompMain", {"variant": "Main"}, {"use_selection": True})
        self.bridge._node(5)["selected"] = False
        with self.assertRaisesRegex(CreatorError, "not a Write"):
            render.create("renderCompMain", {"variant": "Main"}, {"use_selection": True})

    def test_remove_deletes_created_writes_but_only_unmarks_plain_ones(self):
        _context, (render, _prerender, _image) = self.creators()
        created = render.create("renderCompMask", {"variant": "Mask", "folderPath": "/assets/shot", "task": "comp"}, {"use_selection": True})
        plain = next(i for i in render.collect_instances() if i.transient_data["write_node_id"] == 6)
        render.remove_instances([created, plain])
        ids = {n["id"] for n in self.bridge.nodes}
        self.assertNotIn(created.transient_data["write_node_id"], ids)
        self.assertIn(6, ids)
        found = CreateWriteRender(SETTINGS, CreateContext(self.host)).collect_instances()
        self.assertNotIn(6, {i.transient_data["write_node_id"] for i in found})


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.bridge = Bridge([{"id": 9, "kind": "Write", "name": "w", "write_limit_range": False,
                               "write_format": "exr", "output_space": "ACEScg"}])
        self.host = RemoteBatiqHost(self.bridge)
        self.host.get_current_workfile = lambda: "/work/shot.batiq"
        register_host(self.host)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def collect(self, product_type, creator_attributes, context=None):
        instance = Mock()
        instance.context.data = context or {}
        instance.data = {"productType": product_type, "productName": product_type, "stagingDir": self.dir.name,
                         "transientData": {"write_node_id": 9}, "creator_attributes": creator_attributes,
                         "folderPath": "/assets/shot", "task": "comp"}
        CollectWrites().process(instance)
        return instance.data

    def test_task_range_with_handles_is_published_like_nuke(self):
        self.bridge.nodes[0].update(write_limit_range=True, write_first=993, write_last=1018)
        context = {"folderEntity": {"path": "/assets/shot"}, "taskEntity": TASK}
        data = self.collect("render", {}, context)
        self.assertEqual((data["frameStart"], data["frameEnd"], data["handleStart"], data["handleEnd"]),
                         (1001, 1010, 8, 8))
        self.assertEqual((data["frameStartHandle"], data["frameEndHandle"]), (993, 1018))
        # A Write limited to some other range publishes that range without handles.
        self.bridge.nodes[0].update(write_first=1001, write_last=1004)
        data = self.collect("render", {}, context)
        self.assertEqual((data["frameStart"], data["frameEnd"], data["handleStart"]), (1001, 1004, 0))

    def test_image_publishes_its_active_frame(self):
        data = self.collect("image", {"active_frame": 1004})
        self.assertEqual((data["frameStart"], data["frameEnd"]), (1004, 1004))
        self.assertFalse(data["review"])

    def test_prerender_uses_project_range_and_review_toggle(self):
        data = self.collect("prerender", {"review": False})
        self.assertEqual((data["frameStart"], data["frameEnd"]), (1001, 1010))
        self.assertFalse(data["review"])
        self.assertTrue(self.collect("render", {})["review"])
        self.assertTrue(self.collect("prerender", {})["review"])


class FakeNode:
    def __init__(self, node_id, kind, position=(0.0, 0.0)):
        self.id, self.kind, self.name, self.enabled, self.position = node_id, kind, kind, True, position
        self.params, self.inputs, self.metadata = {}, [], {}

    def __setitem__(self, key, value): self.params[key] = value
    def __getitem__(self, key): return self.params.get(key)
    def set_input(self, index, source): self.inputs = [source]
    def set_metadata(self, namespace, data): self.metadata[namespace] = data
    def get_metadata(self, namespace): return self.metadata.get(namespace)


class FakeNodes:
    def __init__(self):
        self.items = {5: FakeNode(5, "Grade", (10.0, 40.0))}
        self.selection = [5]

    def create(self, kind):
        node = FakeNode(max(self.items) + 1, kind)
        self.items[node.id] = node
        return node

    def by_id(self, node_id): return self.items.get(node_id)
    def all(self): return list(self.items.values())
    def selected(self): return [self.items[i] for i in self.selection]
    def select(self, ids): self.selection = list(ids)


class BridgeDispatchTest(unittest.TestCase):
    def setUp(self):
        self.previous = sys.modules.get("batiq")
        self.nodes = FakeNodes()
        sys.modules["batiq"] = SimpleNamespace(nodes=self.nodes, ui=SimpleNamespace(add_menu_action=lambda *a: None))
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

    def test_create_write_wires_places_and_selects(self):
        from ayon_batiq.startup.bridge_server import ALLOWED_METHODS
        self.assertIn("nodes.create_write", ALLOWED_METHODS)
        result = self.bootstrap.dispatch("nodes.create_write", {
            "name": "imageCompStill", "input": 5, "write_limit_range": True, "write_first": 1003,
            "write_last": 1003, "metadata": {"ayon_publish": {"id": "x"}}, "path": "/renders/still.png",
            "not_a_write_param": 1,
        })
        node = self.nodes.by_id(result["id"])
        self.assertEqual((node.kind, node.name, node.inputs), ("Write", "imageCompStill", [self.nodes.by_id(5)]))
        self.assertEqual(node.position, (10.0, 40.0 + self.bootstrap.WRITE_OFFSET))
        self.assertEqual(node.params, {"path": "/renders/still.png", "write_limit_range": True,
                                       "write_first": 1003, "write_last": 1003})
        self.assertEqual(node.metadata["ayon_publish"], {"id": "x"})
        self.assertEqual(self.nodes.selection, [node.id])

    def test_create_write_without_input_and_with_missing_input(self):
        result = self.bootstrap.dispatch("nodes.create_write", {"name": "renderMain", "input": None})
        self.assertEqual(self.nodes.by_id(result["id"]).inputs, [])
        with self.assertRaisesRegex(ValueError, "input node not found"):
            self.bootstrap.dispatch("nodes.create_write", {"name": "x", "input": 99})

    def test_list_reports_selection_and_update_sets_write_range(self):
        write = self.nodes.by_id(self.bootstrap.dispatch("nodes.create_write", {"name": "w"})["id"])
        self.nodes.selection = [5]
        listed = {n["id"]: n for n in self.bootstrap.dispatch("nodes.list", {})}
        self.assertTrue(listed[5]["selected"])
        self.assertFalse(listed[write.id]["selected"])
        self.bootstrap.dispatch("nodes.update", {"id": str(write.id), "write_first": 1009, "write_last": 1009,
                                                 "read_first": 1, "metadata": {}})
        self.assertEqual(write.params, {"write_first": 1009, "write_last": 1009})


class CustomRangeAndValidatorsTest(unittest.TestCase):
    """Custom frame ranges and the Write validators, through the real creator and collector."""

    def setUp(self):
        previous = {k: os.environ.get(k) for k in ("AYON_PROJECT_NAME", "AYON_FOLDER_PATH", "AYON_TASK_NAME")}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in previous.items()])
        os.environ.update(AYON_PROJECT_NAME="Demo", AYON_FOLDER_PATH="/assets/shot", AYON_TASK_NAME="comp")
        self.bridge = Bridge([{"id": 5, "kind": "Grade", "name": "Grade1", "enabled": True, "selected": True}])
        self.host = RemoteBatiqHost(self.bridge)
        self.host.get_current_workfile = lambda: "/work/DEMO_sh010_comp_v007.batiq"
        register_host(self.host)
        core_fakes(self)
        self.create_context = CreateContext(self.host)
        self.create_context.creators = {}
        self.create_context.get_instance_by_id = lambda iid: next(
            (i for i in self.create_context.instances if i.id == iid), None)
        self.create_context.save_changes = Mock()
        self.render = CreateWriteRender(SETTINGS, self.create_context)
        self.create_context.creators[self.render.identifier] = self.render
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def created(self):
        return self.render.create("renderCompMain", {"variant": "Main", "folderPath": "/assets/shot", "task": "comp"}, {})

    def publish_instance(self, created):
        """A pyblish-like instance as CollectFromCreateContext + CollectWrites would build it."""
        instance = Mock()
        instance.context.data = {"folderEntity": {"path": "/assets/shot"}, "taskEntity": TASK,
                                 "folderPath": "/assets/shot", "task": "comp",
                                 "create_context": self.create_context}
        instance.data = dict(created.data_to_store(), stagingDir=self.dir.name,
                             transientData=dict(created.transient_data))
        instance.data["creator_attributes"] = dict(created["creator_attributes"])
        CollectWrites().process(instance)
        return instance

    def test_custom_range_is_written_collected_and_published_without_handles(self):
        created = self.created()
        self.assertEqual(self.render.get_instance_attr_defs()[2].default, 993)
        created["creator_attributes"]["use_custom_range"] = True
        created["creator_attributes"]["frame_start"] = 1020
        created["creator_attributes"]["frame_end"] = 1030
        self.render.update_instances([(created, SimpleNamespace(changed_keys={"creator_attributes"}))])
        node = self.bridge._node(created.transient_data["write_node_id"])
        self.assertEqual((node["write_first"], node["write_last"]), (1020, 1030))
        data = self.publish_instance(created).data
        self.assertEqual((data["frameStart"], data["frameEnd"], data["handleStart"], data["handleEnd"]),
                         (1020, 1030, 0, 0))
        self.assertTrue(data["customFrameRange"])

    def test_write_validator_passes_fails_and_repairs(self):
        from ayon_core.pipeline.publish import PublishValidationError
        from ayon_batiq.plugins.publish.validate_write import ValidateBatiqWrite
        created = self.created()
        instance = self.publish_instance(created)
        ValidateBatiqWrite().process(instance)
        node = self.bridge._node(created.transient_data["write_node_id"])
        node.update(output_space="ACEScg", write_datatype="float")
        with self.assertRaisesRegex(PublishValidationError, "Colorspace.*\\n- |Data type"):
            ValidateBatiqWrite().process(instance)
        ValidateBatiqWrite.repair(instance)
        self.assertEqual((node["output_space"], node["write_datatype"]), ("ACES - ACEScg", "half"))
        ValidateBatiqWrite().process(instance)
        # A Write made by hand keeps its own settings.
        instance.data["madeByCreator"] = False
        node["write_format"] = "png"
        ValidateBatiqWrite().process(instance)

    def test_frame_range_validator(self):
        from ayon_core.pipeline.publish import PublishValidationError
        from ayon_batiq.plugins.publish.validate_write import ValidateBatiqWriteFrameRange
        created = self.created()
        ValidateBatiqWriteFrameRange().process(self.publish_instance(created))
        node = self.bridge._node(created.transient_data["write_node_id"])
        node.update(write_first=1001, write_last=1004)
        instance = self.publish_instance(created)
        with self.assertRaisesRegex(PublishValidationError, "993-1018"):
            ValidateBatiqWriteFrameRange().process(instance)
        ValidateBatiqWriteFrameRange.repair(instance)
        self.assertEqual((node["write_first"], node["write_last"]), (993, 1018))
        created["creator_attributes"].update({"use_custom_range": True, "frame_start": 1050, "frame_end": 1040})
        with self.assertRaisesRegex(PublishValidationError, "ends before it starts"):
            ValidateBatiqWriteFrameRange().process(self.publish_instance(created))

    def test_folder_context_validator(self):
        from ayon_core.pipeline.publish import PublishValidationError
        from ayon_batiq.plugins.publish.validate_write import ValidateBatiqInstanceContext
        created = self.created()
        instance = self.publish_instance(created)
        ValidateBatiqInstanceContext().process(instance)
        instance.data["task"] = "lighting"
        with self.assertRaisesRegex(PublishValidationError, "lighting"):
            ValidateBatiqInstanceContext().process(instance)
        created["task"] = "lighting"
        ValidateBatiqInstanceContext.repair(instance)
        self.assertEqual(created["task"], "comp")
        self.create_context.save_changes.assert_called_once()


class StrictWrite(FakeNode):
    """Refuses a first frame after the last, as BATIQ validates each value it is given."""

    def __init__(self, node_id):
        super().__init__(node_id, "Write")
        self.params = {"write_first": 1, "write_last": 100}

    def __setitem__(self, key, value):
        if key == "write_first" and value > self.params["write_last"]:
            raise ValueError("write_first after write_last")
        if key == "write_last" and value < self.params["write_first"]:
            raise ValueError("write_last before write_first")
        super().__setitem__(key, value)


class BridgeRangeOrderTest(BridgeDispatchTest):
    def test_moving_the_range_past_its_end_and_back(self):
        write = StrictWrite(50)
        self.nodes.items[50] = write
        self.bootstrap.dispatch("nodes.update", {"id": "50", "write_first": 993, "write_last": 1018})
        self.assertEqual((write["write_first"], write["write_last"]), (993, 1018))
        self.bootstrap.dispatch("nodes.update", {"id": "50", "write_first": 10, "write_last": 20})
        self.assertEqual((write["write_first"], write["write_last"]), (10, 20))
