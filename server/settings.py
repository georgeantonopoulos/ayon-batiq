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


class ImageIOFileRuleModel(BaseSettingsModel):
    name: str = SettingsField("", title="Rule name")
    pattern: str = SettingsField("", title="Regex pattern")
    colorspace: str = SettingsField("", title="Colorspace name")
    ext: str = SettingsField("", title="File extension")


class ImageIOFileRulesModel(BaseSettingsModel):
    _isGroup: bool = True

    activate_host_rules: bool = SettingsField(False)
    rules: list[ImageIOFileRuleModel] = SettingsField(default_factory=list, title="Rules")


class ImageIOSettings(BaseSettingsModel):
    """Core colour management for BATIQ; without it Core treats the host as unmanaged."""

    activate_host_color_management: bool = SettingsField(
        True, title="Enable Color Management"
    )
    file_rules: ImageIOFileRulesModel = SettingsField(
        default_factory=ImageIOFileRulesModel, title="File Rules"
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


def write_formats_enum():
    return [
        {"value": "exr", "label": "OpenEXR"}, {"value": "tif", "label": "TIFF"},
        {"value": "dpx", "label": "DPX"}, {"value": "png", "label": "PNG"},
        {"value": "jpeg", "label": "JPEG"},
    ]


def write_datatypes_enum():
    return [
        {"value": "half", "label": "16 bit half"}, {"value": "float", "label": "32 bit float"},
        {"value": "8", "label": "8 bit"}, {"value": "10", "label": "10 bit"},
        {"value": "16", "label": "16 bit"},
    ]


def write_compressions_enum():
    # BATIQ 0.2.26 writes these; anything else (e.g. DWAA) silently becomes ZIP.
    return [
        {"value": "zip", "label": "ZIP"}, {"value": "piz", "label": "PIZ"},
        {"value": "rle", "label": "RLE"}, {"value": "none", "label": "None"},
    ]


def write_channels_enum():
    return ["rgb", "rgba", "all", "alpha"]


class WriteNodeModel(BaseSettingsModel):
    file_format: str = SettingsField("exr", title="File format", enum_resolver=write_formats_enum)
    datatype: str = SettingsField("half", title="Data type", enum_resolver=write_datatypes_enum)
    compression: str = SettingsField(
        "zip", title="EXR compression", enum_resolver=write_compressions_enum
    )
    channels: str = SettingsField("rgba", title="Channels", enum_resolver=write_channels_enum)
    colorspace: str = SettingsField(
        "scene_linear",
        title="Colorspace",
        description=(
            "An OCIO role (scene_linear, color_picking, ...) or colorspace name,"
            " resolved in the project's OCIO config."
        ),
    )


class CreateWriteModel(BaseSettingsModel):
    enabled: bool = SettingsField(True, title="Enabled")
    default_variants: list[str] = SettingsField(default_factory=list, title="Default variants")
    temp_rendering_path_template: str = SettingsField(
        "", title="Rendering path template",
        description="Where the Write renders locally. Keys: work, product[name], frame, ext.",
    )
    review: bool = SettingsField(True, title="Review by default")
    write: WriteNodeModel = SettingsField(default_factory=WriteNodeModel, title="Write node")


class CreatePluginsModel(BaseSettingsModel):
    CreateWriteRender: CreateWriteModel = SettingsField(
        default_factory=CreateWriteModel, title="Render (write)"
    )
    CreateWritePrerender: CreateWriteModel = SettingsField(
        default_factory=CreateWriteModel, title="Prerender (write)"
    )
    CreateWriteImage: CreateWriteModel = SettingsField(
        default_factory=CreateWriteModel, title="Image (write)"
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
    ValidateBatiqWrite: OptionalPluginModel = SettingsField(
        default_factory=OptionalPluginModel,
        title="Validate Write Node",
        description="Format, data type, compression, channels, colorspace and path match the creator.",
    )
    ValidateBatiqWriteFrameRange: OptionalPluginModel = SettingsField(
        default_factory=OptionalPluginModel,
        title="Validate Frame Range",
        description="Renders cover the task range with handles, unless a custom range is set.",
    )
    ValidateBatiqInstanceContext: OptionalPluginModel = SettingsField(
        default_factory=OptionalPluginModel,
        title="Validate Folder Context",
        description="Instances publish to the workfile's folder and task.",
    )


class BatiqSettings(BaseSettingsModel):
    imageio: ImageIOSettings = SettingsField(
        default_factory=ImageIOSettings, title="Color Management (ImageIO)"
    )
    workfile: WorkfileModel = SettingsField(
        default_factory=WorkfileModel, title="Workfile"
    )
    colorspace: ColorspaceModel = SettingsField(
        default_factory=ColorspaceModel, title="Colorspace"
    )
    create: CreatePluginsModel = SettingsField(
        default_factory=CreatePluginsModel, title="Creator plugins"
    )
    publish: PublishPluginsModel = SettingsField(
        default_factory=PublishPluginsModel, title="Publish plugins"
    )


DEFAULT_VALUES: dict[str, Any] = {
    "imageio": {
        "activate_host_color_management": True,
        "file_rules": {"activate_host_rules": False, "rules": []},
    },
    "workfile": {"apply_context_on_launch": True},
    "colorspace": {"rules": []},
    # Mirrors BCN's Nuke write creators; DWAA is not available in BATIQ, so ZIP.
    "create": {
        "CreateWriteRender": {
            "enabled": True,
            "default_variants": ["Main", "Mask"],
            "temp_rendering_path_template": (
                "{work}/renders/batiq/{product[name]}/{product[name]}.{frame}.{ext}"),
            "review": True,
            "write": {"file_format": "exr", "datatype": "half", "compression": "zip",
                      "channels": "rgb", "colorspace": "scene_linear"},
        },
        "CreateWritePrerender": {
            "enabled": True,
            "default_variants": ["MOCKUP", "FLAT", "BG", "CONTAINER", "FG"],
            "temp_rendering_path_template": (
                "{work}/renders/batiq/{product[name]}/{product[name]}.{frame}.{ext}"),
            "review": True,
            "write": {"file_format": "exr", "datatype": "half", "compression": "zip",
                      "channels": "rgba", "colorspace": "scene_linear"},
        },
        "CreateWriteImage": {
            "enabled": True,
            "default_variants": ["StillFrame", "MPFrame", "LayoutFrame"],
            "temp_rendering_path_template": (
                "{work}/renders/batiq/{product[name]}/{product[name]}.{ext}"),
            "review": False,
            "write": {"file_format": "png", "datatype": "8", "compression": "zip",
                      "channels": "rgba", "colorspace": "color_picking"},
        },
    },
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
        "ValidateBatiqWrite": {"enabled": True, "optional": True, "active": True},
        "ValidateBatiqWriteFrameRange": {"enabled": True, "optional": True, "active": True},
        "ValidateBatiqInstanceContext": {"enabled": True, "optional": True, "active": True},
    },
}
