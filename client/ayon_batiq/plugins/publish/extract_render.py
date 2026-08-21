from pathlib import Path
import pyblish.api
from ayon_batiq.api.headless import HeadlessRenderError, render

class ExtractRender(pyblish.api.InstancePlugin):
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
        try:
            result = render(
                executable=executable, project=data["currentFile"], output=str(staging / output),
                frames=(int(data["frameStart"]), int(data["frameEnd"]), int(data.get("step", 1))),
                write_node=write_id,
            )
        except HeadlessRenderError as exc:
            data.pop("representations", None)
            raise RuntimeError("BATIQ headless render failed") from exc
        files = sorted(path.name for path in staging.iterdir() if path.is_file())
        if not files:
            raise RuntimeError("BATIQ headless render produced no files")
        data["representations"] = [{
            "name": data.get("outputFormat") or Path(files[0]).suffix.lstrip(".").lower(),
            "ext": data.get("outputFormat") or Path(files[0]).suffix.lstrip(".").lower(),
            "stagingDir": str(staging),
            "files": files,
        }]
        return result
