# Changelog

## 0.1.10
- Thumbnail: new *Extract BATIQ Thumbnail* makes the JPEG from the middle review
  frame (ACES 2.0 sRGB) as Core would: `thumbnailPath` for the AYON version and a
  `thumbnail` representation for ftrack. Core's Extract Thumbnail has a hard-coded
  host list without BATIQ.
- Review frames are labelled with the config's `color_picking` space (ACES 1.2:
  `Output - sRGB`), so the H.264 no longer claims to be ACEScg.
- Verified in the dev bundle: ayon_alpha render_Batiq_Test v004 reached ftrack with
  EXR, H.264 playable and thumbnail.

## 0.1.9
Fixes from the first live publish in BATIQ, and render targets.
- Publish no longer fails with `KeyError: 'anatomyData'`: the staging directory
  comes from Core's CollectManagedStagingDir instead of being computed before
  anatomy data exists.
- An unsaved workfile is reported by Core's *Validate File Saved* (with its Save
  action) instead of crashing the Write collector.
- Review family is set at collection, like Nuke, so ftrack's CollectFtrackFamily
  sends reviewed renders to ftrack (verified: v002 in ayon_alpha got an ftrack id).
- Render target on Render/Prerender/Image: *Local machine rendering* or *Use
  existing frames* (publish what the Write already rendered to its path). New
  *Validate Rendered Frames* lists missing frames; Repair switches to local.
- Review intermediates bake in the instance staging dir, never next to the
  artist's existing frames.
- *Validate Context Settings* is on the workfile instance, like Nuke's Validate
  Script Attributes, so its toggle is where artists look for it.
- *Validate Write Node* compares colorspaces by their name in the project OCIO
  config: BATIQ reports its built-in ACEScg as "ACEScg" for "ACES - ACEScg".

## 0.1.8
- Creators set the Write up like BCN's Nuke creators, from new `batiq/create`
  settings per creator:
  - render path `{work}/renders/batiq/{product[name]}/{product[name]}.####.{ext}`
    from the anatomy work directory (Image: one file, no frame number);
  - file format, data type, EXR compression, channels (Render: EXR half ZIP RGB;
    Prerender: EXR half ZIP RGBA; Image: PNG 8-bit RGBA). DWAA is not offered:
    BATIQ 0.2.26 silently writes ZIP instead;
  - output colorspace from an OCIO role resolved in the project config
    (Render/Prerender `scene_linear` -> `ACES - ACEScg`, Image `color_picking`
    -> `Output - sRGB` with the studio ACES 1.2 config);
  - frame range: the task range with handles, limited on the Write.
  Changing folder, task or variant in the Publisher moves the path and range.
- Custom frame range: Render/Prerender instances have *Custom frame range*,
  *First frame* and *Last frame*; the Write follows and exactly that range is
  rendered and published (without handles).
- Publishing reports the task range with its handles (frameStart/End plus
  handleStart/End) like Nuke when the Write covers task range + handles; the
  full range is rendered.
- Validators (optional, with Repair): Validate Write Node (setup matches the
  creator settings), Validate Frame Range (task range with handles unless a
  custom range is set), Validate Folder Context (workfile's folder/task).
- Colour management: new `batiq/imageio` settings (Enable Color Management,
  file rules). Without them Core treated BATIQ as unmanaged, so publishes carried
  no colorspace data.
- Duplicate product names are refused when creating.
- Bridge: Write path, colorspace, data type, compression and create-directories
  are settable; range changes are ordered so BATIQ never sees first > last.

## 0.1.7
- Publisher: Render, Prerender and Image creators, as in Nuke. Each creates a Write
  node fed by the selected node (or unconnected with Use selection off), placed
  below it, and named after the product. Default variants match Nuke's.
- Render and Prerender publish the Write's frame range (the project range unless
  the Write limits it). Image publishes one frame, the Active frame (default: the
  project's first frame); changing it in the Publisher updates the Write.
- Review defaults on for Render, off for Prerender; Image has no review.
- Plain Write nodes, and Writes published with 0.1.6 or earlier, are still picked up
  as renders, so existing workfiles publish as before.
- Removing an instance deletes a Write the creator made; a plain Write is kept and
  only stops being published.
- Bridge: new `nodes.create_write`; `nodes.list` reports selection; `nodes.update`
  sets Write frame-range keys on Write nodes.

## 0.1.6
- Review: new `ExtractReviewIntermediates` (like Nuke's) bakes display-referred
  review frames from the rendered EXRs with BATIQ's built-in ACES 2.0 output
  transform (sRGB display, SDR 100 nits). Measured against the ACES 2.0 studio
  OCIO config v3.0.0, the pixels match to within one 8-bit code value. The bake
  reads the published EXRs, so reviews show exactly the published pixels without
  re-rendering the comp. The artist's viewer exposure/gamma never bake in.
- The frames are tagged `review` (plus `delete` unless the output is set to
  publish) and the instance gets the `review` family, so core Extract Review
  encodes the H.264 and burn-ins from its profiles. That needs a core profile
  for host `batiq`; see README.
- PNG/JPEG Writes are already display-referred and are reviewed directly.
- Settings: `batiq/publish/ExtractReviewIntermediates` (outputs: name,
  PNG/JPEG, publish, task type / product name filters, custom tags).
- BATIQ 0.2.26 ignores the project view for Write output (ACES 1.3 gives the
  same pixels), so no view option is offered.

## 0.1.5
- Colorspace: the Write colorspace is published under the name the project's OCIO
  config actually uses (ACES 1.2 `ACES - ACEScg`, ACES 1.3+ `ACEScg`, aliases), or left
  off with a warning when there is no match. Studio rules under `batiq/colorspace`
  override the built-in table, for loading and publishing.
- Loader: reads `colorspaceData` from representations, maps ACES 1.2 names, and never
  asks BATIQ for `sRGB - Display` (unsupported; mapped to `sRGB - Texture`).
- Loader: loads MOV/MP4/M4V/MKV and places movies on the shot's first frame
  (source frame = project frame + frame_offset). Frame ranges include handles and come
  from the version. TIFF and DPX are not offered: BATIQ 0.2.26 cannot decode them.
- Task settings: a launch hook passes frame range (with handles), fps, resolution and
  pixel aspect to BATIQ, applied to a new unsaved project on start
  (`batiq/workfile/apply_context_on_launch`). New AYON menu items: Set Frame Range,
  Set Resolution, Apply All Settings. New bridge method `project.set_settings`.
- Publish: `ValidateBatiqContextSettings` (optional, with Repair) checks the project
  against the task. Render instances get a Review toggle and fps, handle, frame and
  resolution data for review extraction.
- Server settings: `workfile`, `colorspace.rules`, `publish.ValidateBatiqContextSettings`.
- Host plugin paths are deregistered by type rather than list position.
- Headless render failures include BATIQ's error message.

- Tests for task settings, colorspace mapping, the validator, launch hook and
  `project.set_settings` (28 tests against AYON Core 1.9.14-bcn.1).

Review output (an ACES 2.0 intermediate plus core ExtractReview) is the next
step and is not part of 0.1.5.
