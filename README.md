# AYON-BATIQ

AYON-BATIQ 0.1.8 is the separately installed AYON host add-on for BATIQ. It is
not bundled into BATIQ: without this add-on, BATIQ keeps its generic embedded
`import batiq` API and starts with no AYON menus, Qt process, or AYON imports.

## Package and install

Use Python 3.9 or newer from the repository root:

```sh
python create_package.py
```

This uses AYON's standard package workflow and writes the server-installable
archive under `package/`. In AYON Server, open **Studio Settings → Bundles →
Install addon**, choose that archive, then enable BATIQ 0.1.8 in a bundle.

The add-on requires AYON Server `>=1.8.4,<2.0.0`, AYON Core
`>=1.9.10-bcn.1` (including final `1.9.10` and newer), and
BATIQ with the embedded Python/project-format-v30 host API. In AYON's
Applications add-on, configure the BATIQ executable as a host application with
host name `batiq`; that host name is what scopes this add-on's launch
environment to BATIQ alone.

## Settings

`ayon+settings://batiq`:

- `workfile/apply_context_on_launch`: apply the task's frame range (with
  handles), fps, resolution and pixel aspect to a new unsaved project on launch.
- `colorspace/rules`: map BATIQ colorspaces to names in the project's OCIO
  config, overriding the built-in table (loading and publishing).
- `publish/ValidateBatiqContextSettings`: enabled / optional / active.
- `publish/ExtractReviewIntermediates`: review frames baked by BATIQ with its
  ACES 2.0 output transform (sRGB display, SDR 100 nits).

## Review

As in the Nuke add-on, the host bakes the review source and core **Extract
Review** encodes it. The core settings need an Extract Review profile with host
`batiq` and product base type `render`, for example an H.264 output tagged
`burnin` and `ftrackreview`. Leave out `-apply_trc gamma22` (used in Nuke's
EXR-based profile): BATIQ's review frames are already display-referred.

See `CHANGELOG.md` for what changed in each version.

## Tests

The tests run against a checked-out AYON Core client and the AYON dependency
package on `PYTHONPATH`:

```sh
PYTHONPATH=.:client:<ayon-core>/client:<dependencies> python -m pytest tests
```

## Development mode

1. Run `python create_package.py` once and install the generated ZIP on AYON Server.
2. Add and enable BATIQ 0.1.8 in a development bundle.
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
