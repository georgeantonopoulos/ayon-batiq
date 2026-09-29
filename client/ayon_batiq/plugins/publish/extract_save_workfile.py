import pyblish.api
from ayon_core.pipeline import registered_host


class ExtractSaveWorkfile(pyblish.api.ContextPlugin):
    """Save unsaved edits first: renders and the published workfile read the file on disk."""

    label = "Save BATIQ Workfile"
    hosts = ["batiq"]
    order = pyblish.api.ExtractorOrder - 0.45

    def process(self, context):
        host = registered_host()
        if host is None:
            raise RuntimeError("BATIQ publish host is unavailable")
        if not host.get_current_workfile() or not host.workfile_has_unsaved_changes():
            return
        self.log.info("Saving the BATIQ workfile before extraction")
        host.save_workfile()
        if host.workfile_has_unsaved_changes():
            raise RuntimeError("BATIQ still reports unsaved changes after saving the workfile")
