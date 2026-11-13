"""Direct high-resolution world-normal painting and base-resolution output."""

from __future__ import annotations

import math
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import bpy
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector

from . import normal_picker, projection, util
from .addon import addon
from .messaging import encode


EDIT_SCALE = 2
SOURCE_ROLE = "world-normal-source"
NORMAL_ROLE = "world-normal"
GEOMETRY_ROLE = "geometry-world-normal"
BAKE_MATERIAL_NAME = "PB_GeometryNormalBake_v2"
BRUSH_MODES = ('PAINT', 'SET', 'SMOOTH', 'BULGE', 'DENT')
NORMAL_UNDO_LIMIT = 64

_dirty_frames: set[int] = set()
_geometry_dirty_frames: set[int] = set()
_generating = False


def is_generating() -> bool:
    return _generating


def _safe_asset_name(scene: bpy.types.Scene) -> str:
    value = "".join(
        char if char.isalnum() else "_"
        for char in scene.sb_state.asset_name
    ).strip("_")
    return value or scene.name


def _matches(image: bpy.types.Image, scene: bpy.types.Scene, role: str) -> bool:
    return (
        image.get("pribambase_detail_role") == role
        and image.get("pribambase_detail_asset") == _safe_asset_name(scene)
    )


def _frame(image: bpy.types.Image) -> int:
    return int(image.get("pribambase_detail_frame", 0))


def detail_images(scene: bpy.types.Scene, role: str) -> tuple[bpy.types.Image, ...]:
    return tuple(image for image in bpy.data.images if _matches(image, scene, role))


def source_image(scene: bpy.types.Scene, frame: int | None = None):
    target = scene.frame_current if frame is None else frame
    return next(
        (image for image in detail_images(scene, SOURCE_ROLE) if _frame(image) == target),
        None,
    )


def normal_image(scene: bpy.types.Scene, frame: int | None = None):
    target = scene.frame_current if frame is None else frame
    return next(
        (
            image
            for image in detail_images(scene, NORMAL_ROLE)
            if _frame(image) == target and image.get("pribambase_detail_valid")
        ),
        None,
    )


def geometry_normal_image(scene: bpy.types.Scene, frame: int | None = None):
    """Return the immutable base-resolution normal map baked from geometry."""
    target = scene.frame_current if frame is None else frame
    return next(
        (image for image in detail_images(scene, GEOMETRY_ROLE) if _frame(image) == target),
        None,
    )


def _tag_image(
    image: bpy.types.Image,
    scene: bpy.types.Scene,
    role: str,
    frame: int,
    *,
    edit_scale: int = EDIT_SCALE,
) -> None:
    image["pribambase_detail_role"] = role
    image["pribambase_detail_asset"] = _safe_asset_name(scene)
    image["pribambase_detail_frame"] = frame
    image["pribambase_edit_scale"] = edit_scale
    image.use_fake_user = True


def _pack_image(image: bpy.types.Image) -> None:
    try:
        image.pack()
    except RuntimeError:
        pass


def _new_source_image(scene: bpy.types.Scene, frame: int, width: int, height: int):
    existing = source_image(scene, frame)
    if existing is not None and tuple(existing.size) == (width, height):
        return existing
    if existing is not None:
        bpy.data.images.remove(existing)
    image = bpy.data.images.new(
        f"PB_{_safe_asset_name(scene)}_NormalEdit_F{frame:04d}",
        width=width,
        height=height,
        alpha=True,
        float_buffer=True,
        is_data=True,
    )
    image.colorspace_settings.name = 'Non-Color'
    _tag_image(image, scene, SOURCE_ROLE, frame)
    return image


def _new_geometry_normal_image(
    scene: bpy.types.Scene,
    frame: int,
    width: int,
    height: int,
) -> bpy.types.Image:
    existing = geometry_normal_image(scene, frame)
    if existing is not None and tuple(existing.size) == (width, height):
        return existing
    if existing is not None:
        bpy.data.images.remove(existing)
    image = bpy.data.images.new(
        f"PB_{_safe_asset_name(scene)}_GeometryNormal_F{frame:04d}",
        width=width,
        height=height,
        alpha=True,
        is_data=True,
    )
    image.colorspace_settings.name = 'Non-Color'
    _tag_image(image, scene, GEOMETRY_ROLE, frame, edit_scale=1)
    return image


def ensure_normal_image(scene: bpy.types.Scene, frame: int | None = None) -> bpy.types.Image:
    target = scene.frame_current if frame is None else frame
    layout = projection.state_layout(scene)
    if layout is None:
        raise RuntimeError("Calculate the animation canvas before generating World Normal")
    existing = next(
        (image for image in detail_images(scene, NORMAL_ROLE) if _frame(image) == target),
        None,
    )
    if existing is not None and tuple(existing.size) == (layout.width, layout.height):
        return existing
    if existing is not None:
        bpy.data.images.remove(existing)
    image = bpy.data.images.new(
        f"PB_{_safe_asset_name(scene)}_WorldNormal_F{target:04d}",
        width=layout.width,
        height=layout.height,
        alpha=True,
        is_data=True,
    )
    image.colorspace_settings.name = 'Non-Color'
    _tag_image(image, scene, NORMAL_ROLE, target)
    image["pribambase_detail_valid"] = False
    return image


def mark_dirty(scene: bpy.types.Scene, frame: int | None = None) -> None:
    target = scene.frame_current if frame is None else frame
    if source_image(scene, target) is not None:
        _dirty_frames.add(target)


def mark_all_dirty(scene: bpy.types.Scene) -> None:
    _dirty_frames.update(_frame(image) for image in detail_images(scene, SOURCE_ROLE))


def mark_geometry_dirty(scene: bpy.types.Scene, frame: int | None = None) -> None:
    target = scene.frame_current if frame is None else frame
    if source_image(scene, target) is not None:
        _geometry_dirty_frames.add(target)


def dirty_frames() -> tuple[int, ...]:
    return tuple(sorted(_dirty_frames))


def geometry_dirty_frames() -> tuple[int, ...]:
    return tuple(sorted(_geometry_dirty_frames))


def reset_runtime() -> None:
    _dirty_frames.clear()
    _geometry_dirty_frames.clear()


def resize_detail_images(
    scene: bpy.types.Scene,
    old_layout: projection.Layout,
    new_layout: projection.Layout,
) -> None:
    old_source_layout = projection.Layout(
        old_layout.min_x * EDIT_SCALE,
        old_layout.min_y * EDIT_SCALE,
        old_layout.max_x * EDIT_SCALE,
        old_layout.max_y * EDIT_SCALE,
    )
    new_source_layout = projection.Layout(
        new_layout.min_x * EDIT_SCALE,
        new_layout.min_y * EDIT_SCALE,
        new_layout.max_x * EDIT_SCALE,
        new_layout.max_y * EDIT_SCALE,
    )
    for image in detail_images(scene, SOURCE_ROLE):
        projection.resize_image_canvas(
            image,
            old_source_layout,
            new_source_layout,
            fill_color=(0.5, 0.5, 1.0, 0.0),
        )
        _dirty_frames.add(_frame(image))
        _geometry_dirty_frames.add(_frame(image))
    for image in detail_images(scene, GEOMETRY_ROLE):
        projection.resize_image_canvas(
            image,
            old_layout,
            new_layout,
            fill_color=(0.5, 0.5, 1.0, 0.0),
        )
        _pack_image(image)
    for image in tuple(detail_images(scene, NORMAL_ROLE)):
        _dirty_frames.add(_frame(image))
        bpy.data.images.remove(image)


def _geometry_bake_material() -> bpy.types.Material:
    material = bpy.data.materials.get(BAKE_MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(BAKE_MATERIAL_NAME)
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

    links.new(geometry.outputs['Normal'], scale.inputs[0])
    links.new(scale.outputs['Vector'], add.inputs[0])
    links.new(add.outputs['Vector'], emission.inputs['Color'])
    links.new(emission.outputs['Emission'], output.inputs['Surface'])
    material["pribambase_detail_bake"] = True
    return material


@contextmanager
def _normal_bake_context(scene: bpy.types.Scene, material: bpy.types.Material):
    global _generating
    view_layer = bpy.context.view_layer
    original_override = view_layer.material_override
    original_engine = scene.render.engine
    original_hide = {obj: obj.hide_render for obj in scene.objects}
    allowed = {obj.as_pointer() for obj in projection.projection_objects(scene)}
    eevee = getattr(scene, "eevee", None)
    original_samples = None
    _generating = True
    try:
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
        _generating = False
        bpy.context.view_layer.update()


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


def initialize_source(
    scene: bpy.types.Scene,
    frame: int | None = None,
) -> bpy.types.Image:
    target = scene.frame_current if frame is None else frame
    if target < scene.frame_start or target > scene.frame_end:
        raise RuntimeError(
            f"Frame {target} is outside the animation range {scene.frame_start}–{scene.frame_end}"
        )
    layout = projection.state_layout(scene)
    if layout is None:
        raise RuntimeError("Calculate the animation canvas first")
    original_frame = scene.frame_current
    try:
        if original_frame != target:
            scene.frame_set(target)
        material = _geometry_bake_material()
        with _normal_bake_context(scene, material):
            with projection.projection_render_context(scene):
                scene.render.resolution_x = layout.width * EDIT_SCALE
                scene.render.resolution_y = layout.height * EDIT_SCALE
                scene.render.resolution_percentage = 100
                scene.render.film_transparent = True
                raw, actual = _render_float_pixels(scene)
        expected = (layout.width * EDIT_SCALE, layout.height * EDIT_SCALE)
        if actual != expected:
            raise RuntimeError(f"Normal source bake has size {actual}, expected {expected}")
        pixels = _normalize_encoded_pixels(raw, *expected)
        image = _new_source_image(scene, target, *expected)
        image.pixels.foreach_set(pixels.ravel())
        image.update()
        image["pribambase_source_from_geometry"] = True
        _pack_image(image)
        geometry = _new_geometry_normal_image(
            scene,
            target,
            layout.width,
            layout.height,
        )
        geometry_pixels = _downsample_world_normals(
            pixels.ravel(),
            layout.width,
            layout.height,
        )
        geometry.pixels.foreach_set(geometry_pixels.ravel())
        geometry.update()
        geometry["pribambase_reference_from_geometry"] = True
        _pack_image(geometry)
        _dirty_frames.add(target)
        _geometry_dirty_frames.discard(target)
        projection.update_project_material(scene)
        return image
    finally:
        if scene.frame_current != original_frame:
            scene.frame_set(original_frame)


def remove_source_frame(scene: bpy.types.Scene) -> bool:
    frame = scene.frame_current
    source = source_image(scene, frame)
    if source is None:
        return False
    bpy.data.images.remove(source)
    output = next(
        (image for image in detail_images(scene, NORMAL_ROLE) if _frame(image) == frame),
        None,
    )
    if output is not None:
        bpy.data.images.remove(output)
    geometry = geometry_normal_image(scene, frame)
    if geometry is not None:
        bpy.data.images.remove(geometry)
    _dirty_frames.discard(frame)
    _geometry_dirty_frames.discard(frame)
    projection.update_project_material(scene)
    return True


def _downsample_world_normals(
    pixels: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    samples = pixels.reshape(height * EDIT_SCALE, width * EDIT_SCALE, 4).reshape(
        height,
        EDIT_SCALE,
        width,
        EDIT_SCALE,
        4,
    )
    alpha = samples[..., 3]
    vectors = samples[..., :3] * 2.0 - 1.0
    weights = alpha[..., np.newaxis]
    summed = (vectors * weights).sum(axis=(1, 3))
    weight_sum = weights.sum(axis=(1, 3))
    covered = weight_sum[..., 0] > 1e-6
    averaged = np.zeros((height, width, 3), dtype=np.float32)
    averaged[covered] = summed[covered] / weight_sum[covered]
    averaged[~covered] = (0.0, 0.0, 1.0)
    lengths = np.linalg.norm(averaged, axis=2, keepdims=True)
    averaged /= np.maximum(lengths, 1e-8)
    result = np.empty((height, width, 4), dtype=np.float32)
    result[..., :3] = averaged * 0.5 + 0.5
    result[..., 3] = covered.astype(np.float32)
    return result


def send_normal(scene: bpy.types.Scene, frame: int | None = None) -> bool:
    target = scene.frame_current if frame is None else frame
    image = normal_image(scene, target)
    if image is None or not addon.connected:
        return False
    from . import workspace

    addon.server.send(
        encode.generated_image(
            size=(image.size[0], image.size[1]),
            frame=target,
            kind="world-normal",
            sprite=workspace.resolved_sprite_path(scene),
            pixels=util.get_mirrored_pixels(image),
        )
    )
    return True


def generate_normal(
    scene: bpy.types.Scene,
    frame: int | None = None,
    *,
    send: bool | None = None,
) -> bpy.types.Image:
    target = scene.frame_current if frame is None else frame
    if target < scene.frame_start or target > scene.frame_end:
        raise RuntimeError(
            f"Frame {target} is outside the animation range {scene.frame_start}–{scene.frame_end}"
        )
    source = source_image(scene, target)
    if source is None:
        raise RuntimeError("Initialize Normal Edit from geometry for this frame first")
    layout = projection.state_layout(scene)
    if layout is None:
        raise RuntimeError("Calculate the animation canvas first")
    expected = (layout.width * EDIT_SCALE, layout.height * EDIT_SCALE)
    if tuple(source.size) != expected:
        raise RuntimeError(f"Normal Edit has size {tuple(source.size)}, expected {expected}")
    raw = np.asarray(source.pixels[:], dtype=np.float32)
    converted = _downsample_world_normals(raw, layout.width, layout.height)
    output = ensure_normal_image(scene, target)
    output.pixels.foreach_set(converted.ravel())
    output.update()
    output["pribambase_detail_valid"] = True
    output["pribambase_normal_source_frame"] = target
    _pack_image(output)
    _dirty_frames.discard(target)
    projection.update_project_material(scene)
    should_send = scene.sb_state.detail_auto_send if send is None else send
    if should_send:
        send_normal(scene, target)
    return output


def generate_dirty(scene: bpy.types.Scene) -> int:
    frames = tuple(sorted(_dirty_frames))
    for frame in frames:
        generate_normal(scene, frame)
    return len(frames)


def _camera_view_ray(scene, region, rv3d, coord):
    """Build a ray through the visible camera border without viewport unprojection.

    Blender's generic region_2d_to_* helpers can keep using the previous free-view
    matrices for the first modal events after entering Camera View from a sidebar
    operator.  The camera frame itself is projected correctly, so use that frame
    only to locate the cursor and construct the actual ray from camera data.
    """
    camera = scene.camera
    if rv3d.view_perspective != 'CAMERA' or camera is None or camera.type != 'CAMERA':
        return None

    local_frame = tuple(camera.data.view_frame(scene=scene))
    screen_frame = tuple(
        view3d_utils.location_3d_to_region_2d(
            region,
            rv3d,
            camera.matrix_world @ corner,
        )
        for corner in local_frame
    )
    if any(point is None for point in screen_frame):
        return None

    left = min(point.x for point in screen_frame)
    right = max(point.x for point in screen_frame)
    bottom = min(point.y for point in screen_frame)
    top = max(point.y for point in screen_frame)
    if right - left <= 1e-6 or top - bottom <= 1e-6:
        return None
    if coord[0] < left or coord[0] > right or coord[1] < bottom or coord[1] > top:
        return None

    u = (coord[0] - left) / (right - left)
    v = (coord[1] - bottom) / (top - bottom)
    frame_left = min(corner.x for corner in local_frame)
    frame_right = max(corner.x for corner in local_frame)
    frame_bottom = min(corner.y for corner in local_frame)
    frame_top = max(corner.y for corner in local_frame)
    local_x = frame_left + (frame_right - frame_left) * u
    local_y = frame_bottom + (frame_top - frame_bottom) * v

    if camera.data.type == 'ORTHO':
        origin = camera.matrix_world @ Vector((local_x, local_y, 0.0))
        direction = (camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))).normalized()
    else:
        frame_z = sum(corner.z for corner in local_frame) / len(local_frame)
        origin = camera.matrix_world.translation.copy()
        frame_point = camera.matrix_world @ Vector((local_x, local_y, frame_z))
        direction = (frame_point - origin).normalized()
    return origin, direction


def _projected_hit(context, event):
    region = next(
        (candidate for candidate in context.area.regions if candidate.type == 'WINDOW'),
        None,
    )
    rv3d = getattr(context.space_data, "region_3d", None)
    if region is None or rv3d is None:
        return None
    coord = (event.mouse_x - region.x, event.mouse_y - region.y)
    if coord[0] < 0 or coord[1] < 0 or coord[0] >= region.width or coord[1] >= region.height:
        return None
    ray = _camera_view_ray(context.scene, region, rv3d, coord)
    if ray is None:
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    else:
        origin, direction = ray
    depsgraph = context.evaluated_depsgraph_get()
    hit, location, _normal, _index, obj, _matrix = context.scene.ray_cast(
        depsgraph,
        origin,
        direction,
    )
    if not hit or obj is None:
        return None
    allowed = {item.name for item in projection.projection_objects(context.scene)}
    original = getattr(obj, "original", obj)
    if original.name not in allowed and obj.name not in allowed:
        return None
    return location


def _image_pixel_at_location(
    scene: bpy.types.Scene,
    image: bpy.types.Image,
    location,
    scale: int,
):
    layout = projection.state_layout(scene)
    if layout is None:
        return None
    projected_x, projected_y = projection.project_world_point(location)
    pixel_x = math.floor((projected_x - layout.min_x) * scale)
    pixel_y = math.floor((projected_y - layout.min_y) * scale)
    if pixel_x < 0 or pixel_y < 0 or pixel_x >= image.size[0] or pixel_y >= image.size[1]:
        return None
    return pixel_x, pixel_y


def _source_pixel_at_location(scene: bpy.types.Scene, image: bpy.types.Image, location):
    return _image_pixel_at_location(scene, image, location, EDIT_SCALE)


def _pixel_scope_bounds(scene: bpy.types.Scene, image: bpy.types.Image, x: int, y: int):
    if scene.sb_state.detail_pixel_scope == 'OUTPUT':
        min_x = (x // EDIT_SCALE) * EDIT_SCALE
        min_y = (y // EDIT_SCALE) * EDIT_SCALE
        return (
            min_x,
            min(min_x + EDIT_SCALE, image.size[0]),
            min_y,
            min(min_y + EDIT_SCALE, image.size[1]),
        )
    return x, x + 1, y, y + 1


def _set_brush_bounds(
    scene: bpy.types.Scene,
    image: bpy.types.Image,
    x: int,
    y: int,
    size: int,
) -> tuple[int, int, int, int]:
    unit = EDIT_SCALE if scene.sb_state.detail_pixel_scope == 'OUTPUT' else 1
    center_x = x // unit
    center_y = y // unit
    units_wide = image.size[0] // unit
    units_high = image.size[1] // unit
    start_x = center_x - (size - 1) // 2
    start_y = center_y - (size - 1) // 2
    end_x = start_x + size
    end_y = start_y + size
    return (
        max(0, start_x) * unit,
        min(units_wide, end_x) * unit,
        max(0, start_y) * unit,
        min(units_high, end_y) * unit,
    )


def _normalized(vector) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32)
    length = float(np.linalg.norm(value))
    if length < 1e-8:
        return np.array((0.0, 0.0, 1.0), dtype=np.float32)
    return value / length


def brush_radius_property(mode: str) -> str | None:
    return {
        'PAINT': "detail_brush_radius",
        'SET': "detail_set_size",
        'SMOOTH': "detail_smooth_radius",
        'BULGE': "detail_bulge_radius",
        'DENT': "detail_dent_radius",
    }.get(mode)


def _step_set_size(state, change: int) -> bool:
    """Cross the 2× output-pixel / 1× edit-sample boundary at minimum size."""
    if change < 0 and state.detail_set_size == 1 and state.detail_pixel_scope == 'OUTPUT':
        state.detail_pixel_scope = 'EDIT'
        return True
    if change > 0 and state.detail_set_size == 1 and state.detail_pixel_scope == 'EDIT':
        state.detail_pixel_scope = 'OUTPUT'
        return True
    return False


def _sample_image(scene: bpy.types.Scene) -> tuple[bpy.types.Image | None, int]:
    if scene.sb_state.detail_preview_mode == 'GEOMETRY_NORMAL':
        return geometry_normal_image(scene), 1
    if scene.sb_state.detail_preview_mode == 'FINAL_NORMAL':
        return normal_image(scene), 1
    return source_image(scene), EDIT_SCALE


def _sample_normal(context, event):
    location = _projected_hit(context, event)
    if location is None:
        return None
    return _normal_at_location(context.scene, location)


def _normal_at_location(scene: bpy.types.Scene, location):
    image, scale = _sample_image(scene)
    if image is None:
        return None
    pixel = _image_pixel_at_location(scene, image, location, scale)
    if pixel is None:
        return None
    if scale == EDIT_SCALE:
        x0, x1, y0, y1 = _pixel_scope_bounds(scene, image, *pixel)
    else:
        x0, x1, y0, y1 = pixel[0], pixel[0] + 1, pixel[1], pixel[1] + 1
    vectors = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            offset = (y * image.size[0] + x) * 4
            if image.pixels[offset + 3] > 1e-6:
                vectors.append(tuple(image.pixels[offset + axis] * 2.0 - 1.0 for axis in range(3)))
    if not vectors:
        return None
    return _normalized(np.asarray(vectors, dtype=np.float32).mean(axis=0))


def _radial_sculpt_vectors(
    vectors: np.ndarray,
    offset_x: np.ndarray,
    offset_y: np.ndarray,
    radius: float,
    *,
    bulge: bool,
) -> np.ndarray:
    """Return a smooth projected bulge/dent field in world-space coordinates."""
    distance = np.sqrt(offset_x**2 + offset_y**2)
    safe_distance = np.maximum(distance, 1e-8)
    radial = np.zeros_like(vectors)
    radial[..., 0] = offset_x / safe_distance
    radial[..., 1] = (offset_y / safe_distance) * math.sin(projection.PROJECTION_ELEVATION)
    radial[..., 2] = (offset_y / safe_distance) * math.cos(projection.PROJECTION_ELEVATION)
    tangent = radial - vectors * np.sum(radial * vectors, axis=2, keepdims=True)
    tangent_length = np.linalg.norm(tangent, axis=2, keepdims=True)
    tangent /= np.maximum(tangent_length, 1e-8)
    slope = np.sin(np.pi * np.clip(distance / max(radius, 1e-8), 0.0, 1.0))
    direction = 1.0 if bulge else -1.0
    desired = vectors + direction * tangent * (slope * 2.0)[..., np.newaxis]
    desired_length = np.linalg.norm(desired, axis=2, keepdims=True)
    return desired / np.maximum(desired_length, 1e-8)


class SB_OT_detail_initialize(bpy.types.Operator):
    bl_idname = "pribambase.detail_initialize"
    bl_label = "Initialize Normal Edit from Geometry"
    bl_description = "Bake visible geometric world normals into a new editable 2× source for this frame"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return projection.state_layout(context.scene) is not None and not is_generating()

    def execute(self, context):
        try:
            image = initialize_source(context.scene)
            if context.scene.sb_state.detail_auto_rebuild:
                generate_normal(context.scene)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Initialized {image.name}")
        return {'FINISHED'}


class SB_OT_detail_remove_source(bpy.types.Operator):
    bl_idname = "pribambase.detail_remove_source"
    bl_label = "Remove Normal Edit Frame"
    bl_description = "Delete the editable and generated normal maps for the current frame"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return source_image(context.scene) is not None

    def execute(self, context):
        remove_source_frame(context.scene)
        return {'FINISHED'}


class SB_OT_detail_rebuild(bpy.types.Operator):
    bl_idname = "pribambase.detail_rebuild"
    bl_label = "Rebuild World Normal"
    bl_description = "Average each editable 2×2 block, normalize it, and send the base-resolution map"

    @classmethod
    def poll(cls, context):
        return source_image(context.scene) is not None and not is_generating()

    def execute(self, context):
        try:
            image = generate_normal(context.scene, send=True)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Generated {image.name}")
        return {'FINISHED'}


class SB_OT_detail_rebuild_dirty(bpy.types.Operator):
    bl_idname = "pribambase.detail_rebuild_dirty"
    bl_label = "Rebuild Dirty World Normals"
    bl_description = "Regenerate every edited frame whose base-resolution output is out of date"

    @classmethod
    def poll(cls, context):
        return bool(_dirty_frames) and not is_generating()

    def execute(self, context):
        try:
            count = generate_dirty(context.scene)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Generated {count} World Normal frame(s)")
        return {'FINISHED'}


class SB_OT_detail_pick_normal(bpy.types.Operator):
    bl_idname = "pribambase.detail_pick_normal"
    bl_label = "Pick World Normal"
    bl_description = "Sample a direction from the currently previewed Edited, Final, or Geometry map"
    bl_options = {'REGISTER', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == 'VIEW_3D'
            and (
                source_image(context.scene) is not None
                or geometry_normal_image(context.scene) is not None
            )
        )

    def invoke(self, context, event):
        context.window.cursor_modal_set('EYEDROPPER')
        context.area.header_text_set("Pribambase Normal Eyedropper · LMB pick · Esc cancel")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        context.window.cursor_modal_restore()
        context.area.header_text_set(None)

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self._finish(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            value = _sample_normal(context, event)
            if value is None:
                self.report({'WARNING'}, "Point at an initialized projected normal pixel")
                return {'RUNNING_MODAL'}
            context.scene.sb_state.detail_normal_target = tuple(float(item) for item in value)
            self._finish(context)
            self.report({'INFO'}, f"Picked World Normal {tuple(round(float(v), 3) for v in value)}")
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class SB_OT_detail_free_pick_normal(bpy.types.Operator):
    bl_idname = "pribambase.detail_free_pick_normal"
    bl_label = "Free World Normal Picker"
    bl_description = "Pick a continuous or angularly quantized direction from a viewport Normal Ball"
    bl_options = {'REGISTER', 'BLOCKING'}

    _picker = None

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        try:
            self._picker = normal_picker.NormalPickerSession(context, event)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _update_world(self, context, event) -> None:
        location = _projected_hit(context, event)
        current = (
            _normal_at_location(context.scene, location)
            if location is not None
            else None
        )
        self._picker.update_world(location, current)

    def modal(self, context, event):
        outcome = self._picker.handle_event(context, event)
        if self._picker.active:
            self._update_world(context, event)
        if outcome == 'CONFIRM':
            self.report({'INFO'}, "World Normal direction selected")
            return {'FINISHED'}
        if outcome == 'CANCEL':
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if self._picker is not None:
            self._picker.stop()


class SB_OT_detail_paint(bpy.types.Operator):
    bl_idname = "pribambase.detail_paint"
    bl_label = "Paint World Normals"
    bl_description = "Paint the editable 2× world-normal source directly on the projected model"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    _painting = False
    _changed = False
    _image = None
    _pixels = None
    _stroke_changed = False
    _stroke_before = None
    _undo_stack = None
    _redo_stack = None
    _navigating = False
    _navigation_mouse = (0, 0)
    _normal_picker = None

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == 'VIEW_3D'
            and source_image(context.scene) is not None
        )

    def _set_header(self, context, text: str | None = None):
        mode = context.scene.sb_state.detail_brush_mode
        radius_name = brush_radius_property(mode)
        radius = getattr(context.scene.sb_state, radius_name) if radius_name else None
        radius_text = (
            f" · {radius}px · Ctrl+Wheel {'size' if mode == 'SET' else 'radius'}"
            if radius is not None
            else ""
        )
        strength_text = (
            f" · {context.scene.sb_state.detail_brush_strength:.2f} strength"
            if mode != 'SET'
            else ""
        )
        context.area.header_text_set(
            text
            or (
                f"Pribambase {mode.title()}{radius_text}{strength_text} · LMB paint · Alt pick · "
                "Q/E or 1–5 tool · Shift+1–4 preview · Ctrl+Z/Y stroke · Enter/Esc save"
            )
        )

    def _active_mode(self, context, event) -> str:
        return 'SMOOTH' if event.shift else context.scene.sb_state.detail_brush_mode

    def _adjust_radius(self, context, event, change: int) -> bool:
        mode = self._active_mode(context, event)
        property_name = brush_radius_property(mode)
        if property_name is None:
            return False
        state = context.scene.sb_state
        if mode == 'SET' and _step_set_size(state, change):
            description = (
                "1×1 edit sample"
                if state.detail_pixel_scope == 'EDIT'
                else "1 output pixel · 2×2 edit samples"
            )
            self._set_header(context, f"Set size: {description} · Ctrl+Wheel to adjust")
            context.area.tag_redraw()
            return True
        value = max(1, min(256, getattr(state, property_name) + change))
        setattr(state, property_name, value)
        parameter = "size" if mode == 'SET' else "radius"
        self._set_header(context, f"{mode.title()} {parameter}: {value}px · Ctrl+Wheel to adjust")
        context.area.tag_redraw()
        return True

    def _adjust_strength(self, context, event, change: int) -> bool:
        mode = self._active_mode(context, event)
        if mode == 'SET':
            return False
        state = context.scene.sb_state
        state.detail_brush_strength = round(
            max(0.0001, min(1.0, state.detail_brush_strength + change * 0.05)),
            4,
        )
        self._set_header(
            context,
            f"{mode.title()} strength: {state.detail_brush_strength:.2f} · Alt+Wheel to adjust",
        )
        context.area.tag_redraw()
        return True

    def _switch_tool(self, context, mode: str) -> None:
        context.scene.sb_state.detail_brush_mode = mode
        self._set_header(context)
        context.area.tag_redraw()

    def _pan_view(self, context, event) -> None:
        region = next(
            (candidate for candidate in context.area.regions if candidate.type == 'WINDOW'),
            None,
        )
        rv3d = getattr(context.space_data, "region_3d", None)
        if region is None or rv3d is None:
            return
        last_x, last_y = self._navigation_mouse
        delta_x = event.mouse_x - last_x
        delta_y = event.mouse_y - last_y
        self._navigation_mouse = (event.mouse_x, event.mouse_y)
        if delta_x == 0 and delta_y == 0:
            return
        if rv3d.view_perspective == 'CAMERA':
            zoom = ((math.sqrt(2.0) + rv3d.view_camera_zoom / 50.0) ** 2) / 4.0
            offset = rv3d.view_camera_offset.copy()
            offset.x += delta_x * 2.0 / max(region.width * zoom, 1e-8)
            offset.y += delta_y * 2.0 / max(region.height * zoom, 1e-8)
            rv3d.view_camera_offset = offset
        else:
            rotation = rv3d.view_rotation
            right = rotation @ Vector((1.0, 0.0, 0.0))
            up = rotation @ Vector((0.0, 1.0, 0.0))
            world_per_pixel = max(rv3d.view_distance, 0.01) * 2.0 / max(
                min(region.width, region.height),
                1,
            )
            rv3d.view_location -= (
                right * delta_x * world_per_pixel
                + up * delta_y * world_per_pixel
            )
        context.area.tag_redraw()

    def _zoom_view(self, context, *, zoom_in: bool) -> None:
        rv3d = getattr(context.space_data, "region_3d", None)
        if rv3d is None:
            return
        if rv3d.view_perspective == 'CAMERA':
            metadata = rv3d.bl_rna.properties["view_camera_zoom"]
            change = 10.0 if zoom_in else -10.0
            rv3d.view_camera_zoom = max(
                metadata.hard_min,
                min(metadata.hard_max, rv3d.view_camera_zoom + change),
            )
        else:
            rv3d.view_distance = max(
                0.001,
                rv3d.view_distance * (0.9 if zoom_in else 1.0 / 0.9),
            )
        context.area.tag_redraw()

    def _apply_history_pixels(self, context, pixels: np.ndarray) -> None:
        self._pixels = pixels.copy()
        self._image.pixels.foreach_set(self._pixels.ravel())
        self._image.update()
        self._changed = True
        context.area.tag_redraw()
        if context.scene.sb_state.detail_auto_rebuild:
            self._rebuild_preview(context)

    def _rebuild_preview(self, context) -> None:
        mark_dirty(context.scene)
        try:
            generate_normal(context.scene, send=False)
        except Exception as error:
            self.report({'ERROR'}, f"Preview rebuild failed: {error}")

    def _undo_stroke(self, context) -> None:
        if not self._undo_stack:
            self._set_header(context, "Nothing to undo · Ctrl+Y redo · Enter/Esc save")
            return
        self._redo_stack.append(self._pixels.copy())
        self._apply_history_pixels(context, self._undo_stack.pop())
        self._set_header(
            context,
            f"Stroke undone · {len(self._undo_stack)} undo · {len(self._redo_stack)} redo",
        )

    def _redo_stroke(self, context) -> None:
        if not self._redo_stack:
            self._set_header(context, "Nothing to redo · Ctrl+Z undo · Enter/Esc save")
            return
        self._undo_stack.append(self._pixels.copy())
        self._apply_history_pixels(context, self._redo_stack.pop())
        self._set_header(
            context,
            f"Stroke restored · {len(self._undo_stack)} undo · {len(self._redo_stack)} redo",
        )

    def _start_normal_picker(self, context, event) -> None:
        self._normal_picker = normal_picker.NormalPickerSession(context, event)
        location = _projected_hit(context, event)
        current = (
            _normal_at_location(context.scene, location)
            if location is not None
            else None
        )
        self._normal_picker.update_world(location, current)

    def _handle_normal_picker(self, context, event) -> None:
        outcome = self._normal_picker.handle_event(context, event)
        if self._normal_picker.active:
            location = _projected_hit(context, event)
            current = (
                _normal_at_location(context.scene, location)
                if location is not None
                else None
            )
            self._normal_picker.update_world(location, current)
        if outcome in {'CONFIRM', 'CANCEL'}:
            self._normal_picker = None
            self._set_header(context)

    def _dab(self, context, event) -> None:
        if event.alt:
            value = _sample_normal(context, event)
            if value is not None:
                context.scene.sb_state.detail_normal_target = tuple(float(item) for item in value)
                self._set_header(
                    context,
                    f"Picked Normal {tuple(round(float(v), 3) for v in value)} · release Alt to paint",
                )
            return
        if context.scene.sb_state.detail_preview_mode in {'GEOMETRY_NORMAL', 'FINAL_NORMAL'}:
            context.scene.sb_state.detail_preview_mode = 'NORMAL_EDIT'
        location = _projected_hit(context, event)
        if location is None:
            return
        pixel = _source_pixel_at_location(context.scene, self._image, location)
        if pixel is None:
            return
        mode = self._active_mode(context, event)
        target = _normalized(context.scene.sb_state.detail_normal_target)
        if mode == 'SET':
            x0, x1, y0, y1 = _set_brush_bounds(
                context.scene,
                self._image,
                *pixel,
                context.scene.sb_state.detail_set_size,
            )
            region = self._pixels[y0:y1, x0:x1]
            valid = region[..., 3] > 1e-6
            region[valid, :3] = target * 0.5 + 0.5
        else:
            layout = projection.state_layout(context.scene)
            projected_x, projected_y = projection.project_world_point(location)
            center_x = (projected_x - layout.min_x) * EDIT_SCALE
            center_y = (projected_y - layout.min_y) * EDIT_SCALE
            radius_name = brush_radius_property(mode)
            radius_value = getattr(context.scene.sb_state, radius_name)
            radius = max(1.0, radius_value * EDIT_SCALE)
            height, width = self._pixels.shape[:2]
            min_x = max(0, int(math.floor(center_x - radius)))
            max_x = min(width - 1, int(math.ceil(center_x + radius)))
            min_y = max(0, int(math.floor(center_y - radius)))
            max_y = min(height - 1, int(math.ceil(center_y + radius)))
            if min_x > max_x or min_y > max_y:
                return
            yy, xx = np.mgrid[min_y : max_y + 1, min_x : max_x + 1]
            distance = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)
            mask = distance <= radius
            falloff = np.clip(1.0 - distance / radius, 0.0, 1.0) ** 2
            region = self._pixels[min_y : max_y + 1, min_x : max_x + 1]
            valid = mask & (region[..., 3] > 1e-6)
            vectors = region[..., :3] * 2.0 - 1.0
            if mode == 'SMOOTH':
                padded_vectors = np.pad(vectors, ((1, 1), (1, 1), (0, 0)), mode='edge')
                padded_alpha = np.pad(region[..., 3], 1, mode='constant')
                summed = np.zeros_like(vectors)
                weights = np.zeros(region.shape[:2], dtype=np.float32)
                for y in range(3):
                    for x in range(3):
                        alpha = padded_alpha[y : y + region.shape[0], x : x + region.shape[1]]
                        summed += padded_vectors[
                            y : y + region.shape[0],
                            x : x + region.shape[1],
                        ] * alpha[..., np.newaxis]
                        weights += alpha
                desired = summed / np.maximum(weights[..., np.newaxis], 1e-8)
            elif mode in {'BULGE', 'DENT'}:
                desired = _radial_sculpt_vectors(
                    vectors,
                    xx - center_x,
                    yy - center_y,
                    radius,
                    bulge=mode == 'BULGE',
                )
            else:
                desired = np.broadcast_to(target, vectors.shape)
            strength = np.minimum(1.0, context.scene.sb_state.detail_brush_strength)
            factor = (
                np.full_like(distance, strength)
                if mode in {'BULGE', 'DENT'}
                else strength * falloff
            )
            vectors[valid] += (desired[valid] - vectors[valid]) * factor[valid, np.newaxis]
            lengths = np.linalg.norm(vectors, axis=2, keepdims=True)
            vectors /= np.maximum(lengths, 1e-8)
            region[valid, :3] = vectors[valid] * 0.5 + 0.5
        self._image.pixels.foreach_set(self._pixels.ravel())
        self._image.update()
        self._changed = True
        self._stroke_changed = True
        context.area.tag_redraw()

    def invoke(self, context, event):
        self._image = source_image(context.scene)
        if self._image is None:
            self.report({'ERROR'}, "Initialize Normal Edit from geometry first")
            return {'CANCELLED'}
        self._pixels = np.asarray(self._image.pixels[:], dtype=np.float32).reshape(
            self._image.size[1],
            self._image.size[0],
            4,
        )
        self._painting = False
        self._changed = False
        self._stroke_changed = False
        self._stroke_before = None
        self._undo_stack = []
        self._redo_stack = []
        self._navigating = False
        self._navigation_mouse = (event.mouse_x, event.mouse_y)
        self._normal_picker = None
        context.scene.sb_state.detail_preview_mode = 'NORMAL_EDIT'
        context.window.cursor_modal_set('PAINT_BRUSH')
        self._set_header(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        if self._normal_picker is not None:
            self._normal_picker.stop()
            self._normal_picker = None
        context.window.cursor_modal_restore()
        context.area.header_text_set(None)
        if self._changed:
            _pack_image(self._image)
            mark_dirty(context.scene)
            if context.scene.sb_state.detail_auto_rebuild:
                try:
                    generate_normal(context.scene)
                except Exception as error:
                    self.report({'ERROR'}, f"Normal edits saved, output rebuild failed: {error}")
        return {'FINISHED'}

    def cancel(self, context):
        if self._image is not None and self._pixels is not None:
            self._finish(context)

    def modal(self, context, event):
        if self._normal_picker is not None:
            self._handle_normal_picker(context, event)
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and event.type == 'N':
            try:
                self._start_normal_picker(context, event)
            except Exception as error:
                self.report({'ERROR'}, f"Normal Picker failed: {error}")
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            return self._finish(context)
        if event.type in {'RET', 'NUMPAD_ENTER'}:
            return self._finish(context)
        if event.value == 'PRESS' and event.ctrl and event.type == 'Z':
            if event.shift:
                self._redo_stroke(context)
            else:
                self._undo_stroke(context)
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and event.ctrl and event.type == 'Y':
            self._redo_stroke(context)
            return {'RUNNING_MODAL'}
        if event.type == 'TAB' and event.value == 'PRESS':
            state = context.scene.sb_state
            modes = ('NORMAL_EDIT', 'FINAL_NORMAL', 'GEOMETRY_NORMAL', 'MATERIAL')
            direction = -1 if event.shift else 1
            state.detail_preview_mode = modes[
                (modes.index(state.detail_preview_mode) + direction) % len(modes)
            ]
            self._set_header(context)
            return {'RUNNING_MODAL'}
        if event.type == 'MIDDLEMOUSE':
            if event.value == 'PRESS':
                self._navigating = True
                self._navigation_mouse = (event.mouse_x, event.mouse_y)
            elif event.value == 'RELEASE':
                self._navigating = False
                self._set_header(context)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE' and self._navigating:
            self._pan_view(context, event)
            return {'RUNNING_MODAL'}
        direct_tools = {
            'ONE': 'PAINT',
            'NUMPAD_1': 'PAINT',
            'TWO': 'SET',
            'NUMPAD_2': 'SET',
            'THREE': 'SMOOTH',
            'NUMPAD_3': 'SMOOTH',
            'FOUR': 'BULGE',
            'NUMPAD_4': 'BULGE',
            'FIVE': 'DENT',
            'NUMPAD_5': 'DENT',
        }
        direct_previews = {
            'ONE': 'NORMAL_EDIT',
            'NUMPAD_1': 'NORMAL_EDIT',
            'TWO': 'FINAL_NORMAL',
            'NUMPAD_2': 'FINAL_NORMAL',
            'THREE': 'GEOMETRY_NORMAL',
            'NUMPAD_3': 'GEOMETRY_NORMAL',
            'FOUR': 'MATERIAL',
            'NUMPAD_4': 'MATERIAL',
        }
        if event.value == 'PRESS' and event.shift and event.type in direct_previews:
            context.scene.sb_state.detail_preview_mode = direct_previews[event.type]
            self._set_header(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and not event.shift and event.type in direct_tools:
            self._switch_tool(context, direct_tools[event.type])
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and event.type in {'Q', 'E'}:
            current = context.scene.sb_state.detail_brush_mode
            direction = -1 if event.type == 'Q' else 1
            self._switch_tool(
                context,
                BRUSH_MODES[(BRUSH_MODES.index(current) + direction) % len(BRUSH_MODES)],
            )
            return {'RUNNING_MODAL'}
        if (
            event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
            and event.value == 'PRESS'
            and event.ctrl
        ):
            change = 1 if event.type == 'WHEELUPMOUSE' else -1
            if self._adjust_radius(context, event, change):
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}
            return {'RUNNING_MODAL'}
        if (
            event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}
            and event.value == 'PRESS'
            and event.alt
        ):
            change = 1 if event.type == 'WHEELUPMOUSE' else -1
            if self._adjust_strength(context, event, change):
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.value == 'PRESS':
            self._zoom_view(context, zoom_in=event.type == 'WHEELUPMOUSE')
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._painting = True
                self._stroke_changed = False
                self._stroke_before = self._pixels.copy()
                self._dab(context, event)
            elif event.value == 'RELEASE':
                self._painting = False
                if self._stroke_changed:
                    self._undo_stack.append(self._stroke_before)
                    if len(self._undo_stack) > NORMAL_UNDO_LIMIT:
                        overflow = len(self._undo_stack) - NORMAL_UNDO_LIMIT
                        del self._undo_stack[:overflow]
                    self._redo_stack.clear()
                    if context.scene.sb_state.detail_auto_rebuild:
                        self._rebuild_preview(context)
                self._stroke_before = None
                self._set_header(context)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE' and self._painting:
            self._dab(context, event)
        return {'RUNNING_MODAL'}
