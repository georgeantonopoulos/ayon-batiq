from pathlib import Path
import pyblish.api
from ayon_core.pipeline.colorspace import (
    get_colorspace_settings_from_publish_context,
    get_ocio_config_colorspaces,
)
from ayon_core.pipeline.publish import ColormanagedPyblishPluginMixin
from ayon_batiq.api.headless import HeadlessRenderError, render
from ayon_batiq.colorspace import to_ocio

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
            raise RuntimeError(f"BATIQ headless render failed: {exc}") from exc
        files = self._rendered_files(result.get("frame_files") or {}, range(start, end + 1, step), staging)
        ext = Path(files[0]).suffix.lstrip(".").lower()
        representation = {
            "name": ext,
            "ext": ext,
            "stagingDir": str(staging),
            # AYON integrates a list as a frame sequence and a string as one file.
            "files": files if len(files) > 1 else files[0],
            "frameStart": start,
            "frameEnd": end,
        }
        ocio_name = self._ocio_colorspace(data.get("colorspace"), instance.context)
        if ocio_name:
            self.set_representation_colorspace(representation, instance.context, colorspace=ocio_name)
        data["representations"] = [representation]
        return result

    def _ocio_colorspace(self, batiq_name, context):
        """The project's OCIO name for the Write colorspace, or None if it has none."""
        if not batiq_name:
            return None
        config_data, _file_rules = get_colorspace_settings_from_publish_context(context.data)
        if not config_data:
            return None  # colour management is off for this project
        colorspaces = get_ocio_config_colorspaces(config_data["path"])["colorspaces"]
        rules = context.data["project_settings"].get("batiq", {}).get("colorspace", {}).get("rules")
        ocio_name = to_ocio(batiq_name, colorspaces, rules)
        if not ocio_name:
            self.log.warning(
                f"BATIQ colorspace {batiq_name!r} has no match in {config_data['path']}; add a rule"
                " under batiq/colorspace. The render is published without colorspace data."
            )
        return ocio_name

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
