# Changelog

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
