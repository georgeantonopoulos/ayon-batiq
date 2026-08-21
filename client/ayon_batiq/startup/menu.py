"""Native BATIQ menu registration; deliberately independent of AYON/Qt."""

MENU_ITEMS = ("Workfiles...", "Load...", "Manage...", "Publish...")


def register_menu(ui, show_tool):
    for label in MENU_ITEMS:
        ui.add_menu_action("AYON/" + label, lambda name=label: show_tool(name[:-3].lower()))
