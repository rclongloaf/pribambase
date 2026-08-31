"""Load the working tree as a Blender add-on and provide an in-app reload operator."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy


def script_arguments() -> list[str]:
    try:
        separator = sys.argv.index("--")
    except ValueError:
        return []
    return sys.argv[separator + 1 :]


arguments = script_arguments()
if len(arguments) not in (2, 5):
    raise RuntimeError(
        "Expected project and dependency paths, optionally followed by '--debug HOST PORT'."
    )

PROJECT_ROOT = Path(arguments[0]).resolve()
ADDON_ROOT = PROJECT_ROOT / "blender"
DEPENDENCIES = str(Path(arguments[1]).resolve())
MODULE_NAME = "pribambase"
if DEPENDENCIES not in sys.path:
    sys.path.insert(0, DEPENDENCIES)
TOOLS_ROOT = str(PROJECT_ROOT / "tools")
if TOOLS_ROOT not in sys.path:
    sys.path.insert(0, TOOLS_ROOT)

from addon_loader import load_addon_module

if len(arguments) == 5:
    if arguments[2] != "--debug":
        raise RuntimeError("Unknown Blender development startup arguments.")
    debug_host = arguments[3]
    try:
        debug_port = int(arguments[4])
    except ValueError as exc:
        raise RuntimeError(f"Invalid debug port: {arguments[4]!r}") from exc

    import debugpy

    debugpy.listen((debug_host, debug_port))
    print(
        f"Pribambase dev: waiting for PyCharm DAP debugger at {debug_host}:{debug_port}...",
        flush=True,
    )
    debugpy.wait_for_client()
    print("Pribambase dev: debugger connected.", flush=True)

addon_module = None
development_preferences = None


def ensure_addon_preferences() -> None:
    """Create the preferences entry Blender normally adds when enabling an add-on."""
    global development_preferences

    preferences = bpy.context.preferences
    entry = preferences.addons.get(MODULE_NAME)
    if entry is not None:
        return

    entry = preferences.addons.new()
    entry.module = MODULE_NAME
    development_preferences = entry

    # The development entry is process-local and must not leak into the user's
    # regular Blender configuration, where this checkout may not be importable.
    preferences.use_preferences_save = False
    print("Pribambase dev: created temporary add-on preferences.")


def unload_addon() -> None:
    global addon_module
    if addon_module is not None:
        addon_module.unregister()
        addon_module = None

    prefix = f"{MODULE_NAME}."
    for name in tuple(sys.modules):
        if name == MODULE_NAME or name.startswith(prefix):
            del sys.modules[name]


def load_addon() -> None:
    global addon_module
    unload_addon()
    importlib.invalidate_caches()
    addon_module = load_addon_module(PROJECT_ROOT, MODULE_NAME)
    addon_module.register()
    ensure_addon_preferences()
    print(f"Pribambase dev: loaded from {ADDON_ROOT}")


class PRIBAMBASE_OT_reload_dev(bpy.types.Operator):
    bl_idname = "wm.pribambase_reload_dev"
    bl_label = "Reload Pribambase (Dev)"
    bl_description = "Reload Pribambase directly from the development working tree"

    def execute(self, _context):
        try:
            load_addon()
        except Exception as error:  # Blender also prints the full traceback.
            self.report({"ERROR"}, f"Reload failed: {error}")
            raise
        self.report({"INFO"}, "Pribambase reloaded")
        return {"FINISHED"}


load_addon()
bpy.utils.register_class(PRIBAMBASE_OT_reload_dev)
bpy.context.preferences.view.show_developer_ui = True
print("Pribambase dev: use F3 > Reload Pribambase (Dev) after editing source files.")
