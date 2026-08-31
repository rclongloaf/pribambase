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
        actions.operator(
            "pribambase.projection_restore_camera",
            text="Restore Camera",
            icon='VIEW_CAMERA',
        )
        projected.operator(
            "pribambase.projection_setup_material",
            text="Create / Repair Material",
            icon='MATERIAL',
        )
        if state.projection_material is not None:
            projected.label(text=f"Material: {state.projection_material.name}", icon='CHECKMARK')

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
