"""Studio and project settings for the BATIQ host integration."""
from typing import Any

from ayon_server.settings import BaseSettingsModel, SettingsField, task_types_enum


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


def review_extensions_enum():
    return [{"value": "png", "label": "PNG"}, {"value": "jpg", "label": "JPEG"}]


class ReviewIntermediateFilterModel(BaseSettingsModel):
    task_types: list[str] = SettingsField(
        default_factory=list, title="Task types", enum_resolver=task_types_enum
    )
    product_names: list[str] = SettingsField(
        default_factory=list, title="Product names (regex)"
    )


class ReviewIntermediateOutputModel(BaseSettingsModel):
    name: str = SettingsField("aces20", title="Output name")
    extension: str = SettingsField(
        "png", title="Extension", enum_resolver=review_extensions_enum
    )
    publish: bool = SettingsField(
        False,
        title="Publish the baked frames",
        description="Off: the frames only feed core Extract Review and are deleted.",
    )
    filter: ReviewIntermediateFilterModel = SettingsField(
        default_factory=ReviewIntermediateFilterModel, title="Filter"
    )
    add_custom_tags: list[str] = SettingsField(
        default_factory=list,
        title="Custom tags",
        description="Match these in core Extract Review output filters.",
    )


class ExtractReviewIntermediatesModel(BaseSettingsModel):
    enabled: bool = SettingsField(True, title="Enabled")
    outputs: list[ReviewIntermediateOutputModel] = SettingsField(
        default_factory=list,
        title="Baking outputs",
        description=(
            "Display-referred frames baked by BATIQ with its ACES 2.0 output"
            " transform (sRGB display, SDR 100 nits), encoded by core"
            " Extract Review from its profiles."
        ),
    )


class PublishPluginsModel(BaseSettingsModel):
    ExtractReviewIntermediates: ExtractReviewIntermediatesModel = SettingsField(
        default_factory=ExtractReviewIntermediatesModel,
        title="Extract Review Intermediates",
    )
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
        "ExtractReviewIntermediates": {
            "enabled": True,
            "outputs": [
                {
                    "name": "aces20",
                    "extension": "png",
                    "publish": False,
                    "filter": {"task_types": [], "product_names": []},
                    "add_custom_tags": [],
                },
            ],
        },
        "ValidateBatiqContextSettings": {
            "enabled": True,
            "optional": True,
            "active": True,
        },
    },
}
