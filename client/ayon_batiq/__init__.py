"""AYON host integration for BATIQ.

The root stays standard-library-only so BATIQ can import the isolated startup
package without having AYON Core in its embedded interpreter.
"""

__all__ = ["BatiqAddon"]


def __getattr__(name):
    if name == "BatiqAddon":
        from .addon import BatiqAddon

        return BatiqAddon
    raise AttributeError(name)


def __dir__():
    """Advertise the lazy add-on class to AYON's dir-based discovery."""
    return sorted(set(globals()) | {"BatiqAddon"})
