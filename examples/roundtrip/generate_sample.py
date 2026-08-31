"""Generate the Pribambase round-trip sample from a clean Blender startup."""

from __future__ import annotations

import importlib
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


def texture_color(x: int, y: int, size: int) -> tuple[float, float, float, float]:
    dark = (0.025, 0.04, 0.09, 1.0)
    navy = (0.055, 0.11, 0.22, 1.0)
    cyan = (0.05, 0.8, 0.78, 1.0)
    gold = (1.0, 0.55, 0.08, 1.0)
    pink = (0.95, 0.08, 0.42, 1.0)
    white = (0.9, 1.0, 1.0, 1.0)

    color = dark if ((x // 8) + (y // 8)) % 2 == 0 else navy
    if x < 2 or y < 2 or x >= size - 2 or y >= size - 2:
        color = gold
    if 14 <= x < 50 and 14 <= y < 50:
        color = cyan if ((x // 4) + (y // 4)) % 2 == 0 else (0.04, 0.58, 0.62, 1.0)
    if 20 <= y < 28 and (20 <= x < 28 or 36 <= x < 44):
        color = white
    if 22 <= y < 26 and (22 <= x < 26 or 38 <= x < 42):
        color = dark
    if 21 <= x < 43 and 36 <= y < 41:
        color = pink
    if (6 <= x < 11 and 6 <= y < 11) or (53 <= x < 58 and 53 <= y < 58):
        color = gold
    return color


def main() -> None:
    arguments = script_arguments()
    if len(arguments) != 3:
        raise RuntimeError("Expected project root, dependency path, and sample directory.")

    project_root = Path(arguments[0]).resolve()
    dependencies = str(Path(arguments[1]).resolve())
    sample_root = Path(arguments[2]).resolve()
    sample_root.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, dependencies)
    sys.path.insert(0, str(project_root / "tools"))

    from addon_loader import load_addon_module

    package = load_addon_module(project_root)
    package.register()

    for obj in tuple(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    scene = bpy.context.scene
    scene.name = "Scene"
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.render.fps = 12
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = 12
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    size = 64
    png_path = sample_root / "roundtrip_texture.png"
    projection_path = sample_root / "roundtrip_projection.png"
    aseprite_path = sample_root / "roundtrip_texture.aseprite"
    blend_path = sample_root / "pribambase_roundtrip.blend"

    image = bpy.data.images.new("RoundtripTexture", width=size, height=size, alpha=True)
    pixels = [channel for y in range(size) for x in range(size) for channel in texture_color(x, y, size)]
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(png_path)
    image.file_format = "PNG"
    image.save()
    image.pack()
    image.filepath = "//roundtrip_texture.png"
    image.sb_source = "//roundtrip_texture.aseprite"
    image.use_fake_user = True

    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    cube = bpy.context.object
    cube.name = "AsepriteTexturedCube"
    cube.dimensions = (2.25, 1.6, 2.0)
    cube.rotation_euler.z = math.radians(24.0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    while cube.data.uv_layers:
        cube.data.uv_layers.remove(cube.data.uv_layers[0])
    projected_collection = bpy.data.collections.new("PB_Projected")
    scene.collection.children.link(projected_collection)
    previous_collections = tuple(cube.users_collection)
    projected_collection.objects.link(cube)
    for collection in previous_collections:
        collection.objects.unlink(cube)
    bevel = cube.modifiers.new("PixelBevel", "BEVEL")
    bevel.width = 0.06
    bevel.segments = 1

    camera_data = bpy.data.cameras.new("RoundtripCamera")
    camera = bpy.data.objects.new("RoundtripCamera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera

    world = bpy.data.worlds.new("RoundtripWorld") if scene.world is None else scene.world
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.015, 0.02, 0.04, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35

    key_data = bpy.data.lights.new("KeyLight", "AREA")
    key_data.energy = 850
    key_data.shape = "DISK"
    key_data.size = 5.0
    key = bpy.data.objects.new("KeyLight", key_data)
    key.location = (-3.0, -4.0, 7.0)
    scene.collection.objects.link(key)

    fill_data = bpy.data.lights.new("FillLight", "AREA")
    fill_data.energy = 420
    fill_data.size = 4.0
    fill = bpy.data.objects.new("FillLight", fill_data)
    fill.location = (4.0, 1.0, 3.0)
    fill.rotation_euler = (math.radians(55.0), 0.0, math.radians(125.0))
    scene.collection.objects.link(fill)

    bpy.context.view_layer.objects.active = cube
    cube.select_set(True)

    state = scene.sb_state
    state.asset_name = "Roundtrip Cube"
    state.sprite_path = "//roundtrip_texture.aseprite"
    state.manifest_path = "//pribambase_roundtrip.pribambase.json"
    state.guide_layer = "Pribambase Render"
    state.auto_render_current = True
    state.auto_render_on_save = False
    state.follow_frame = True
    state.projection_collection = projected_collection
    state.projection_image = image

    from pribambase import projection, workspace

    projection.set_state_layout(scene, projection.centered_layout(size, size))
    material = projection.ensure_project_material(scene, image)
    projection.assign_project_material(scene, material)
    workspace.recalculate_projection_layout(scene)
    projection.apply_projection_camera(scene, camera)

    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = image
            elif area.type == "VIEW_3D":
                area.spaces.active.shading.type = "MATERIAL"

    instructions = bpy.data.texts.new("ROUNDTRIP_README.txt")
    instructions.write(
        "Pribambase round-trip sample\n"
        "1. Blender: N > Tool > Pribambase > Start Sync.\n"
        "2. Aseprite: File > Pribambase: Start Sync.\n"
        "3. Paint roundtrip_texture.aseprite to update the projected material.\n"
        "4. Geometry and light changes update the guide layer automatically.\n"
        "5. Restore Camera returns the viewport render to the canonical global projection.\n"
        "6. Use Update Guide or Render Dirty Frames for explicit projection updates.\n"
    )

    scene["pribambase_sample"] = "Aseprite texture to Blender object and render back to Aseprite"
    scene.render.filepath = str(projection_path)
    bpy.ops.render.render(write_still=True)
    scene.render.filepath = ""
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    workspace.write_manifest(scene)
    print(f"Generated Blender sample: {blend_path}")
    print(f"Generated projection preview: {projection_path}")
    print(f"Texture source expected at: {aseprite_path}")


main()
