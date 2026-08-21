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

The BATIQ menu should expose exactly `AYON/Workfiles...`, `AYON/Load...`,
`AYON/Manage...`, and `AYON/Publish...`. Create is intentionally not a menu
item in v1.

This separate repository contains the add-on scaffold, authenticated bridge,
Qt helper, host, plugins, and offline contract tests. Those tests do not prove
a production AYON package install or live BATIQ-to-Qt round trip; Launcher
packaging and live AYON validation remain separate release gates.
