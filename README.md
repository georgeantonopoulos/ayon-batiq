# AYON-BATIQ

AYON-BATIQ 0.1.4 is the separately installed AYON host add-on for BATIQ. It is
not bundled into BATIQ: without this add-on, BATIQ keeps its generic embedded
`import batiq` API and starts with no AYON menus, Qt process, or AYON imports.

## Package and install

Use Python 3.9 or newer from the repository root:

```sh
python create_package.py
```

This uses AYON's standard package workflow and writes the server-installable
archive under `package/`. In AYON Server, open **Studio Settings → Bundles →
Install addon**, choose that archive, then enable BATIQ 0.1.4 in a bundle.

The add-on requires AYON Server `>=1.8.4,<2.0.0`, AYON Core
`>=1.9.10-bcn.1` (including final `1.9.10` and newer), and
BATIQ with the embedded Python/project-format-v30 host API. In AYON's
Applications add-on, configure the BATIQ executable as a host application with
host name `batiq`; that host name is what scopes this add-on's launch
environment to BATIQ alone.

## Development mode

1. Run `python create_package.py` once and install the generated ZIP on AYON Server.
2. Add and enable BATIQ 0.1.4 in a development bundle.
3. Enable the add-on custom path and point its client path at `<path-to-ayon-batiq>/client`.
4. Start AYON Launcher with that development bundle (or `--use-dev`).
5. Launch the configured BATIQ application.

For production bundles, configure the BATIQ application executable for each
platform in the Applications add-on, keep its host name set to `batiq`, and
launch it with an AYON project, folder, and task selected.

When AYON launches BATIQ, this add-on appends its client directory to
`BATIQ_PYTHONPATH` and `ayon_batiq.startup.bootstrap` to
`BATIQ_STARTUP_MODULES`. Startup is Qt-free; it starts an authenticated
localhost bridge and native BATIQ AYON menu. Selecting a menu starts one
persistent AYON Qt helper through `AYON_EXECUTABLE` and `ayon addon batiq
ui-helper`. The session token is only the first JSON line on stdin, never an
argument.
