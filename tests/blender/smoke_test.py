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
import numpy as np
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
        assert hasattr(bpy.ops.pribambase, "projection_view_camera")
        assert hasattr(bpy.ops.pribambase, "projection_setup_material")
        assert hasattr(bpy.ops.pribambase, "detail_paint")
        assert hasattr(bpy.ops.pribambase, "detail_initialize")
        assert hasattr(bpy.ops.pribambase, "detail_pick_normal")
        assert hasattr(bpy.ops.pribambase, "detail_free_pick_normal")
        assert hasattr(bpy.ops.pribambase, "detail_rebuild")

        projection = importlib.import_module(f"{ADDON_MODULE_NAME}.projection")
        normal_picker = importlib.import_module(f"{ADDON_MODULE_NAME}.normal_picker")
        assert state.detail_picker_mode == 'QUANTIZED'
        assert state.detail_picker_divisions == 4
        assert normal_picker.direction_from_disk(0.0, 0.0).dot(normal_picker.FRONT) > 0.999
        assert normal_picker.direction_from_disk(1.0, 0.0).dot(normal_picker.RIGHT) > 0.999
        direction_counts = []
        for divisions in (2, 3, 4):
            directions = normal_picker.palette_directions(divisions)
            direction_counts.append(len(directions))
            assert all(
                math.isclose(direction.length, 1.0, abs_tol=1e-6)
                for direction in directions
            )
        assert direction_counts == sorted(direction_counts)
        half_xz = Vector((1.0, 0.0, 1.0)).normalized()
        assert any(
            half_xz.dot(direction) > 0.999999
            for direction in normal_picker.palette_directions(2)
        )
        third_xz = Vector((math.cos(math.radians(30.0)), 0.0, math.sin(math.radians(30.0))))
        assert any(
            third_xz.dot(direction) > 0.999999
            for direction in normal_picker.palette_directions(3)
        )
        quantized = normal_picker.quantize_direction((0.2, -0.5, 0.8), 4)
        assert any(
            quantized.dot(direction) > 0.999999
            for direction in normal_picker.palette_directions(4)
        )
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
        assert material.get("pribambase_material_schema") == 8
        assert master_tree.name == "PB_MasterShader_v4"
        assert master_tree.get("pribambase_material_schema") == 4
        assert master_tree.get("pribambase_ao_mode") == "light-weighted-eevee"
        assert master.outputs.get("EEVEE Shader") is not None
        assert master.outputs.get("Cycles Shader") is not None
        assert master.inputs.get("Ambient Occlusion") is not None
        assert master.inputs.get("Roughness") is not None
        assert master.inputs.get("Metallic") is not None
        assert master.inputs.get("Emission Mask") is not None
        assert master.inputs.get("Surface Normal") is not None

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
            assert any(
                link.from_node == group_input and link.from_socket.name == "Surface Normal"
                for link in pbr.inputs['Normal'].links
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

        # Existing project materials are rebuilt in-place and keep their
        # scene-level controls when the add-on is reloaded.
        material["pribambase_material_schema"] = 5
        projection.update_project_material(scene)
        assert material.get("pribambase_material_schema") == 8
        master = next(
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "master"
        )
        assert master.node_tree.name == "PB_MasterShader_v4"
        assert master.inputs["Emission Strength"].default_value == 3.5

        detail = importlib.import_module(f"{ADDON_MODULE_NAME}.detail")
        source = detail.initialize_source(scene)
        geometry_reference = detail.geometry_normal_image(scene)
        assert geometry_reference is not None
        assert detail.dirty_frames() == (1,)
        assert tuple(source.size) == (
            canvas.width * detail.EDIT_SCALE,
            canvas.height * detail.EDIT_SCALE,
        )
        assert source.colorspace_settings.name == "Non-Color"
        assert tuple(geometry_reference.size) == (canvas.width, canvas.height)
        assert geometry_reference.colorspace_settings.name == "Non-Color"
        assert geometry_reference.get("pribambase_edit_scale") == 1
        geometry_reference_pixels = tuple(geometry_reference.pixels[:])
        assert max(geometry_reference_pixels[3::4]) > 0.5
        origin_pixel = detail._source_pixel_at_location(scene, source, Vector((0.0, 0.0, 0.0)))
        assert origin_pixel is not None
        state.detail_pixel_scope = 'EDIT'
        x0, x1, y0, y1 = detail._pixel_scope_bounds(scene, source, *origin_pixel)
        assert (x1 - x0, y1 - y0) == (1, 1)
        state.detail_pixel_scope = 'OUTPUT'
        x0, x1, y0, y1 = detail._pixel_scope_bounds(scene, source, *origin_pixel)
        assert (x1 - x0, y1 - y0) == (detail.EDIT_SCALE, detail.EDIT_SCALE)
        state.detail_set_size = 3
        x0, x1, y0, y1 = detail._set_brush_bounds(
            scene,
            source,
            *origin_pixel,
            state.detail_set_size,
        )
        assert (x1 - x0, y1 - y0) == (3 * detail.EDIT_SCALE, 3 * detail.EDIT_SCALE)
        state.detail_pixel_scope = 'EDIT'
        x0, x1, y0, y1 = detail._set_brush_bounds(
            scene,
            source,
            *origin_pixel,
            state.detail_set_size,
        )
        assert (x1 - x0, y1 - y0) == (3, 3)
        state.detail_pixel_scope = 'OUTPUT'
        state.detail_set_size = 1
        assert detail._step_set_size(state, -1)
        assert state.detail_pixel_scope == 'EDIT'
        assert state.detail_set_size == 1
        assert detail._step_set_size(state, 1)
        assert state.detail_pixel_scope == 'OUTPUT'
        assert state.detail_set_size == 1

        source_pixels = list(source.pixels[:])
        edited_output = None
        for output_y in range(canvas.height):
            for output_x in range(canvas.width):
                offsets = [
                    (
                        ((output_y * detail.EDIT_SCALE + sub_y) * source.size[0]
                        + output_x * detail.EDIT_SCALE + sub_x)
                        * 4
                    )
                    for sub_y in range(detail.EDIT_SCALE)
                    for sub_x in range(detail.EDIT_SCALE)
                ]
                if all(source_pixels[offset + 3] > 0.5 for offset in offsets):
                    edited_output = (output_x, output_y, offsets)
                    break
            if edited_output is not None:
                break
        assert edited_output is not None, "Normal source has no fully covered 2×2 output pixel"
        for index, offset in enumerate(edited_output[2]):
            source_pixels[offset : offset + 3] = (
                (1.0, 0.5, 0.5) if index < 2 else (0.5, 0.5, 1.0)
            )
        source.pixels.foreach_set(source_pixels)
        source.update()
        generated = detail.generate_normal(scene, send=False)
        assert tuple(geometry_reference.pixels[:]) == geometry_reference_pixels
        assert detail.dirty_frames() == ()
        assert tuple(generated.size) == (canvas.width, canvas.height)
        assert generated.colorspace_settings.name == "Non-Color"
        assert generated.get("pribambase_detail_valid")
        assert max(generated.pixels[3::4]) > 0.5
        generated_pixels = tuple(generated.pixels[:])
        covered_normals = []
        for offset in range(0, len(generated_pixels), 4):
            if generated_pixels[offset + 3] <= 0.5:
                continue
            vector = tuple(generated_pixels[offset + axis] * 2.0 - 1.0 for axis in range(3))
            assert math.isclose(
                math.sqrt(sum(component * component for component in vector)),
                1.0,
                # The delivered base-resolution image is intentionally 8-bit,
                # so decoded unit vectors carry normal RGB quantization error.
                abs_tol=1.5e-2,
            )
            covered_normals.append(tuple(round(component, 2) for component in vector))
        assert len(set(covered_normals)) > 1, "World Normal output lost the cube's surface directions"
        output_offset = (edited_output[1] * canvas.width + edited_output[0]) * 4
        mixed = tuple(generated_pixels[output_offset + axis] * 2.0 - 1.0 for axis in range(3))
        assert math.isclose(mixed[0], math.sqrt(0.5), abs_tol=0.02)
        assert abs(mixed[1]) < 0.02
        assert math.isclose(mixed[2], math.sqrt(0.5), abs_tol=0.02)
        projection.update_project_material(scene)
        normal_texture = next(
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "world-normal"
        )
        normal_map = next(
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "world-normal-map"
        )
        assert normal_texture.image == generated
        assert normal_texture.interpolation == "Closest"
        assert normal_map.space == "WORLD"
        assert normal_map.inputs['Strength'].default_value == 1.0
        output_nodes = {
            node.get("pribambase_role"): node
            for node in material.node_tree.nodes
            if node.type == 'OUTPUT_MATERIAL'
        }
        state.detail_preview_mode = 'NORMAL_EDIT'
        assert all(
            socket.links[0].from_node.get("pribambase_role") == "normal-edit-preview-shader"
            for node in output_nodes.values()
            for socket in (node.inputs['Surface'],)
        )
        with projection.guide_material_context(scene):
            assert all(
                socket.links[0].from_node.get("pribambase_role") == "master"
                for node in output_nodes.values()
                for socket in (node.inputs['Surface'],)
            )
        assert all(
            socket.links[0].from_node.get("pribambase_role") == "normal-edit-preview-shader"
            for node in output_nodes.values()
            for socket in (node.inputs['Surface'],)
        )
        edit_preview = next(
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "normal-edit-preview"
        )
        assert edit_preview.image == source
        assert edit_preview.interpolation == "Closest"
        state.detail_preview_mode = 'GEOMETRY_NORMAL'
        assert all(
            socket.links[0].from_node.get("pribambase_role")
            == "geometry-normal-preview-shader"
            for node in output_nodes.values()
            for socket in (node.inputs['Surface'],)
        )
        geometry_preview = next(
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "geometry-normal-preview"
        )
        assert geometry_preview.image == geometry_reference
        assert geometry_preview.interpolation == "Closest"
        state.detail_preview_mode = 'FINAL_NORMAL'
        assert all(
            socket.links[0].from_node.get("pribambase_role")
            == "final-normal-preview-shader"
            for node in output_nodes.values()
            for socket in (node.inputs['Surface'],)
        )
        final_preview_shader = next(
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "final-normal-preview-shader"
        )
        assert final_preview_shader.inputs['Color'].links[0].from_node == normal_texture
        state.detail_preview_mode = 'MATERIAL'
        assert all(
            socket.links[0].from_node.get("pribambase_role") == "master"
            for node in output_nodes.values()
            for socket in (node.inputs['Surface'],)
        )
        state.apply_generated_normal = False
        assert normal_map.inputs['Strength'].default_value == 0.0
        state.apply_generated_normal = True
        assert normal_map.inputs['Strength'].default_value == 1.0

        flat = np.zeros((1, 3, 3), dtype=np.float32)
        flat[..., 2] = 1.0
        offset_x = np.asarray(((-1.0, 0.0, 1.0),), dtype=np.float32)
        offset_y = np.zeros((1, 3), dtype=np.float32)
        bulge = detail._radial_sculpt_vectors(
            flat,
            offset_x,
            offset_y,
            2.0,
            bulge=True,
        )
        dent = detail._radial_sculpt_vectors(
            flat,
            offset_x,
            offset_y,
            2.0,
            bulge=False,
        )
        assert bulge[0, 0, 0] < 0.0 < bulge[0, 2, 0]
        assert dent[0, 0, 0] > 0.0 > dent[0, 2, 0]
        assert tuple(bulge[0, 1]) == (0.0, 0.0, 1.0)
        assert np.allclose(np.linalg.norm(bulge, axis=2), 1.0)

        scene.frame_set(2)
        assert detail.source_image(scene) is None, "Normal Edit must be explicit per animation frame"
        scene.frame_set(1)
        try:
            detail.generate_normal(scene, scene.frame_end + 1, send=False)
        except RuntimeError as error:
            assert "outside the animation range" in str(error)
        else:
            raise AssertionError("An out-of-range World Normal request was accepted")

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
