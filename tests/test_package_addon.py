"""Packaging and Launcher-shell tests against the checked-out AYON Core API."""
from __future__ import annotations

import io
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

ROOT = Path(__file__).parents[1]
CLIENT_ROOT = ROOT / "client"
if str(CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIENT_ROOT))

import package
from ayon_batiq.addon import BatiqAddon
from ayon_batiq.startup.bridge_server import BridgeServer
from ayon_core.addon import AddonsManager


class TestPackageMetadata(TestCase):
    def test_addon_initializes_with_current_addons_manager_contract(self):
        addon = BatiqAddon(AddonsManager(initialize=False), {})
        self.assertEqual(addon.name, "batiq")
        self.assertEqual(addon.version, "0.1.8")
        self.assertEqual(addon.get_workfile_extensions(), [".batiq"])

    def test_package_metadata_matches_ayon_host_contract(self):
        self.assertEqual(package.name, "batiq")
        self.assertEqual(package.title, "BATIQ")
        self.assertEqual(package.version, "0.1.8")
        self.assertEqual(package.app_host_name, "batiq")
        self.assertEqual(package.client_dir, "ayon_batiq")
        self.assertTrue(package.project_can_override_addon_version)
        self.assertEqual(package.ayon_server_version, ">=1.8.4,<2.0.0")
        self.assertEqual(
            package.ayon_required_addons, {"core": ">=1.9.10-bcn.1"}
        )

    def test_environment_is_scoped_to_batiq_and_preserves_values(self):
        addon = BatiqAddon.__new__(BatiqAddon)
        env = {"BATIQ_PYTHONPATH": "/existing", "BATIQ_STARTUP_MODULES": "existing.module"}
        addon.add_implementation_envs(env, SimpleNamespace(host_name="other"))
        self.assertEqual(env["BATIQ_PYTHONPATH"], "/existing")
        self.assertEqual(env["BATIQ_STARTUP_MODULES"], "existing.module")

        addon.add_implementation_envs(env, SimpleNamespace(host_name="batiq"))
        self.assertIn("/existing", env["BATIQ_PYTHONPATH"])
        self.assertIn(str(CLIENT_ROOT), env["BATIQ_PYTHONPATH"])
        self.assertEqual(env["BATIQ_STARTUP_MODULES"], "existing.module,ayon_batiq.startup.bootstrap")
        addon.add_implementation_envs(env, SimpleNamespace(host_name="batiq"))
        self.assertEqual(env["BATIQ_STARTUP_MODULES"].count("ayon_batiq.startup.bootstrap"), 1)

    def test_cli_registers_ui_helper(self):
        registered = []
        BatiqAddon.__new__(BatiqAddon).cli(SimpleNamespace(add_command=registered.append))
        command = registered[0]
        self.assertEqual(command.name, "batiq")
        self.assertIn("ui-helper", command.commands)

    def test_server_addon_declares_real_base_and_settings_defaults(self):
        class BaseServerAddon:
            def get_settings_model(self):
                return self.settings_model

        class BaseSettingsModel:
            def __init__(self, **kwargs):
                self.values = kwargs

        def SettingsField(default=None, **kwargs):
            return default

        fake_server = SimpleNamespace(
            addons=SimpleNamespace(BaseServerAddon=BaseServerAddon),
            settings=SimpleNamespace(
                BaseSettingsModel=BaseSettingsModel, SettingsField=SettingsField,
                task_types_enum=lambda: [],
            ),
        )
        with mock.patch.dict(sys.modules, {
            "ayon_server": fake_server,
            "ayon_server.addons": fake_server.addons,
            "ayon_server.settings": fake_server.settings,
        }):
            sys.modules.pop("server", None)
            sys.modules.pop("server.settings", None)
            server_module = importlib.import_module("server")
            self.assertTrue(issubclass(server_module.BatiqAddon, BaseServerAddon))
            self.assertTrue(issubclass(server_module.BatiqSettings, BaseSettingsModel))
            defaults = server_module.DEFAULT_VALUES
            self.assertTrue(defaults["workfile"]["apply_context_on_launch"])
            self.assertEqual(defaults["colorspace"], {"rules": []})
            review = defaults["publish"]["ExtractReviewIntermediates"]
            self.assertTrue(review["enabled"])
            self.assertEqual(
                [(o["name"], o["extension"], o["publish"]) for o in review["outputs"]],
                [("aces20", "png", False)],
            )
            self.assertEqual(
                defaults["publish"]["ValidateBatiqContextSettings"],
                {"enabled": True, "optional": True, "active": True},
            )
        sys.modules.pop("server", None)
        sys.modules.pop("server.settings", None)

    def test_helper_uses_ayon_cli_and_writes_token_only_to_stdin(self):
        fake_batiq = SimpleNamespace(ui=SimpleNamespace(add_menu_action=lambda *args: None))
        previous = sys.modules.get("batiq")
        sys.modules["batiq"] = fake_batiq
        sys.modules.pop("ayon_batiq.startup.bootstrap", None)
        old_executable = os.environ.get("AYON_EXECUTABLE")
        os.environ["AYON_EXECUTABLE"] = "/ayon/ayon"
        bootstrap = None
        try:
            with mock.patch("ayon_batiq.startup.bridge_server.BridgeServer.start"):
                from ayon_batiq.startup import bootstrap as module
                bootstrap = module
            bootstrap._bridge = SimpleNamespace(address=("127.0.0.1", 1234), token="private-token")
            process = mock.Mock(stdin=io.StringIO())
            process.poll.return_value = None
            with mock.patch.object(bootstrap.subprocess, "Popen", return_value=process) as popen:
                bootstrap._helper = None
                bootstrap._show_helper("workfiles")
            argv = popen.call_args.args[0]
            self.assertEqual(argv[:4], ["/ayon/ayon", "addon", "batiq", "ui-helper"])
            self.assertNotIn("private-token", argv)
            self.assertEqual(json.loads(process.stdin.getvalue().splitlines()[0]), {"token": "private-token"})
        finally:
            if bootstrap is not None:
                bootstrap._helper = None
                if getattr(bootstrap._bridge, "close", None):
                    bootstrap._bridge.close()
            sys.modules.pop("ayon_batiq.startup.bootstrap", None)
            if previous is None:
                sys.modules.pop("batiq", None)
            else:
                sys.modules["batiq"] = previous
            if old_executable is None:
                os.environ.pop("AYON_EXECUTABLE", None)
            else:
                os.environ["AYON_EXECUTABLE"] = old_executable

    def test_bridge_is_loopback_authenticated_and_allowlisted(self):
        dispatch = mock.Mock(return_value={"ok": True})
        bridge = BridgeServer(dispatch)
        bridge.start()
        try:
            self.assertEqual(bridge.address[0], "127.0.0.1")
            valid = bridge.handle_line((json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "project.info",
                "params": {}, "token": bridge.token,
            }) + "\n").encode())
            self.assertEqual(valid["result"], {"ok": True})
            rejected = bridge.handle_line((json.dumps({
                "jsonrpc": "2.0", "id": 2, "method": "project.info",
                "params": {}, "token": "wrong",
            }) + "\n").encode())
            forbidden = bridge.handle_line((json.dumps({
                "jsonrpc": "2.0", "id": 3, "method": "exec",
                "params": {}, "token": bridge.token,
            }) + "\n").encode())
            self.assertIn("error", rejected)
            self.assertIn("error", forbidden)
            dispatch.assert_called_once_with("project.info", {})
        finally:
            bridge.close()
