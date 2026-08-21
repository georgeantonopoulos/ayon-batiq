"""BATIQ's server-recognised AYON add-on entry point."""
from typing import Type

from ayon_server.addons import BaseServerAddon

from .settings import BatiqSettings, DEFAULT_VALUES


class BatiqAddon(BaseServerAddon):
    """Settings-only server half; host implementation lives in ``client``."""

    settings_model: Type[BatiqSettings] = BatiqSettings

    async def get_default_settings(self) -> BatiqSettings:
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_VALUES)
