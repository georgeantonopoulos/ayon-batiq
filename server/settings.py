"""No settings are required for the initial BATIQ host integration."""
from typing import Any

from ayon_server.settings import BaseSettingsModel

DEFAULT_VALUES: dict[str, Any] = {}


class BatiqSettings(BaseSettingsModel):
    """Placeholder for future server-configured BATIQ integration settings."""
