"""Blender-side smoke test for add-on import, registration, and cleanup."""

from __future__ import annotations

import importlib
import asyncio
import math
import socket
import struct
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


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
    sys.path.insert(0, str(project_root / "tools"))
    from addon_loader import ADDON_MODULE_NAME, load_addon_module

    addon = load_addon_module(project_root)

    assert addon.bl_info["name"] == "Pribambase"
    assert tuple(addon.bl_info["blender"]) <= tuple(bpy.app.version)

    registered = False
    preferences_entry = None
    created_preferences = False
    try:
        addon.register()
        registered = True

        preferences_entry = bpy.context.preferences.addons.get(ADDON_MODULE_NAME)
        if preferences_entry is None:
            preferences_entry = bpy.context.preferences.addons.new()
            preferences_entry.module = ADDON_MODULE_NAME
            created_preferences = True

        for owner, name in (
            (bpy.types.Scene, "sb_state"),
            (bpy.types.Image, "sb_source"),
        ):
            assert_property(owner, name, True)
        assert_property(bpy.types.Image, "sb_scale", False)
        assert_property(bpy.types.Image, "sb_offset", False)

        state = bpy.context.scene.sb_state
        assert state.auto_render_current
        assert state.follow_frame
        assert state.guide_layer == "Pribambase Render"
        assert hasattr(bpy.ops.pribambase, "sync_start")
        assert hasattr(bpy.ops.pribambase, "projection_current")
        assert hasattr(bpy.ops.pribambase, "projection_recalculate")
        assert hasattr(bpy.ops.pribambase, "projection_restore_camera")
        assert hasattr(bpy.ops.pribambase, "projection_setup_material")

        projection = importlib.import_module(f"{ADDON_MODULE_NAME}.projection")
        scene = bpy.context.scene
        cube = bpy.data.objects["Cube"]
        scene.frame_start = 1
        scene.frame_end = 2
        scene.frame_set(1)
        cube.scale = (1.0, 1.0, 1.0)
        cube.keyframe_insert(data_path="scale")
        scene.frame_set(2)
        cube.scale = (2.0, 1.0, 1.0)
        cube.keyframe_insert(data_path="scale")
        scene.frame_set(1)

        canvas = projection.calculate_animation_layout(scene)
        assert canvas.width >= 84, "Canvas did not include the largest animation frame"
        assert canvas.min_x <= 0 <= canvas.max_x
        assert canvas.min_y <= 0 <= canvas.max_y
        projection.set_state_layout(scene, canvas)

        resize_test = bpy.data.images.new(
            "PribambaseCanvasResize",
            width=2,
            height=3,
            alpha=True,
        )
        resize_pixels = [0.0] * (2 * 3 * 4)
        resize_pixels[0:4] = (1.0, 0.0, 0.0, 1.0)
        resize_test.pixels.foreach_set(resize_pixels)
        projection.resize_image_canvas(
            resize_test,
            projection.Layout(-1, -1, 1, 2),
            projection.Layout(-3, -4, 2, 3),
        )
        assert tuple(resize_test.size) == (5, 7)
        shifted_index = (3 * 5 + 2) * 4
        assert tuple(resize_test.pixels[shifted_index : shifted_index + 4]) == (
            1.0,
            0.0,
            0.0,
            1.0,
        )

        image = bpy.data.images.new(
            "PribambaseSmokeTexture",
            width=canvas.width,
            height=canvas.height,
            alpha=True,
        )
        material = projection.ensure_project_material(scene, image)
        assert projection.assign_project_material(scene, material) == 1
        assert material.get("pribambase_project_material")
        assert any(
            node.get("pribambase_role") == "projection"
            for node in material.node_tree.nodes
        )
        orme = state.material_image
        assert orme is not None
        assert orme.colorspace_settings.name == "Non-Color"
        assert any(
            node.get("pribambase_role") == "orme" and node.image == orme
            for node in material.node_tree.nodes
        )
        master = next(
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "master"
        )
        master_tree = master.node_tree
        assert material.get("pribambase_material_schema") == 3
        assert master_tree.name == "PB_MasterShader_v3"
        assert master_tree.get("pribambase_material_schema") == 3
        assert master_tree.get("pribambase_ao_mode") == "light-weighted-eevee"
        assert master.outputs.get("EEVEE Shader") is not None
        assert master.outputs.get("Cycles Shader") is not None
        assert master.inputs.get("Ambient Occlusion") is not None
        assert master.inputs.get("Roughness") is not None
        assert master.inputs.get("Metallic") is not None
        assert master.inputs.get("Emission Mask") is not None

        def role(name):
            return next(
                node
                for node in master_tree.nodes
                if node.get("pribambase_role") == name
            )

        def linked_from(socket, source_role):
            return any(
                link.from_node.get("pribambase_role") == source_role
                for link in socket.links
            )

        group_input = next(node for node in master_tree.nodes if node.type == 'GROUP_INPUT')
        eevee_pbr = role("eevee-pbr-lighting")
        cycles_pbr = role("cycles-pbr")
        for pbr in (eevee_pbr, cycles_pbr):
            assert any(
                link.from_node == group_input and link.from_socket.name == "Base Color"
                for link in pbr.inputs['Base Color'].links
            ), "Base Color must enter the PBR shader without AO pre-multiplication"
            assert any(
                link.from_node == group_input and link.from_socket.name == "Roughness"
                for link in pbr.inputs['Roughness'].links
            )
            assert any(
                link.from_node == group_input and link.from_socket.name == "Metallic"
                for link in pbr.inputs['Metallic'].links
            )
        assert not any(
            link.to_node in {eevee_pbr, cycles_pbr}
            for link in group_input.outputs['Ambient Occlusion'].links
        ), "AO must not modify Base Color or another Principled input"
        assert any(
            link.from_node == group_input and link.from_socket.name == "Ambient Occlusion"
            for link in role("ao-inverse").inputs[1].links
        )
        assert any(
            link.from_node == group_input and link.from_socket.name == "Roughness"
            for link in role("ao-inverse-roughness").inputs[1].links
        )
        assert any(
            link.from_node == group_input and link.from_socket.name == "Metallic"
            for link in role("ao-smooth-metal").inputs[0].links
        )
        assert linked_from(role("ao-smooth-metal").inputs[1], "ao-inverse-roughness")
        assert linked_from(role("ao-material-weight").inputs[1], "ao-smooth-metal")
        assert linked_from(role("ao-by-material").inputs[1], "ao-material-weight")
        assert linked_from(role("ao-lit-color").inputs[1], "eevee-lighting-color")
        assert linked_from(role("eevee-final-color").inputs[2], "emission-color")
        assert linked_from(role("eevee-output").inputs['Color'], "eevee-final-color")
        output_targets = {
            node.get("pribambase_role"): node.target
            for node in material.node_tree.nodes
            if node.type == 'OUTPUT_MATERIAL'
        }
        assert output_targets == {
            "eevee-material-output": "EEVEE",
            "cycles-material-output": "CYCLES",
        }
        state.emission_strength = 3.5
        assert master.inputs["Emission Strength"].default_value == 3.5

        # Existing v2 project materials are rebuilt in-place and keep their
        # scene-level controls when the add-on is reloaded.
        material["pribambase_material_schema"] = 2
        projection.update_project_material(scene)
        assert material.get("pribambase_material_schema") == 3
        master = next(
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "master"
        )
        assert master.node_tree.name == "PB_MasterShader_v3"
        assert master.inputs["Emission Strength"].default_value == 3.5

        preferences_entry.preferences.skip_modal = True
        image_name = image.name.encode("utf-8")
        disabled_pixels = bytes((204, 204, 204, 255)) * (canvas.width * canvas.height)
        restored_pixels = bytes((17, 34, 51, 255)) * (canvas.width * canvas.height)

        def image_message(pixels):
            return (
                b"I"
                + struct.pack("<HHI", canvas.width, canvas.height, len(image_name))
                + image_name
                + struct.pack("<I", len(pixels))
                + pixels
            )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(addon.addon.handlers.process(image_message(disabled_pixels)))
        assert all(abs(value - 204 / 255) < 1e-5 for value in image.pixels[:3])
        loop.run_until_complete(addon.addon.handlers.process(image_message(restored_pixels)))
        assert all(
            abs(actual - expected) < 1e-5
            for actual, expected in zip(image.pixels[:3], (17 / 255, 34 / 255, 51 / 255))
        ), "A re-enabled Base Color texture was not restored in Blender"

        channel_pixels = bytes((255, 64, 128, 32)) * (canvas.width * canvas.height)
        channel = b"orme"
        source = b"roundtrip_texture.aseprite"
        channel_message = (
            b"P"
            + struct.pack("<HHI", canvas.width, canvas.height, 1)
            + struct.pack("<I", len(channel))
            + channel
            + struct.pack("<I", len(source))
            + source
            + struct.pack("<I", len(channel_pixels))
            + channel_pixels
        )
        loop.run_until_complete(addon.addon.handlers.process(channel_message))
        assert state.material_frame == 1
        received = tuple(orme.pixels[:4])
        assert all(
            abs(actual - expected) < 1e-5
            for actual, expected in zip(received, (1.0, 64 / 255, 128 / 255, 32 / 255))
        ), received

        camera = projection.restore_projection_camera(scene)
        assert camera.data.type == 'ORTHO'
        assert scene.render.resolution_x == canvas.width
        assert scene.render.resolution_y == canvas.height
        assert math.isclose(
            scene.render.filter_size,
            projection.PIXEL_FILTER_SIZE,
            rel_tol=1e-6,
        )
        for pixel, expected in (
            ((canvas.min_x, canvas.min_y), (0.0, 0.0)),
            ((canvas.max_x, canvas.max_y), (1.0, 1.0)),
        ):
            projected_y = pixel[1] / projection.PIXELS_PER_UNIT
            point = Vector(
                (
                    pixel[0] / projection.PIXELS_PER_UNIT,
                    projected_y * math.sin(projection.PROJECTION_ELEVATION),
                    projected_y * math.cos(projection.PROJECTION_ELEVATION),
                )
            )
            ndc = world_to_camera_view(scene, camera, point)
            details = (
                pixel,
                expected,
                tuple(ndc),
                canvas,
                (scene.render.resolution_x, scene.render.resolution_y),
                camera.data.ortho_scale,
                tuple(camera.scale),
                tuple(camera.matrix_world.normalized().inverted() @ point),
            )
            assert abs(ndc.x - expected[0]) < 1e-5, details
            assert abs(ndc.y - expected[1]) < 1e-5, details

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            preferences_entry.preferences.port = probe.getsockname()[1]
        preferences_entry.preferences.localhost = True

        assert bpy.ops.pribambase.start_server() == {"FINISHED"}
        assert addon.addon.server_up
        assert not addon.addon.connected
        assert bpy.ops.pribambase.stop_server() == {"FINISHED"}
        assert not addon.addon.server_up

        state.sprite_path = str(project_root / "examples" / "roundtrip" / "roundtrip_texture.aseprite")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            preferences_entry.preferences.port = probe.getsockname()[1]
        assert bpy.ops.pribambase.sync_start() == {"FINISHED"}
        assert addon.addon.server_up
        workspace = importlib.import_module(f"{ADDON_MODULE_NAME}.workspace")
        util = importlib.import_module(f"{ADDON_MODULE_NAME}.util")

        class ModalProbe(util.ModalExecuteMixin):
            def __init__(self):
                self.timer = object()
                self.applied = 0

            def modal_execute(self, _context):
                self.applied += 1
                return {"FINISHED"}

        class WindowManagerProbe:
            def __init__(self):
                self.removed = []

            def event_timer_remove(self, timer):
                self.removed.append(timer)

        class ContextProbe:
            def __init__(self):
                self.window_manager = WindowManagerProbe()

        class EventProbe:
            def __init__(self, event_type):
                self.type = event_type

        modal_probe = ModalProbe()
        context_probe = ContextProbe()
        assert modal_probe.modal(context_probe, EventProbe("MOUSEMOVE")) == {"RUNNING_MODAL"}
        assert modal_probe.applied == 0
        assert modal_probe.modal(
            context_probe,
            EventProbe("TIMER"),
        ) == {"FINISHED"}
        assert modal_probe.applied == 1
        assert context_probe.window_manager.removed == [modal_probe.timer]

        state.projection_bounds_dirty = True
        assert bpy.ops.pribambase.projection_recalculate() == {"FINISHED"}
        bpy.context.view_layer.update()
        assert not state.projection_bounds_dirty, (
            "A material refresh brought the bounds warning back after recalculation"
        )

        class Update:
            def __init__(self, item, *, geometry=False, transform=False, shading=False):
                self.id = item
                self.is_updated_geometry = geometry
                self.is_updated_transform = transform
                self.is_updated_shading = shading

        shading_updates = (
            Update(cube, shading=True),
            Update(cube.data, shading=True),
            Update(material, shading=True),
        )
        assert not workspace._projection_bounds_changed(scene, shading_updates)
        assert workspace._projection_bounds_changed(
            scene,
            (Update(cube, transform=True),),
        )

        class Depsgraph:
            def __init__(self, updates):
                self.updates = updates

        state.projection_bounds_dirty = False
        workspace.on_depsgraph_update(scene, Depsgraph(shading_updates))
        assert not state.projection_bounds_dirty
        workspace.on_depsgraph_update(
            scene,
            Depsgraph((Update(cube, transform=True),)),
        )
        assert state.projection_bounds_dirty
        projection.set_state_layout(scene, canvas)

        workspace.mark_current_frame_dirty(bpy.context.scene)
        assert workspace.dirty_frames() == (bpy.context.scene.frame_current,)
        assert bpy.ops.pribambase.sync_stop() == {"FINISHED"}
        assert not addon.addon.server_up
        assert workspace.dirty_frames() == ()
        loop.close()
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
    ):
        assert_property(owner, name, False)

    print(f"Pribambase smoke test passed on Blender {bpy.app.version_string}")


main()
