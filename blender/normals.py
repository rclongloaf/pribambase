"""Polygon-normal references from Blender; artist normal textures arrive from Aseprite."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import bpy
import numpy as np

from . import projection, util
from .addon import addon
from .messaging import encode

SCHEMA = 1
REFERENCE_MODES = ("FLAT", "SMOOTH")
BAKE_MATERIAL_NAME = "PB_GeometryNormalBake_v3"
_generating = False
_dirty: set[tuple[int, int]] = set()


def is_generating() -> bool:
    return _generating


def _asset(scene):
    return "".join(c if c.isalnum() else "_" for c in scene.sb_state.asset_name).strip("_") or scene.name


def images(scene, role):
    return tuple(image for image in bpy.data.images
                 if image.get("pribambase_normal_role") == role
                 and image.get("pribambase_normal_asset") == _asset(scene))


def image_for(scene, role, frame=None):
    target = scene.frame_current if frame is None else frame
    return next((image for image in images(scene, role)
                 if image.get("pribambase_normal_frame") == target), None)


def default_image(scene, frame=None, mode="FLAT"):
    return image_for(scene, "geometry-" + mode.lower(), frame)


def painted_image(scene, frame=None):
    return image_for(scene, "painted", frame)


def material_image(scene):
    return painted_image(scene) or default_image(scene)


def _pack_image(image):
    try:
        image.pack()
    except RuntimeError:
        pass


def ensure_image(scene, role, frame, width, height):
    image = image_for(scene, role, frame)
    if image is not None and tuple(image.size) != (width, height):
        image.scale(width, height)
    if image is None:
        image = bpy.data.images.new(
            f"PB_{_asset(scene)}_{role.replace('-', '_').title()}_F{frame:04d}",
            width=width, height=height, alpha=True, is_data=True,
        )
        image["pribambase_normal_role"] = role
        image["pribambase_normal_asset"] = _asset(scene)
        image["pribambase_normal_frame"] = frame
        image.use_fake_user = True
    image.colorspace_settings.name = 'Non-Color'
    return image


def migrate_scene(scene):
    """Discard legacy Blender brush data once; never touch Aseprite-authored maps."""
    state = scene.sb_state
    if state.normal_schema >= SCHEMA:
        return False
    if "apply_generated_normal" in state:
        state.apply_world_normal = bool(state["apply_generated_normal"])
    for key in tuple(state.keys()):
        if key.startswith("detail_") or key == "apply_generated_normal":
            del state[key]
    for image in tuple(bpy.data.images):
        if (image.get("pribambase_detail_role") is not None
                and image.get("pribambase_detail_asset") == _asset(scene)):
            bpy.data.images.remove(image)
    state.normal_schema = SCHEMA
    mark_geometry_dirty(scene, all_frames=True)
    return True


def mark_geometry_dirty(scene, *, all_frames=False):
    frames = range(scene.frame_start, scene.frame_end + 1) if all_frames else (scene.frame_current,)
    _dirty.update((scene.as_pointer(), frame) for frame in frames)


def reset_runtime():
    _dirty.clear()


def resize_images(scene, old_layout, new_layout):
    for role in ("geometry-flat", "geometry-smooth", "painted"):
        for image in images(scene, role):
            projection.resize_image_canvas(image, old_layout, new_layout,
                                           fill_color=(0.5, 0.5, 1.0, 0.0))
            _pack_image(image)
    mark_geometry_dirty(scene, all_frames=True)


def _geometry_bake_material(smooth=False) -> bpy.types.Material:
    name = BAKE_MATERIAL_NAME + ("_Smooth" if smooth else "_Flat")
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    links = material.node_tree.links

    output = nodes.new('ShaderNodeOutputMaterial')
    emission = nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 1.0
    add = nodes.new('ShaderNodeVectorMath')
    add.operation = 'ADD'
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    scale = nodes.new('ShaderNodeVectorMath')
    scale.operation = 'SCALE'
    scale.inputs['Scale'].default_value = 0.5
    geometry = nodes.new('ShaderNodeNewGeometry')

    links.new(geometry.outputs['Normal' if smooth else 'True Normal'], scale.inputs[0])
    links.new(scale.outputs['Vector'], add.inputs[0])
    links.new(add.outputs['Vector'], emission.inputs['Color'])
    links.new(emission.outputs['Emission'], output.inputs['Surface'])
    material["pribambase_normal_bake"] = True
    return material


@contextmanager
def _normal_bake_context(scene: bpy.types.Scene, material: bpy.types.Material, *, smooth=False):
    global _generating
    view_layer = bpy.context.view_layer
    original_override = view_layer.material_override
    original_engine = scene.render.engine
    original_hide = {obj: obj.hide_render for obj in scene.objects}
    allowed = {obj.as_pointer() for obj in projection.projection_objects(scene)}
    eevee = getattr(scene, "eevee", None)
    original_samples = None
    original_smoothing = {}
    previous_generating = _generating
    _generating = True
    try:
        if smooth:
            for obj in projection.projection_objects(scene):
                mesh = obj.data
                if mesh in original_smoothing:
                    continue
                flags = np.empty(len(mesh.polygons), dtype=np.bool_)
                mesh.polygons.foreach_get("use_smooth", flags)
                original_smoothing[mesh] = flags
                mesh.polygons.foreach_set("use_smooth", np.ones(len(mesh.polygons), dtype=np.bool_))
                mesh.update()
        for obj in scene.objects:
            if hasattr(obj, "hide_render") and obj.type not in {'CAMERA', 'LIGHT'}:
                obj.hide_render = obj.as_pointer() not in allowed
        view_layer.material_override = material
        scene.render.engine = 'BLENDER_EEVEE'
        if eevee is not None and hasattr(eevee, "taa_render_samples"):
            original_samples = eevee.taa_render_samples
            eevee.taa_render_samples = 1
        yield
    finally:
        if original_samples is not None:
            eevee.taa_render_samples = original_samples
        scene.render.engine = original_engine
        view_layer.material_override = original_override
        for obj, hidden in original_hide.items():
            obj.hide_render = hidden
        try:
            for mesh, flags in original_smoothing.items():
                mesh.polygons.foreach_set("use_smooth", flags)
                mesh.update()
            bpy.context.view_layer.update()
        finally:
            _generating = previous_generating


def _render_float_pixels(scene: bpy.types.Scene) -> tuple[np.ndarray, tuple[int, int]]:
    directory = tempfile.mkdtemp(prefix="pribambase-normal-source-")
    path = Path(directory) / "world-normal.exr"
    original = (
        scene.render.filepath,
        scene.render.image_settings.file_format,
        scene.render.image_settings.color_mode,
        scene.render.image_settings.color_depth,
    )
    image = None
    try:
        scene.render.filepath = str(path)
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '32'
        bpy.ops.render.render(write_still=True)
        if not path.is_file():
            raise RuntimeError("Blender did not write the World Normal source bake")
        image = bpy.data.images.load(str(path), check_existing=False)
        image.colorspace_settings.name = 'Non-Color'
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        return pixels, (image.size[0], image.size[1])
    finally:
        if image is not None:
            bpy.data.images.remove(image)
        (
            scene.render.filepath,
            scene.render.image_settings.file_format,
            scene.render.image_settings.color_mode,
            scene.render.image_settings.color_depth,
        ) = original
        shutil.rmtree(directory, ignore_errors=True)


def _normalize_encoded_pixels(pixels: np.ndarray, width: int, height: int) -> np.ndarray:
    result = pixels.reshape(height, width, 4).copy()
    vectors = result[..., :3] * 2.0 - 1.0
    lengths = np.linalg.norm(vectors, axis=2, keepdims=True)
    covered = result[..., 3] > 1e-6
    vectors[covered] /= np.maximum(lengths[covered], 1e-8)
    vectors[~covered] = (0.0, 0.0, 1.0)
    result[..., :3] = vectors * 0.5 + 0.5
    result[..., 3] = covered.astype(np.float32)
    return result


def generate_default(scene, frame=None, *, send=False, force=False):
    """Bake both flat polygon and smooth references; no artist texture is changed."""
    target = scene.frame_current if frame is None else frame
    if not scene.frame_start <= target <= scene.frame_end:
        raise RuntimeError(f"Frame {target} is outside the animation range")
    migrate_scene(scene)
    layout = projection.state_layout(scene)
    if layout is None:
        raise RuntimeError("Calculate the animation canvas first")
    key = (scene.as_pointer(), target)
    needs_bake = force or key in _dirty or any(
        default_image(scene, target, mode) is None
        or tuple(default_image(scene, target, mode).size) != (layout.width, layout.height)
        for mode in REFERENCE_MODES
    )
    if needs_bake:
        original_frame = scene.frame_current
        for mode in REFERENCE_MODES:
            smooth = mode == "SMOOTH"
            with _normal_bake_context(scene, _geometry_bake_material(smooth), smooth=smooth):
                try:
                    if scene.frame_current != target:
                        scene.frame_set(target)
                    with projection.projection_render_context(scene):
                        scene.render.film_transparent = True
                        raw, actual = _render_float_pixels(scene)
                    if actual != (layout.width, layout.height):
                        raise RuntimeError(f"Geometry normal bake has unexpected size: {actual}")
                    pixels = _normalize_encoded_pixels(raw, *actual)
                    image = ensure_image(scene, "geometry-" + mode.lower(), target, *actual)
                    image.pixels.foreach_set(pixels.ravel())
                    image.update()
                    _pack_image(image)
                finally:
                    if scene.frame_current != original_frame:
                        scene.frame_set(original_frame)
        _dirty.discard(key)
        projection.update_project_material(scene)
    if send:
        send_default(scene, target)
    return default_image(scene, target)


def default_message(scene, frame=None, mode="FLAT"):
    from . import workspace
    target = scene.frame_current if frame is None else frame
    image = default_image(scene, target, mode)
    if image is None:
        return None
    return encode.generated_image(
        size=tuple(image.size), frame=target, kind="geometry-normal-" + mode.lower(),
        sprite=workspace.resolved_sprite_path(scene), pixels=util.get_mirrored_pixels(image),
    )


def send_default(scene, frame=None):
    if not addon.connected:
        return False
    sent = False
    for mode in REFERENCE_MODES:
        message = default_message(scene, frame, mode)
        if message is not None:
            addon.server.send(message)
            sent = True
    return sent


def receive_painted(scene, width, height, frame, data):
    """Receive 8-bit world RGB with Aseprite's top-left origin; no color transform."""
    if not scene.frame_start <= frame <= scene.frame_end:
        raise RuntimeError(f"Normal frame {frame} is outside the animation range")
    layout = projection.state_layout(scene)
    if layout is None or (width, height) != (layout.width, layout.height):
        raise RuntimeError("Normal texture does not match the shared projection canvas")
    raw = np.asarray(data, dtype=np.uint8)
    if raw.size != width * height * 4:
        raise RuntimeError("Invalid normal texture payload length")
    image = ensure_image(scene, "painted", frame, width, height)
    pixels = raw.reshape(height, width, 4)[::-1].astype(np.float32) / 255.0
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    _pack_image(image)
    projection.update_project_material(scene)
    return image


class SB_OT_normal_generate(bpy.types.Operator):
    bl_idname = "pribambase.normal_generate"
    bl_label = "Generate Geometry Normals"
    bl_description = "Bake flat and smooth world normals and send both references to Aseprite"

    @classmethod
    def poll(cls, context):
        return projection.state_layout(context.scene) is not None and not is_generating()

    def execute(self, context):
        try:
            generate_default(context.scene, force=True, send=True)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}
