# Copyright (c) 2021 lampysprites
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Primary Pribambase panel in Blender's 3D Viewport."""

import bpy
from .addon import addon
from . import workspace
from . import projection
from . import detail
import numpy as np
from math import pi


def scale_image(image, scale):
    """Scale image in-place without filtering"""
    w, h = image.size
    px = np.array(image.pixels, dtype=np.float32)
    px.shape = (w, h, 4)
    image.scale(w * scale, h * scale)
    px = px.repeat(scale, 0).repeat(scale, 1)
    try:
        # version >= 2.83
        image.pixels.foreach_set(px.ravel())
    except:
        # version < 2.83
        image.pixels[:] = px.ravel()
    image.update()

class SB_PT_panel_link(bpy.types.Panel):
    bl_idname = "SB_PT_panel_link_3d"
    bl_label = "Pribambase"
    bl_category = "Tool"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"


    def draw(self, context):
        layout = self.layout
        state = context.scene.sb_state

        row = layout.row()
        status = "Sync paused"
        icon = 'UNLINKED'
        if addon.connected:
            status = "Sync active"
            icon = 'CHECKMARK'
        elif addon.server_up:
            status = "Waiting for Aseprite..."
            icon = 'SORTTIME'

        row.label(text=status, icon=icon)

        row = row.row()
        row.alignment = 'RIGHT'
        if addon.server_up:
            row.operator("pribambase.sync_stop", text="Pause", icon="PAUSE")
        else:
            row.operator("pribambase.sync_start", text="Start Sync", icon="PLAY")
        row.operator("pribambase.preferences", icon='PREFERENCES', text="", emboss=False)

        pair = layout.box()
        pair.label(text="Source Pair", icon='LINKED')
        pair.prop(state, "asset_name")
        pair.prop(state, "sprite_path", text="Aseprite")

        network = pair.row()
        network.enabled = not addon.server_up
        network.prop(addon.prefs, "localhost", text="Same computer only")

        image = workspace.paired_image(context)
        if image is not None:
            pair.label(text=f"Blender texture: {image.name}", icon='IMAGE_DATA')
        else:
            warning = pair.row()
            warning.alert = True
            warning.label(text="Choose Paint Texture or select a textured object", icon='ERROR')

        row = pair.row(align=True)
        row.operator("pribambase.pair_save", text="Save Pair", icon='FILE_TICK')
        row.operator("pribambase.pair_load", text="Load Pair", icon='FILE_FOLDER')

        projected = layout.box()
        projected.label(text="Global Projection", icon='MOD_UVPROJECT')
        projected.label(
            text=f"Global Iso · {projection.PIXELS_PER_UNIT:g} pixels/unit",
            icon='WORLD',
        )
        projected.prop(state, "projection_collection")
        projected.prop(state, "projection_image")
        projected.prop(state, "material_image")
        projected.prop(state, "emission_strength")

        options = projected.row(align=True)
        options.prop(state, "projection_padding")
        options.prop(state, "projection_auto_grow", text="Auto-grow")

        canvas = projection.state_layout(context.scene)
        if canvas is None:
            warning = projected.row()
            warning.alert = True
            warning.label(text="Animation canvas is not calculated", icon='ERROR')
        else:
            projected.label(
                text=f"Canvas {canvas.width} × {canvas.height} px · origin ({canvas.origin_x}, {canvas.origin_y})",
                icon='IMAGE_PLANE',
            )
            if state.projection_bounds_dirty:
                warning = projected.row()
                warning.alert = True
                warning.label(text="Animation bounds may have changed", icon='ERROR')

        actions = projected.row(align=True)
        actions.operator(
            "pribambase.projection_recalculate",
            text="Recalculate Canvas",
            icon='FILE_REFRESH',
        )
        camera_actions = projected.row(align=True)
        camera_actions.operator(
            "pribambase.projection_restore_camera",
            text="Restore Camera",
            icon='VIEW_CAMERA',
        )
        camera_actions.operator(
            "pribambase.projection_view_camera",
            text="View Camera",
            icon='CAMERA_DATA',
        )
        projected.operator(
            "pribambase.projection_setup_material",
            text="Create / Repair Material",
            icon='MATERIAL',
        )
        if state.projection_material is not None:
            projected.label(text=f"Material: {state.projection_material.name}", icon='CHECKMARK')

        surface = layout.box()
        surface.label(text="World Normal Edit", icon='NORMALS_FACE')
        canvas = projection.state_layout(context.scene)
        source = detail.source_image(context.scene)
        normal = detail.normal_image(context.scene)
        geometry_normal = detail.geometry_normal_image(context.scene)
        if canvas is None:
            warning = surface.row()
            warning.alert = True
            warning.label(text="Calculate the animation canvas first", icon='ERROR')
        else:
            surface.label(
                text=(
                    f"Frame {context.scene.frame_current} · Edit "
                    f"{canvas.width * detail.EDIT_SCALE}×{canvas.height * detail.EDIT_SCALE} "
                    f"→ Output {canvas.width}×{canvas.height}"
                ),
                icon='IMAGE_DATA',
            )
            if source is None:
                surface.label(text="Normal Edit: not initialized for this frame", icon='INFO')
            else:
                surface.label(text=f"Normal Edit: {source.name}", icon='KEYFRAME')
            if geometry_normal is not None:
                surface.label(text=f"Geometry Normal: {geometry_normal.name}", icon='LOCKED')
            if context.scene.frame_current in detail.geometry_dirty_frames():
                warning = surface.row()
                warning.alert = True
                warning.label(text="Geometry changed — reset source if needed", icon='ERROR')

        preview = surface.column(align=True)
        preview.prop(state, "detail_preview_mode", expand=True)
        if state.detail_preview_mode == 'NORMAL_EDIT' and source is None:
            warning = preview.row()
            warning.alert = True
            warning.label(text="Initialize Normal Edit to preview it", icon='ERROR')
        elif state.detail_preview_mode == 'GEOMETRY_NORMAL' and geometry_normal is None:
            warning = preview.row()
            warning.alert = True
            warning.label(text="Reset from Geometry to create the reference", icon='ERROR')
        elif state.detail_preview_mode == 'FINAL_NORMAL' and normal is None:
            warning = preview.row()
            warning.alert = True
            warning.label(text="Rebuild World Normal to create Final", icon='ERROR')
        preview.label(text="Preview is unlit; Aseprite guide stays Material", icon='SHADING_RENDERED')
        preview.label(text="Use Material Preview or Rendered viewport", icon='INFO')

        frames = surface.row(align=True)
        frames.enabled = canvas is not None
        frames.operator(
            "pribambase.detail_initialize",
            text="Reset from Geometry" if source is not None else "Initialize from Geometry",
            icon='RENDER_STILL',
        )
        remove = frames.row(align=True)
        remove.enabled = source is not None
        remove.operator("pribambase.detail_remove_source", text="Remove Frame", icon='X')

        brush = surface.column(align=True)
        brush.enabled = source is not None
        brush.prop(state, "detail_brush_mode")
        if state.detail_brush_mode != 'SET':
            values = brush.row(align=True)
            values.prop(state, detail.brush_radius_property(state.detail_brush_mode))
            values.prop(state, "detail_brush_strength")
        if state.detail_brush_mode in {'PAINT', 'SET'}:
            target = brush.row(align=True)
            target.prop(state, "detail_normal_target")
            target.operator("pribambase.detail_pick_normal", text="", icon='EYEDROPPER')
            target.operator(
                "pribambase.detail_free_pick_normal",
                text="",
                icon='ORIENTATION_GIMBAL',
            )
            picker = brush.row(align=True)
            picker.prop(state, "detail_picker_mode", expand=True)
            if state.detail_picker_mode == 'QUANTIZED':
                divisions = state.detail_picker_divisions
                brush.prop(state, "detail_picker_divisions", slider=True)
                brush.label(
                    text=f"1/{divisions} of 90° = {90.0 / divisions:g}°",
                    icon='DRIVER_ROTATIONAL_DIFFERENCE',
                )
        if state.detail_brush_mode == 'SET':
            brush.prop(state, "detail_set_size")
            brush.prop(state, "detail_pixel_scope")
            unit = "output pixels" if state.detail_pixel_scope == 'OUTPUT' else "edit samples"
            brush.label(text=f"Exact {state.detail_set_size}×{state.detail_set_size} {unit}", icon='SNAP_GRID')
        else:
            radius_name = detail.brush_radius_property(state.detail_brush_mode)
            radius = getattr(state, radius_name)
            brush.label(
                text=f"Radius {radius} px = {radius * detail.EDIT_SCALE} edit samples",
                icon='BRUSH_DATA',
            )
        brush.label(text="Q/E or 1–5 tool · Ctrl+Wheel radius/size", icon='INFO')
        brush.label(text="Alt+Wheel strength", icon='MODIFIER')
        brush.label(text="MMB pan · Wheel view zoom", icon='VIEWZOOM')
        brush.label(text="Ctrl+Z undo · Ctrl+Y redo · Enter/Esc save", icon='LOOP_BACK')
        brush.label(text="Alt pick visible normal · Shift smooth", icon='INFO')
        brush.label(text="N free Normal Ball", icon='ORIENTATION_GIMBAL')
        brush.label(text="Tab/Shift+Tab cycle · Shift+1–4 preview", icon='INFO')
        brush.operator("pribambase.detail_paint", text="Paint Normals", icon='BRUSH_DATA')

        shader = surface.column(align=True)
        apply_row = shader.row()
        apply_row.enabled = normal is not None
        apply_row.prop(state, "apply_generated_normal")
        shader.prop(state, "detail_auto_rebuild")
        shader.prop(state, "detail_auto_send")
        if context.scene.frame_current in detail.dirty_frames():
            shader.label(text="World Normal is out of date", icon='ERROR')
        elif normal is not None:
            shader.label(text=f"World Normal: {normal.name}", icon='CHECKMARK')
        elif source is not None:
            shader.label(text="World Normal is out of date", icon='ERROR')

        detail_actions = surface.row(align=True)
        detail_actions.operator("pribambase.detail_rebuild", text="Rebuild + Send", icon='FILE_REFRESH')
        if detail.dirty_frames():
            surface.operator(
                "pribambase.detail_rebuild_dirty",
                text=f"Rebuild Dirty Frames ({len(detail.dirty_frames())})",
                icon='RENDER_ANIMATION',
            )

        if addon.server_up:
            sync = layout.box()
            sync.label(text="Live Updates", icon='FILE_REFRESH')
            sync.prop(state, "auto_render_current")
            delay = sync.row()
            delay.enabled = state.auto_render_current
            delay.prop(state, "auto_render_delay")
            sync.prop(state, "auto_render_on_save")
            sync.prop(state, "follow_frame")
            sync.prop(state, "guide_layer")

            frame = context.scene.frame_current
            fps = context.scene.render.fps / context.scene.render.fps_base
            sync.label(text=f"Frame {frame} · {fps:g} FPS", icon='TIME')

            dirty = workspace.dirty_frames()
            if dirty:
                shown = ", ".join(str(value) for value in dirty[:8])
                if len(dirty) > 8:
                    shown += f" … (+{len(dirty) - 8})"
                sync.label(text=f"Changed frames: {shown}", icon='REC')
            elif workspace.last_projection_frame() is not None:
                sync.label(
                    text=f"Projection current through frame {workspace.last_projection_frame()}",
                    icon='CHECKMARK',
                )

            if workspace.last_error():
                error = sync.row()
                error.alert = True
                error.label(text=workspace.last_error(), icon='ERROR')

            actions = sync.row(align=True)
            actions.operator("pribambase.projection_current", text="Update Guide", icon='RENDER_STILL')
            actions.operator("pribambase.pair_open_sprite", text="Open Aseprite", icon='GREASEPENCIL')
            if dirty:
                sync.operator(
                    "pribambase.projection_dirty",
                    text=f"Render Dirty Frames ({len(dirty)})",
                    icon='RENDER_ANIMATION',
                )
