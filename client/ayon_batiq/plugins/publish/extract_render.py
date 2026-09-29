from pathlib import Path
import pyblish.api
from ayon_core.pipeline.publish import ColormanagedPyblishPluginMixin
from ayon_batiq.api.headless import HeadlessRenderError, render

class ExtractRender(pyblish.api.InstancePlugin, ColormanagedPyblishPluginMixin):
    label = "Render BATIQ Write"
    hosts = ["batiq"]
    families = ["render"]
    order = pyblish.api.ExtractorOrder

    def process(self, instance):
        data = instance.data
        write_id = (data.get("transientData") or {}).get("write_node_id")
        if not isinstance(write_id, int) or isinstance(write_id, bool): raise RuntimeError("render instance requires explicit Write node ID")
        staging = Path(data["stagingDir"]); staging.mkdir(parents=True, exist_ok=True)
        output = data.get("output", f"{data.get('productName', 'render')}.####.exr")
        executable = data.get("batiqExecutable") or instance.context.data.get("batiqExecutable")
        if not executable:
            raise RuntimeError("BATIQ executable is unavailable from the live host")
        start, end, step = int(data["frameStart"]), int(data["frameEnd"]), int(data.get("step", 1))
        try:
            result = render(
                executable=executable, project=data["currentFile"], output=str(staging / output),
                frames=(start, end, step),
                write_node=write_id,
            )
        except HeadlessRenderError as exc:
            data.pop("representations", None)
            raise RuntimeError("BATIQ headless render failed") from exc
        files = self._rendered_files(result.get("frame_files") or {}, range(start, end + 1, step), staging)
        ext = data.get("outputFormat") or Path(files[0]).suffix.lstrip(".").lower()
        representation = {
            "name": ext,
            "ext": ext,
            "stagingDir": str(staging),
            # AYON integrates a list as a frame sequence and a string as one file.
            "files": files if len(files) > 1 else files[0],
            "frameStart": start,
            "frameEnd": end,
        }
        if data.get("colorspace"):
            # Filled only when the project enables colour management for BATIQ.
            self.set_representation_colorspace(representation, instance.context, colorspace=data["colorspace"])
        data["representations"] = [representation]
        return result

    @staticmethod
    def _rendered_files(frame_files, expected, staging):
        """File names in frame order, only when BATIQ wrote exactly the expected frames."""
        missing = sorted(set(expected) - set(frame_files))
        extra = sorted(set(frame_files) - set(expected))
        if missing or extra:
            raise RuntimeError(f"BATIQ render frames do not match the range: missing {missing}, unexpected {extra}")
        files = []
        for frame in expected:
            path = Path(frame_files[frame])
            if path.parent.resolve() != staging.resolve():
                raise RuntimeError(f"BATIQ wrote frame {frame} outside the staging directory: {path}")
            if not path.is_file():
                raise RuntimeError(f"BATIQ reported frame {frame} but the file is missing: {path}")
            files.append(path.name)
        return files
