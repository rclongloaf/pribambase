"""Blender-side smoke test for add-on import, registration, and cleanup."""

from __future__ import annotations

import importlib
import socket
import sys
from pathlib import Path

import bpy


def script_arguments() -> list[str]:
    try:
        separator = sys.argv.index("--")
    except ValueError:
        return []
    return sys.argv[separator + 1 :]


def assert_property(owner: type, name: str, expected: bool) -> None:
    present = hasattr(owner, name)
    assert present is expected, f"{owner.__name__}.{name}: expected present={expected}"


def main() -> None:
    arguments = script_arguments()
    if len(arguments) != 2:
        raise RuntimeError("Expected the project and dependency paths after '--'.")

    project_root = Path(arguments[0]).resolve()
    dependencies = str(Path(arguments[1]).resolve())
    sys.path.insert(0, dependencies)
    sys.path.insert(0, str(project_root.parent))
    addon = importlib.import_module(project_root.name)

    assert addon.bl_info["name"] == "Pribambase"
    assert tuple(addon.bl_info["blender"]) <= tuple(bpy.app.version)

    registered = False
    preferences_entry = None
    created_preferences = False
    try:
        addon.register()
        registered = True

        preferences_entry = bpy.context.preferences.addons.get(project_root.name)
        if preferences_entry is None:
            preferences_entry = bpy.context.preferences.addons.new()
            preferences_entry.module = project_root.name
            created_preferences = True

        for owner, name in (
            (bpy.types.Scene, "sb_state"),
            (bpy.types.Image, "sb_source"),
            (bpy.types.Image, "sb_scale"),
            (bpy.types.Image, "sb_offset"),
        ):
            assert_property(owner, name, True)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            preferences_entry.preferences.port = probe.getsockname()[1]
        preferences_entry.preferences.localhost = True

        assert bpy.ops.pribambase.start_server() == {"FINISHED"}
        assert addon.addon.server_up
        assert not addon.addon.connected
        assert bpy.ops.pribambase.stop_server() == {"FINISHED"}
        assert not addon.addon.server_up
    finally:
        if addon.addon.server_up:
            addon.addon.stop_server()
        if created_preferences:
            bpy.context.preferences.addons.remove(preferences_entry)
        if registered:
            addon.unregister()

    for owner, name in (
        (bpy.types.Scene, "sb_state"),
        (bpy.types.Image, "sb_source"),
        (bpy.types.Image, "sb_scale"),
        (bpy.types.Image, "sb_offset"),
    ):
        assert_property(owner, name, False)

    print(f"Pribambase smoke test passed on Blender {bpy.app.version_string}")


main()
