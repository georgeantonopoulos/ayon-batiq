"""Native BATIQ menu registration; deliberately independent of AYON/Qt."""

# (menu label, helper tool)
MENU_ITEMS = (
    ("Workfiles...", "workfiles"),
    ("Load...", "load"),
    ("Manage...", "manage"),
    ("Publish...", "publish"),
    ("Set Frame Range", "set_frame_range"),
    ("Set Resolution", "set_resolution"),
    ("Apply All Settings", "apply_settings"),
)


def register_menu(ui, show_tool):
    for label, tool in MENU_ITEMS:
        ui.add_menu_action("AYON/" + label, lambda name=tool: show_tool(name))
