# AYON Batiq add-on design

This is a narrow v1 design for Workfiles, Load, Manage/Scene Inventory, and
Publish. It is not an attempt to reproduce `ayon-nuke`.

## Two Python boundaries

`import batiq` is the internal, in-process API. AYON's standard tools are
Qt/PySide applications, while BATIQ owns an egui/winit event loop. Running a
second Qt event loop in the BATIQ process is not a supported v1 design.

The add-on therefore uses a small external Qt helper process for AYON UI:

```text
BATIQ embedded Python (import batiq)
        │ restricted authenticated loopback bridge
        ▼
AYON Qt helper (RemoteBatiqHost + AYON Core tools)
```

The bridge is only for this toolkit boundary; it is not the canonical BATIQ
API. Both sides ultimately request the same host operations. The helper is
started lazily through `AYON_EXECUTABLE addon batiq ui-helper --host … --port
…`, inherits the AYON project/folder/task environment, and exits during
bounded BATIQ startup teardown. Its token is the first JSON line on stdin,
never an argument.

## Bridge requirements

Bind only to `127.0.0.1`, use an ephemeral port and a cryptographically random
per-session token, bound message sizes, request timeouts, and an explicit
method allowlist. JSON-RPC 2.0/JSONL is acceptable. The allowlist covers
project/workfile operations, node/container operations needed by the four v1
tools, and showing a named AYON window. It must not expose `eval`, `exec`,
`run_python`, shell execution, arbitrary file reads, or arbitrary commands.

## v1 host behavior

`RemoteBatiqHost` implements the AYON `IWorkfileHost`, `ILoadHost`, and
`IPublishHost` contracts through the bridge. Workfiles use `.batiq` and map
open/save/save-as/current-path/modified state to the live BATIQ window.
`LoadImage` is the only loader: it creates a native Read node, sets path and
range/colorspace where available, and stores the normal AYON container data in
generic node metadata. Manage/Scene Inventory updates or removes those
containers. Publish collects normal AYON instances and representations; the
extractor saves the workfile and invokes the existing isolated
`batiq-headless` Write-node render path. The old direct `batiq_api` AYON
adapter is for standalone automation and is not the host Publisher.

The BATIQ menu exposes `AYON/Workfiles...`, `AYON/Load...`, `AYON/Manage...`,
and `AYON/Publish...`, plus the context-settings actions `AYON/Set Frame Range`,
`AYON/Set Resolution` and `AYON/Apply All Settings` (0.1.5). Create is
intentionally not a menu item: creators are automatic.

## Task settings (0.1.5)

`settings_from_attrib` turns task attributes into BATIQ project values: frame
range with handles (as Nuke sets its root), fps, resolution and pixel aspect.
A pre-launch hook passes them as JSON in `BATIQ_AYON_CONTEXT_SETTINGS`; startup
applies them only to a fresh, unsaved project. The menu actions and the
`ValidateBatiqContextSettings` repair call the allowlisted
`project.set_settings` bridge method, which accepts only those six keys.

## Colorspace (0.1.5)

BATIQ reads ACEScg, ACES2065-1, Linear sRGB, sRGB - Texture and Rec.709 and
writes ACEScg, ACES2065-1 or Linear sRGB. `colorspace.py` maps these to the
names in the project's OCIO config (config names and aliases, ACES 1.2 and
1.3+) and back. Studio rules in `batiq/colorspace/rules` take priority. A Write
colorspace with no match in the config is published without colorspace data
rather than under a name the config does not know.

This separate repository contains the add-on scaffold, authenticated bridge,
Qt helper, host, plugins, and offline contract tests. Those tests do not prove
a production AYON package install or live BATIQ-to-Qt round trip; Launcher
packaging and live AYON validation remain separate release gates.

## Review (0.1.6)

Following the Nuke add-on, review is split in two. `ExtractReviewIntermediates`
(host) builds a two-node BATIQ project, a Read of the published EXRs into a
PNG/JPEG Write, from the artist's project with viewer exposure and gamma reset.
It renders that project headless, so BATIQ's built-in ACES 2.0 output transform
bakes the frames. Core Extract Review then encodes them from its profiles.
Keeping the colour transform inside BATIQ means the review shows what the
artist saw, and BATIQ needs no OCIO config for it. Published EXRs keep
colorspace names from the studio OCIO config (ACES 1.2 at BCN), so Nuke and
other ACES 1.2 hosts read them correctly.
