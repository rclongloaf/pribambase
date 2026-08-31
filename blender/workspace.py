"""Asset-pair workflow and safe automatic projection updates for Blender."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import bpy

from . import util
from . import projection
from .addon import addon
from .messaging import encode
from .render import get_render_image, remove_render_image


_dirty_frames: set[int] = set()
_render_due = 0.0
_rendering = False
_applying_remote_frame = False
_batch_frames: list[int] = []
_batch_restore_frame: int | None = None
_last_projection_frame: int | None = None
_last_error = ""


def resolved_sprite_path(scene: bpy.types.Scene) -> str:
    source = scene.sb_state.sprite_path.strip()
    if not source:
        return ""
    return bpy.path.abspath(source)


def default_manifest_path(scene: bpy.types.Scene) -> Path | None:
    if not bpy.data.filepath:
        return None
    blend_path = Path(bpy.data.filepath)
    return blend_path.with_suffix(".pribambase.json")


def resolved_manifest_path(scene: bpy.types.Scene) -> Path | None:
    source = scene.sb_state.manifest_path.strip()
    if source:
        return Path(bpy.path.abspath(source))
    return default_manifest_path(scene)


def asset_name(scene: bpy.types.Scene) -> str:
    configured = scene.sb_state.asset_name.strip()
    if configured:
        return configured
    if bpy.data.filepath:
        return Path(bpy.data.filepath).stem
    return scene.name


def _relative_or_absolute(path: Path, parent: Path) -> str:
    try:
        return os.path.relpath(path, parent)
    except ValueError:
        return str(path)


def workspace_manifest(scene: bpy.types.Scene, manifest_path: Path) -> dict[str, object]:
    sprite = Path(resolved_sprite_path(scene))
    blend = Path(bpy.data.filepath)
    state = scene.sb_state
    manifest = {
        "schema_version": 2,
        "asset": asset_name(scene),
        "sources": {
            "blender": _relative_or_absolute(blend, manifest_path.parent),
            "aseprite": _relative_or_absolute(sprite, manifest_path.parent),
        },
        "animation": {
            "fps": scene.render.fps / scene.render.fps_base,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        },
        "sync": {
            "guide_layer": state.guide_layer,
            "auto_render_current": state.auto_render_current,
            "auto_render_on_save": state.auto_render_on_save,
            "follow_frame": state.follow_frame,
        },
    }
    layout = projection.state_layout(scene)
    if layout is not None:
        collection = state.projection_collection
        material = state.projection_material
        manifest["projection"] = {
            "profile": projection.PROFILE_NAME,
            "pixels_per_unit": projection.PIXELS_PER_UNIT,
            "collection": collection.name if collection is not None else "",
            "material": material.name if material is not None else "",
            "image": state.projection_image.name if state.projection_image is not None else "",
            "material_image": state.material_image.name if state.material_image is not None else "",
            "emission_strength": state.emission_strength,
            "padding": state.projection_padding,
            "auto_grow": state.projection_auto_grow,
            "canvas": {
                "min_x": layout.min_x,
                "min_y": layout.min_y,
                "max_x": layout.max_x,
                "max_y": layout.max_y,
                "width": layout.width,
                "height": layout.height,
                "origin_x": layout.origin_x,
                "origin_y": layout.origin_y,
            },
        }
    return manifest


def write_manifest(scene: bpy.types.Scene) -> Path:
    if not bpy.data.filepath:
        raise RuntimeError("Save the Blender file before creating an asset pair")
    if not resolved_sprite_path(scene):
        raise RuntimeError("Choose an Aseprite source before creating an asset pair")

    manifest_path = resolved_manifest_path(scene)
    if manifest_path is None:
        raise RuntimeError("Could not determine the pair manifest path")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(workspace_manifest(scene, manifest_path), indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def load_manifest(scene: bpy.types.Scene, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in {1, 2}:
        raise RuntimeError("Unsupported Pribambase pair manifest version")

    sources = manifest.get("sources", {})
    animation = manifest.get("animation", {})
    sync = manifest.get("sync", {})
    projection_data = manifest.get("projection", {})
    sprite_value = str(sources.get("aseprite", ""))
    sprite_path = Path(sprite_value)
    if not sprite_path.is_absolute():
        sprite_path = manifest_path.parent / sprite_path

    state = scene.sb_state
    state.asset_name = str(manifest.get("asset", ""))
    state.sprite_path = bpy.path.relpath(str(sprite_path.resolve()))
    state.manifest_path = bpy.path.relpath(str(manifest_path.resolve()))
    state.guide_layer = str(sync.get("guide_layer", state.guide_layer))
    state.auto_render_current = bool(sync.get("auto_render_current", True))
    state.auto_render_on_save = bool(sync.get("auto_render_on_save", False))
    state.follow_frame = bool(sync.get("follow_frame", True))

    if isinstance(projection_data, dict) and projection_data:
        profile = str(projection_data.get("profile", ""))
        if profile != projection.PROFILE_NAME:
            raise RuntimeError(f"Unsupported projection profile: {profile or 'missing'}")
        collection_name = str(projection_data.get("collection", ""))
        material_name = str(projection_data.get("material", ""))
        image_name = str(projection_data.get("image", ""))
        material_image_name = str(projection_data.get("material_image", ""))
        state.projection_collection = bpy.data.collections.get(collection_name)
        state.projection_material = bpy.data.materials.get(material_name)
        state.projection_image = bpy.data.images.get(image_name)
        state.material_image = bpy.data.images.get(material_image_name)
        state.emission_strength = float(projection_data.get("emission_strength", 2.0))
        state.projection_padding = int(projection_data.get("padding", 2))
        state.projection_auto_grow = bool(projection_data.get("auto_grow", True))
        canvas = projection_data.get("canvas", {})
        if isinstance(canvas, dict):
            layout = projection.Layout(
                int(canvas.get("min_x", 0)),
                int(canvas.get("min_y", 0)),
                int(canvas.get("max_x", 0)),
                int(canvas.get("max_y", 0)),
            )
            if layout.width > 0 and layout.height > 0:
                projection.set_state_layout(scene, layout)
                projection.update_project_material(scene)
    else:
        state.projection_bounds_dirty = True

    if "fps" in animation:
        scene.render.fps = max(1, round(float(animation["fps"])))
        scene.render.fps_base = 1.0
    if "frame_start" in animation:
        scene.frame_start = int(animation["frame_start"])
    if "frame_end" in animation:
        scene.frame_end = int(animation["frame_end"])


def _image_from_active_object(context) -> bpy.types.Image | None:
    obj = getattr(context, "object", None)
    if obj is None:
        return None
    for material_slot in obj.material_slots:
        material = material_slot.material
        if material is None or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image is not None:
                return node.image
    return None


def paired_image(context=None) -> bpy.types.Image | None:
    scene = (context or bpy.context).scene
    if scene.sb_state.projection_image is not None:
        return scene.sb_state.projection_image
    source = resolved_sprite_path(scene)
    if source:
        for image in bpy.data.images:
            if util.image_name(image) == source:
                return image
    return _image_from_active_object(context or bpy.context)


def ensure_image_pair(context) -> bpy.types.Image | None:
    source = resolved_sprite_path(context.scene)
    if not source:
        return None
    image = paired_image(context)
    if image is not None and util.image_name(image) != source:
        image.sb_source = context.scene.sb_state.sprite_path
    if image is not None:
        context.scene.sb_state.projection_image = image
    return image


def _default_projection_collection(context) -> None:
    state = context.scene.sb_state
    if state.projection_collection is not None:
        return
    obj = getattr(context, "object", None)
    if obj is not None and obj.users_collection:
        collection = obj.users_collection[0]
        # Scene.collection is an embedded datablock and cannot be stored in an
        # RNA pointer property. None already means the full scene collection.
        if collection != context.scene.collection:
            state.projection_collection = collection


def canvas_message(scene: bpy.types.Scene) -> bytearray | None:
    layout = projection.state_layout(scene)
    source = resolved_sprite_path(scene)
    if layout is None or not source:
        return None
    return encode.canvas(
        size=(layout.width, layout.height),
        origin=(layout.origin_x, layout.origin_y),
        sprite=source,
    )


def recalculate_projection_layout(scene: bpy.types.Scene) -> tuple[projection.Layout, bool]:
    required = projection.calculate_animation_layout(scene)
    old_layout = projection.state_layout(scene)
    image = paired_image()
    if old_layout is None and image is not None:
        old_layout = projection.centered_layout(image.size[0], image.size[1])

    new_layout = required if old_layout is None else old_layout.union(required)
    if new_layout.width > 65535 or new_layout.height > 65535:
        raise RuntimeError("Animation canvas exceeds the protocol limit of 65535 pixels per side")
    changed = old_layout != new_layout
    if changed and old_layout is not None:
        if image is not None:
            projection.resize_image_canvas(image, old_layout, new_layout)
        material_image = scene.sb_state.material_image
        if material_image is not None and material_image != image:
            projection.resize_image_canvas(
                material_image,
                old_layout,
                new_layout,
                fill_color=(1.0, 128.0 / 255.0, 0.0, 0.0),
            )
    projection.set_state_layout(scene, new_layout)
    projection.update_project_material(scene)

    if changed and addon.connected:
        message = canvas_message(scene)
        if message is not None:
            addon.server.send(message)
    if changed and bpy.data.filepath and resolved_sprite_path(scene):
        try:
            write_manifest(scene)
        except Exception as error:
            print(f"Pribambase: could not update expanded canvas in pair manifest: {error}")
    return new_layout, changed


def ensure_projection_layout(scene: bpy.types.Scene) -> projection.Layout:
    layout = projection.state_layout(scene)
    if layout is None or (scene.sb_state.projection_bounds_dirty and scene.sb_state.projection_auto_grow):
        layout, _changed = recalculate_projection_layout(scene)
    return layout


def connection_messages(scene: bpy.types.Scene) -> list[bytearray]:
    messages: list[bytearray] = []
    source = resolved_sprite_path(scene)
    if source:
        messages.append(encode.workspace(asset_name(scene), source))
        messages.append(encode.sprite_open(source))
        canvas = canvas_message(scene)
        if canvas is not None:
            messages.append(canvas)
    if scene.sb_state.follow_frame:
        messages.append(encode.frame(scene.frame_current))
    return messages


def _projection_message(scene: bpy.types.Scene, image, frame: int) -> bytearray:
    source = resolved_sprite_path(scene)
    pixels = util.get_mirrored_pixels(image)
    guide = encode.uv_map(
        size=(image.size[0], image.size[1]),
        sprite=source,
        pixels=pixels,
        layer=scene.sb_state.guide_layer,
        opacity=255,
    )
    messages = [encode.guide_frame(frame), guide]
    canvas = canvas_message(scene)
    if canvas is not None:
        messages.insert(0, canvas)
    if source:
        messages.insert(0, encode.sprite_focus(source))
    return encode.batch(messages)


def send_projection(scene: bpy.types.Scene, frame: int | None = None) -> None:
    global _rendering, _last_projection_frame, _last_error
    if not addon.connected:
        raise RuntimeError("Aseprite is not connected")

    target_frame = scene.frame_current if frame is None else frame
    _rendering = True
    image = None
    try:
        ensure_projection_layout(scene)
        with projection.projection_render_context(scene):
            image = get_render_image()
        addon.server.send(_projection_message(scene, image, target_frame))
        _dirty_frames.discard(target_frame)
        _last_projection_frame = target_frame
        _last_error = ""
    except Exception as error:
        _last_error = str(error)
        raise
    finally:
        if image is not None:
            remove_render_image(image)
        _rendering = False
        util.refresh()


def dirty_frames() -> tuple[int, ...]:
    return tuple(sorted(_dirty_frames))


def last_projection_frame() -> int | None:
    return _last_projection_frame


def last_error() -> str:
    return _last_error


def is_rendering() -> bool:
    return _rendering or _batch_restore_frame is not None or projection.is_scanning()


def _auto_render_timer():
    if time.monotonic() < _render_due:
        return max(0.05, _render_due - time.monotonic())
    scene = getattr(bpy.context, "scene", None)
    if (
        scene is None
        or not addon.connected
        or not scene.sb_state.auto_render_current
        or scene.frame_current not in _dirty_frames
    ):
        return None
    try:
        send_projection(scene)
    except Exception as error:
        bpy.ops.pribambase.report(message_type='ERROR', message=f"Auto projection failed: {error}")
    return None


def mark_current_frame_dirty(scene: bpy.types.Scene) -> None:
    global _render_due
    if is_rendering() or not addon.server_up:
        return
    _dirty_frames.add(scene.frame_current)
    if scene.sb_state.auto_render_current:
        _render_due = time.monotonic() + scene.sb_state.auto_render_delay
        if not bpy.app.timers.is_registered(_auto_render_timer):
            bpy.app.timers.register(_auto_render_timer, first_interval=scene.sb_state.auto_render_delay)
    util.refresh()


def _projection_bounds_changed(scene: bpy.types.Scene, updates) -> bool:
    """Return whether depsgraph updates can change the projected canvas bounds.

    Blender reports projected mesh objects as updated when only their material
    node tree changes. Those shading-only notifications do not affect the
    animation bounds and must not bring the canvas warning back immediately
    after a successful recalculation.
    """
    objects = projection.projection_objects(scene)
    object_ids = {obj.as_pointer() for obj in objects}
    mesh_ids = {obj.data.as_pointer() for obj in objects if obj.data is not None}
    collection_id = projection.projection_collection(scene).as_pointer()

    for update in updates:
        item = update.id.original
        if isinstance(item, bpy.types.Object):
            if item.as_pointer() in object_ids and (
                update.is_updated_geometry or update.is_updated_transform
            ):
                return True
        elif isinstance(item, bpy.types.Mesh):
            if item.as_pointer() in mesh_ids and update.is_updated_geometry:
                return True
        elif isinstance(item, bpy.types.Collection):
            if item.as_pointer() == collection_id and update.is_updated_geometry:
                return True
    return False


def on_depsgraph_update(scene: bpy.types.Scene, depsgraph) -> None:
    if is_rendering() or not addon.server_up:
        return
    updates = tuple(depsgraph.updates)
    updated = tuple(update.id.original for update in updates)
    render_changed = any(
        isinstance(item, (bpy.types.Mesh, bpy.types.Light, bpy.types.World, bpy.types.Material))
        or (
            isinstance(item, bpy.types.Object)
            and item.type in {'MESH', 'LIGHT'}
        )
        for item in updated
    )
    if _projection_bounds_changed(scene, updates):
        scene.sb_state.projection_bounds_dirty = True
    # The scene camera is only a viewing aid. Guides always use the canonical
    # global projection camera, so moving the user's camera is intentionally ignored.
    if render_changed:
        mark_current_frame_dirty(scene)


def on_frame_change(scene: bpy.types.Scene) -> None:
    if is_rendering() or _applying_remote_frame or not addon.connected:
        return
    if scene.sb_state.follow_frame:
        addon.server.send(encode.frame(scene.frame_current))


def apply_remote_frame(frame: int) -> None:
    global _applying_remote_frame
    scene = getattr(bpy.context, "scene", None)
    if scene is None or not scene.sb_state.follow_frame or scene.frame_current == frame:
        return
    if frame < scene.frame_start or frame > scene.frame_end:
        return
    _applying_remote_frame = True
    try:
        scene.frame_set(frame)
    finally:
        _applying_remote_frame = False


def _finish_batch(scene: bpy.types.Scene) -> None:
    global _batch_restore_frame
    if _batch_restore_frame is not None and scene.frame_current != _batch_restore_frame:
        scene.frame_set(_batch_restore_frame)
    if addon.connected and scene.sb_state.follow_frame:
        addon.server.send(encode.frame(scene.frame_current))
    _batch_restore_frame = None
    util.refresh()


def _batch_render_timer():
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        _batch_frames.clear()
        return None
    if not addon.connected:
        _batch_frames.clear()
        _finish_batch(scene)
        return None
    if not _batch_frames:
        _finish_batch(scene)
        return None

    frame = _batch_frames.pop(0)
    try:
        scene.frame_set(frame)
        send_projection(scene, frame)
    except Exception as error:
        bpy.ops.pribambase.report(message_type='ERROR', message=f"Frame {frame}: {error}")
    return 0.05


def render_dirty_frames(scene: bpy.types.Scene) -> int:
    global _batch_restore_frame
    if not addon.connected:
        raise RuntimeError("Aseprite is not connected")
    if _batch_frames:
        return len(_batch_frames)
    _batch_frames.extend(dirty_frames())
    if not _batch_frames:
        return 0
    _batch_restore_frame = scene.frame_current
    if not bpy.app.timers.is_registered(_batch_render_timer):
        bpy.app.timers.register(_batch_render_timer, first_interval=0.01)
    util.refresh()
    return len(_batch_frames)


def on_save(scene: bpy.types.Scene) -> None:
    if scene.sb_state.auto_render_on_save and addon.connected and _dirty_frames:
        render_dirty_frames(scene)
    try:
        if resolved_sprite_path(scene):
            write_manifest(scene)
    except Exception as error:
        print(f"Pribambase: could not update pair manifest: {error}")


def reset_runtime() -> None:
    global _rendering, _batch_restore_frame, _last_projection_frame, _last_error
    for timer in (_auto_render_timer, _batch_render_timer):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    _dirty_frames.clear()
    _batch_frames.clear()
    _rendering = False
    _batch_restore_frame = None
    _last_projection_frame = None
    _last_error = ""


class SB_OT_sync_start(bpy.types.Operator):
    bl_idname = "pribambase.sync_start"
    bl_label = "Start Sync"
    bl_description = "Connect this Blender and Aseprite source pair"

    @classmethod
    def poll(cls, context):
        return not addon.server_up

    def execute(self, context):
        state = context.scene.sb_state
        _default_projection_collection(context)
        if not state.sprite_path:
            image = _image_from_active_object(context)
            if image is not None:
                state.sprite_path = image.sb_source or image.filepath
        if not resolved_sprite_path(context.scene):
            self.report({'ERROR'}, "Choose an Aseprite source or select an object with a linked texture")
            return {'CANCELLED'}

        ensure_image_pair(context)
        try:
            ensure_projection_layout(context.scene)
        except Exception as error:
            self.report({'ERROR'}, f"Could not calculate animation canvas: {error}")
            return {'CANCELLED'}
        if bpy.data.filepath:
            try:
                write_manifest(context.scene)
            except Exception as error:
                self.report({'WARNING'}, f"Could not save pair manifest: {error}")
        try:
            addon.start_server()
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class SB_OT_sync_stop(bpy.types.Operator):
    bl_idname = "pribambase.sync_stop"
    bl_label = "Pause Sync"
    bl_description = "Pause automatic exchange with Aseprite"

    @classmethod
    def poll(cls, context):
        return addon.server_up

    def execute(self, context):
        addon.stop_server()
        reset_runtime()
        return {'FINISHED'}


class SB_OT_pair_save(bpy.types.Operator):
    bl_idname = "pribambase.pair_save"
    bl_label = "Save Source Pair"
    bl_description = "Write the Blender and Aseprite pair manifest next to the blend file"

    def execute(self, context):
        try:
            path = write_manifest(context.scene)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Pair saved to {path.name}")
        return {'FINISHED'}


class SB_OT_pair_load(bpy.types.Operator):
    bl_idname = "pribambase.pair_load"
    bl_label = "Load Source Pair"
    bl_description = "Load a Pribambase source-pair manifest"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.pribambase.json", options={'HIDDEN'})

    def execute(self, context):
        try:
            load_manifest(context.scene, Path(self.filepath))
            ensure_image_pair(context)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SB_OT_pair_open_sprite(bpy.types.Operator):
    bl_idname = "pribambase.pair_open_sprite"
    bl_label = "Open in Aseprite"
    bl_description = "Ask the connected Aseprite instance to open the paired source"

    @classmethod
    def poll(cls, context):
        return addon.connected and bool(resolved_sprite_path(context.scene))

    def execute(self, context):
        addon.server.send(encode.sprite_open(resolved_sprite_path(context.scene)))
        return {'FINISHED'}


class SB_OT_projection_current(bpy.types.Operator):
    bl_idname = "pribambase.projection_current"
    bl_label = "Update Current Guide"
    bl_description = "Render the current Blender frame into an Aseprite reference layer"

    @classmethod
    def poll(cls, context):
        return addon.connected and not is_rendering()

    def execute(self, context):
        try:
            send_projection(context.scene)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class SB_OT_projection_dirty(bpy.types.Operator):
    bl_idname = "pribambase.projection_dirty"
    bl_label = "Render Dirty Frames"
    bl_description = "Render every animation frame changed since its last projection"

    @classmethod
    def poll(cls, context):
        return addon.connected and bool(_dirty_frames) and not is_rendering()

    def execute(self, context):
        count = render_dirty_frames(context.scene)
        self.report({'INFO'}, f"Rendering {count} changed frame(s)")
        return {'FINISHED'}


class SB_OT_projection_recalculate(bpy.types.Operator):
    bl_idname = "pribambase.projection_recalculate"
    bl_label = "Recalculate Animation Canvas"
    bl_description = "Scan every animation frame and grow the shared global-projection canvas"

    def execute(self, context):
        _default_projection_collection(context)
        try:
            layout, changed = recalculate_projection_layout(context.scene)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        status = "expanded" if changed else "already fits"
        self.report({'INFO'}, f"Animation canvas {layout.width}×{layout.height} ({status})")
        return {'FINISHED'}


class SB_OT_projection_restore_camera(bpy.types.Operator):
    bl_idname = "pribambase.projection_restore_camera"
    bl_label = "Restore Projection Camera"
    bl_description = "Return the active camera to the canonical global projection view"

    def execute(self, context):
        try:
            ensure_projection_layout(context.scene)
            camera = projection.restore_projection_camera(context.scene)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Restored projection view on {camera.name}")
        return {'FINISHED'}


class SB_OT_projection_setup_material(bpy.types.Operator):
    bl_idname = "pribambase.projection_setup_material"
    bl_label = "Create / Repair Project Material"
    bl_description = "Create the shared world-projected material and assign it to the collection"

    def execute(self, context):
        _default_projection_collection(context)
        image = ensure_image_pair(context)
        if image is None:
            self.report({'ERROR'}, "Choose a Paint Texture or select an object with an image first")
            return {'CANCELLED'}
        try:
            ensure_projection_layout(context.scene)
            material = projection.ensure_project_material(context.scene, image)
            count = projection.assign_project_material(context.scene, material)
            if bpy.data.filepath and resolved_sprite_path(context.scene):
                write_manifest(context.scene)
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Assigned {material.name} to {count} mesh object(s)")
        return {'FINISHED'}
