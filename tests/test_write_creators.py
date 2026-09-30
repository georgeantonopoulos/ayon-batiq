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
from ayon_batiq.plugins.publish.collect_writes import CollectWrites

SETTINGS = {"core": {"tools": {"creator": {"product_name_profiles": []}}}}


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
            node.update({k: v for k, v in params.items() if k.startswith("write_")})
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

    def __init__(self, host):
        self.host, self.instances = host, []

    def get_current_project_entity(self): return {"name": "Demo"}
    def get_current_project_name(self): return "Demo"
    def get_current_folder_entity(self): return {"name": "shot", "path": "/assets/shot", "folderType": "Shot"}
    def get_current_task_entity(self): return {"name": "comp", "taskType": "compositing"}
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
        register_host(self.host)

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

    def test_prerender_creates_write_from_selection_and_is_collected_again(self):
        context, (_render, prerender, _image) = self.creators()
        instance = prerender.create("prerenderCompKey01", {"variant": "Key01", "folderPath": "/assets/shot", "task": "comp"}, {"use_selection": True})
        method, params = self.bridge.calls[-1]
        self.assertEqual(method, "nodes.create_write")
        self.assertEqual(params["input"], 5)
        self.assertNotIn("write_limit_range", params)
        self.assertEqual(instance.product_type, "prerender")
        self.assertFalse(instance["creator_attributes"]["review"])
        write_id = instance.transient_data["write_node_id"]
        # A fresh Publisher session finds it with the same id, and only the Prerender creator does.
        context2 = CreateContext(self.host)
        again = CreateWritePrerender(SETTINGS, context2).collect_instances()
        self.assertEqual([(i.id, i["variant"]) for i in again], [(instance.id, "Key01")])
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
        instance["creator_attributes"]["active_frame"] = 1007
        image.update_instances([(instance, Mock())])
        node = self.bridge._node(instance.transient_data["write_node_id"])
        self.assertEqual((node["write_first"], node["write_last"]), (1007, 1007))

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

    def collect(self, product_type, creator_attributes):
        instance = Mock()
        instance.data = {"productType": product_type, "productName": product_type, "stagingDir": self.dir.name,
                         "transientData": {"write_node_id": 9}, "creator_attributes": creator_attributes}
        CollectWrites().process(instance)
        return instance.data

    def test_image_publishes_its_active_frame(self):
        data = self.collect("image", {"active_frame": 1004})
        self.assertEqual((data["frameStart"], data["frameEnd"]), (1004, 1004))
        self.assertFalse(data["review"])

    def test_prerender_uses_project_range_and_review_toggle(self):
        data = self.collect("prerender", {"review": False})
        self.assertEqual((data["frameStart"], data["frameEnd"]), (1001, 1010))
        self.assertFalse(data["review"])
        self.assertTrue(self.collect("render", {})["review"])


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
            "write_last": 1003, "metadata": {"ayon_publish": {"id": "x"}}, "path": "/ignored",
        })
        node = self.nodes.by_id(result["id"])
        self.assertEqual((node.kind, node.name, node.inputs), ("Write", "imageCompStill", [self.nodes.by_id(5)]))
        self.assertEqual(node.position, (10.0, 40.0 + self.bootstrap.WRITE_OFFSET))
        self.assertEqual(node.params, {"write_limit_range": True, "write_first": 1003, "write_last": 1003})
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
