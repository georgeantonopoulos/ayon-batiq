"""Studio and project settings for the BATIQ host integration."""
from typing import Any

from ayon_server.settings import BaseSettingsModel, SettingsField


def batiq_colorspaces_enum():
    return ["ACEScg", "ACES2065-1", "Linear sRGB", "sRGB - Texture", "Rec.709"]


class WorkfileModel(BaseSettingsModel):
    apply_context_on_launch: bool = SettingsField(
        True,
        title="Apply task settings to a new project on launch",
        description=(
            "Frame range (with handles), fps, resolution and pixel aspect"
            " from the task, applied when BATIQ starts without a saved project."
        ),
    )


class ColorspaceRuleModel(BaseSettingsModel):
    batiq_name: str = SettingsField(
        "ACEScg", title="BATIQ colorspace", enum_resolver=batiq_colorspaces_enum
    )
    ocio_name: str = SettingsField("", title="OCIO colorspace")


class ColorspaceModel(BaseSettingsModel):
    rules: list[ColorspaceRuleModel] = SettingsField(
        default_factory=list,
        title="Remapping rules",
        description=(
            "Overrides the built-in mapping between BATIQ colorspaces and names"
            " in the project's OCIO config, for loading and publishing."
        ),
    )


class OptionalPluginModel(BaseSettingsModel):
    enabled: bool = SettingsField(True, title="Enabled")
    optional: bool = SettingsField(True, title="Optional")
    active: bool = SettingsField(True, title="Active")


class PublishPluginsModel(BaseSettingsModel):
    ValidateBatiqContextSettings: OptionalPluginModel = SettingsField(
        default_factory=OptionalPluginModel,
        title="Validate Context Settings",
        description="Frame range, fps, resolution and pixel aspect match the task.",
    )


class BatiqSettings(BaseSettingsModel):
    workfile: WorkfileModel = SettingsField(
        default_factory=WorkfileModel, title="Workfile"
    )
    colorspace: ColorspaceModel = SettingsField(
        default_factory=ColorspaceModel, title="Colorspace"
    )
    publish: PublishPluginsModel = SettingsField(
        default_factory=PublishPluginsModel, title="Publish plugins"
    )


DEFAULT_VALUES: dict[str, Any] = {
    "workfile": {"apply_context_on_launch": True},
    "colorspace": {"rules": []},
    "publish": {
        "ValidateBatiqContextSettings": {
            "enabled": True,
            "optional": True,
            "active": True,
        },
    },
}
