"""AYON Launcher-facing BATIQ host add-on declaration."""
from __future__ import annotations

import os
from pathlib import Path

from ayon_core.addon import AYONAddon, IHostAddon, click_wrap

from .version import __version__

PACKAGE_ROOT = Path(__file__).resolve().parent


def _append_path(existing: str | None, value: str) -> str:
    parts = [part for part in (existing or "").split(os.pathsep) if part]
    if value not in parts:
        parts.append(value)
    return os.pathsep.join(parts)


def _append_module(existing: str | None, module: str) -> str:
    modules = [item.strip() for item in (existing or "").split(",") if item.strip()]
    if module not in modules:
        modules.append(module)
    return ",".join(modules)


def _run_ui_helper(host: str, port: int) -> None:
    """Delay Qt and host imports until AYON invokes the helper command."""
    from .remote.ui_helper import main

    main(host, port)


class BatiqAddon(AYONAddon, IHostAddon):
    name = "batiq"
    version = __version__
    host_name = "batiq"

    def add_implementation_envs(self, env, app):
        """Inject startup code only into the BATIQ application environment."""
        if getattr(app, "host_name", None) != self.host_name:
            return
        # BATIQ adds this directory to embedded CPython's ``sys.path``.
        env["BATIQ_PYTHONPATH"] = _append_path(
            env.get("BATIQ_PYTHONPATH"), str(PACKAGE_ROOT.parent)
        )
        env["BATIQ_STARTUP_MODULES"] = _append_module(
            env.get("BATIQ_STARTUP_MODULES"),
            "ayon_batiq.startup.bootstrap",
        )

    def get_launch_hook_paths(self, app):
        if getattr(app, "host_name", None) != self.host_name:
            return []
        return [str(PACKAGE_ROOT / "hooks")]

    def get_workfile_extensions(self):
        return [".batiq"]

    def cli(self, click_group):
        def _main() -> None:
            pass

        main = click_wrap.group(_main, name=self.name, help="BATIQ host add-on commands")
        main.command(
            _run_ui_helper,
            name="ui-helper",
            help="Run the persistent BATIQ AYON Qt helper.",
        ).option("--host", required=True).option("--port", required=True, type=int)
        click_group.add_command(main.to_click_obj())
