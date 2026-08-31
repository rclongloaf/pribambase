"""Validate the generated round-trip sample inside Blender."""

from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path

import bpy


def script_arguments() -> list[str]:
    try:
        separator = sys.argv.index("--")
    except ValueError:
        return []
    return sys.argv[separator + 1 :]


def main() -> None:
    arguments = script_arguments()
    if len(arguments) != 3:
        raise RuntimeError("Expected project root, dependency path, and sample directory.")

    project_root = Path(arguments[0]).resolve()
    dependencies = str(Path(arguments[1]).resolve())
    sample_root = Path(arguments[2]).resolve()
    sys.path.insert(0, dependencies)
    sys.path.insert(0, str(project_root / "tools"))

    from addon_loader import ADDON_MODULE_NAME, load_addon_module

    package = load_addon_module(project_root)
    package.register()
    preferences_entry = bpy.context.preferences.addons.get(ADDON_MODULE_NAME)
    created_preferences = preferences_entry is None
    if preferences_entry is None:
        preferences_entry = bpy.context.preferences.addons.new()
        preferences_entry.module = ADDON_MODULE_NAME

    try:
        image = bpy.data.images.get("RoundtripTexture")
        cube = bpy.data.objects.get("AsepriteTexturedCube")
        assert image is not None and tuple(image.size) == (64, 64)
        assert cube is not None and cube.type == "MESH"
        assert len(cube.data.uv_layers) == 0, "Sample material must not depend on a UV map"

        util = importlib.import_module(f"{ADDON_MODULE_NAME}.util")
        expected_source = (sample_root / "roundtrip_texture.aseprite").resolve()
        assert Path(util.image_name(image)).resolve() == expected_source

        state = bpy.context.scene.sb_state
        assert state.asset_name == "Roundtrip Cube"
        assert Path(bpy.path.abspath(state.sprite_path)).resolve() == expected_source
        assert state.guide_layer == "Pribambase Render"
        assert state.follow_frame
        assert bpy.context.scene.render.fps == 12
        orme = state.material_image
        assert orme is not None and tuple(orme.size) == (64, 64)
        assert orme.name == "PB_Roundtrip_Cube_ORME"
        assert orme.colorspace_settings.name == "Non-Color"

        manifest_path = sample_root / "pribambase_roundtrip.pribambase.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["schema_version"] == 2
        assert manifest["asset"] == "Roundtrip Cube"
        assert manifest["sources"]["aseprite"] == "roundtrip_texture.aseprite"
        assert manifest["animation"]["fps"] == 12.0
        projection_manifest = manifest["projection"]
        assert projection_manifest["profile"] == "global_iso_v1"
        assert projection_manifest["pixels_per_unit"] == 20.0
        assert projection_manifest["collection"] == "PB_Projected"
        assert projection_manifest["material_image"] == "PB_Roundtrip_Cube_ORME"
        assert projection_manifest["emission_strength"] == 2.0
        assert projection_manifest["canvas"]["width"] == 64
        assert projection_manifest["canvas"]["height"] == 64
        assert projection_manifest["canvas"]["origin_x"] == 32
        assert projection_manifest["canvas"]["origin_y"] == 32

        image_nodes = [
            node
            for material in cube.data.materials
            if material and material.use_nodes
            for node in material.node_tree.nodes
            if node.type == "TEX_IMAGE"
        ]
        assert any(node.image == image and node.interpolation == "Closest" for node in image_nodes)
        assert any(node.image == orme and node.interpolation == "Closest" for node in image_nodes)

        projection = importlib.import_module(f"{ADDON_MODULE_NAME}.projection")
        projection.update_project_material(bpy.context.scene)
        canvas = projection.state_layout(bpy.context.scene)
        assert canvas is not None and (canvas.width, canvas.height) == (64, 64)
        assert (canvas.origin_x, canvas.origin_y) == (32, 32)
        material = state.projection_material
        assert material is not None and material.get("pribambase_project_material")
        assert material.get("pribambase_material_schema") == 3
        projection_nodes = [
            node
            for node in material.node_tree.nodes
            if node.get("pribambase_role") == "projection"
        ]
        assert len(projection_nodes) == 1
        assert projection_nodes[0].node_tree.get("pribambase_profile") == "global_iso_v1"

        camera = bpy.context.scene.camera
        assert camera is not None and camera.data.type == "ORTHO"
        assert math.isclose(
            camera.data.ortho_scale,
            64 / projection.PIXELS_PER_UNIT,
            rel_tol=1e-6,
        )

        render = importlib.import_module(f"{ADDON_MODULE_NAME}.render")
        camera.location.x += 7.0
        camera.scale = (1.7, 0.8, 2.1)
        moved_matrix = camera.matrix_world.copy()
        scene = bpy.context.scene
        scene.render.filter_size = 1.5
        eevee = getattr(scene, "eevee", None)
        original_eevee_samples = None
        if eevee is not None and hasattr(eevee, "taa_render_samples"):
            eevee.taa_render_samples = 64
            original_eevee_samples = 64
        with projection.projection_render_context(scene):
            assert math.isclose(
                scene.render.filter_size,
                projection.PIXEL_FILTER_SIZE,
                rel_tol=1e-6,
            )
            if original_eevee_samples is not None:
                assert eevee.taa_render_samples == original_eevee_samples
            result = render.get_render_image()
        try:
            assert tuple(result.size) == (64, 64)
            unoccluded_pixels = tuple(result.pixels[:])
            alpha = result.pixels[3::4]
            assert max(alpha) > 0.5, "Rendered object is fully transparent"
            partial_alpha = [value for value in alpha if 1e-5 < value < 1.0 - 1e-5]
            assert not partial_alpha, (
                f"Pixel-perfect guide contains {len(partial_alpha)} anti-aliased pixels"
            )
        finally:
            render.remove_render_image(result)

        # A black AO map must affect bright PBR lighting more than pixels that
        # are already dark. This guards against the old Base Color multiply,
        # which looked like a uniform layer of dirt over the whole texture.
        original_orme_pixels = tuple(orme.pixels[:])
        fully_occluded_pixels = list(original_orme_pixels)
        fully_occluded_pixels[0::4] = [0.0] * (len(fully_occluded_pixels) // 4)
        orme.pixels.foreach_set(fully_occluded_pixels)
        orme.update()
        occluded_result = None
        try:
            with projection.projection_render_context(scene):
                occluded_result = render.get_render_image()
            occluded_pixels = tuple(occluded_result.pixels[:])
        finally:
            if occluded_result is not None:
                render.remove_render_image(occluded_result)
            orme.pixels.foreach_set(original_orme_pixels)
            orme.update()

        def luminance(pixels, offset):
            return (
                pixels[offset] * 0.2126
                + pixels[offset + 1] * 0.7152
                + pixels[offset + 2] * 0.0722
            )

        ao_samples = []
        for offset in range(0, len(unoccluded_pixels), 4):
            if unoccluded_pixels[offset + 3] <= 0.5:
                continue
            baseline = luminance(unoccluded_pixels, offset)
            occluded = luminance(occluded_pixels, offset)
            delta = baseline - occluded
            if baseline > 0.02:
                ao_samples.append((baseline, delta, delta / baseline))
        assert len(ao_samples) >= 16
        ao_samples.sort(key=lambda sample: sample[0])
        quartile = max(1, len(ao_samples) // 4)
        dark_delta = sum(delta for _, delta, _ in ao_samples[:quartile]) / quartile
        light_delta = sum(delta for _, delta, _ in ao_samples[-quartile:]) / quartile
        dark_ratio = sum(ratio for _, _, ratio in ao_samples[:quartile]) / quartile
        light_ratio = sum(ratio for _, _, ratio in ao_samples[-quartile:]) / quartile
        assert max(delta for _, delta, _ in ao_samples) > 0.01, "AO has no visible effect"
        assert light_delta > dark_delta + 0.002, (
            "AO is not weighted toward lit pixels",
            dark_delta,
            light_delta,
        )
        assert light_ratio > dark_ratio + 0.02, (
            "AO behaves like a uniform Base Color multiply",
            dark_ratio,
            light_ratio,
        )
        assert camera.matrix_world == moved_matrix, "Guide rendering changed the user's camera"
        assert math.isclose(scene.render.filter_size, 1.5, rel_tol=1e-6)
        if original_eevee_samples is not None:
            assert eevee.taa_render_samples == original_eevee_samples
    finally:
        if created_preferences:
            bpy.context.preferences.addons.remove(preferences_entry)
        package.unregister()

    print("Pribambase round-trip sample passed Blender validation")


main()
