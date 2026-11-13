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

"""Persistent Blender properties and add-on preferences."""

import bpy

from .addon import addon


def _update_project_material(self, context) -> None:
    from . import projection

    projection.update_project_material(context.scene)


def _update_apply_generated_normal(self, context) -> None:
    from . import projection, workspace

    projection.update_project_material(context.scene)
    workspace.mark_current_frame_dirty(context.scene)


def _update_detail_preview(self, context) -> None:
    from . import projection, util

    projection.update_project_material(context.scene)
    util.refresh()



class SB_State(bpy.types.PropertyGroup):
    asset_name: bpy.props.StringProperty(
        name="Asset",
        description="Shared name of the Blender and Aseprite source pair",
    )

    sprite_path: bpy.props.StringProperty(
        name="Aseprite Source",
        description="Aseprite file that owns the painted texture",
        subtype='FILE_PATH',
        options={'PATH_SUPPORTS_BLEND_RELATIVE'},
    )

    manifest_path: bpy.props.StringProperty(
        name="Pair Manifest",
        description="JSON file describing this Blender and Aseprite source pair",
        subtype='FILE_PATH',
        options={'PATH_SUPPORTS_BLEND_RELATIVE'},
    )

    guide_layer: bpy.props.StringProperty(
        name="Projection Layer",
        description="Reference layer updated by automatic Blender projections",
        default="Pribambase Render",
    )

    auto_render_current: bpy.props.BoolProperty(
        name="Auto-render Current Frame",
        description="Update the current Aseprite guide after geometry, material, or light changes",
        default=True,
    )

    auto_render_on_save: bpy.props.BoolProperty(
        name="Render Dirty Frames on Save",
        description="Render all changed animation frames after saving the Blender file",
        default=False,
    )

    follow_frame: bpy.props.BoolProperty(
        name="Follow Animation Frame",
        description="Keep the Blender and Aseprite animation frames aligned",
        default=True,
    )

    auto_render_delay: bpy.props.FloatProperty(
        name="Auto-render Delay",
        description="Idle time before automatically rendering the current frame",
        default=0.75,
        min=0.1,
        max=10.0,
        subtype='TIME',
    )

    projection_collection: bpy.props.PointerProperty(
        name="Projected Collection",
        description="Collection whose renderable mesh objects share the global projection",
        type=bpy.types.Collection,
    )

    projection_material: bpy.props.PointerProperty(
        name="Project Material",
        description="Single Pribambase material assigned to the projected collection",
        type=bpy.types.Material,
    )

    projection_image: bpy.props.PointerProperty(
        name="Paint Texture",
        description="Image datablock updated from the paired Aseprite sprite",
        type=bpy.types.Image,
    )

    material_image: bpy.props.PointerProperty(
        name="Material ORME",
        description="Packed AO, Roughness, Metallic, and Emission texture generated from Aseprite channels",
        type=bpy.types.Image,
    )

    material_frame: bpy.props.IntProperty(default=0, options={'HIDDEN'})

    emission_strength: bpy.props.FloatProperty(
        name="Emission Strength",
        description="Brightness applied where the Aseprite Emission channel is white",
        default=2.0,
        min=0.0,
        max=100.0,
        update=_update_project_material,
    )

    apply_generated_normal: bpy.props.BoolProperty(
        name="Apply Generated World Normal",
        description="Use the generated world-space normal texture in the project shader",
        default=True,
        update=_update_apply_generated_normal,
    )

    detail_auto_rebuild: bpy.props.BoolProperty(
        name="Auto Rebuild",
        description="Downsample World Normal when a direct-normal stroke finishes",
        default=True,
    )

    detail_auto_send: bpy.props.BoolProperty(
        name="Auto Send to Aseprite",
        description="Send each generated World Normal to its read-only Aseprite output layer",
        default=True,
    )

    detail_brush_mode: bpy.props.EnumProperty(
        name="Brush",
        description="Operation performed on the editable world-normal source",
        items=(
            ('PAINT', "Paint Direction", "Blend pixels toward the selected world-normal direction"),
            ('SET', "Set Pixel", "Replace one selected pixel with the exact direction"),
            ('SMOOTH', "Smooth", "Average nearby world-normal directions"),
            ('BULGE', "Bulge", "Tilt normals outward to create a projected convex bump"),
            ('DENT', "Dent", "Tilt normals inward to create a projected concave dent"),
        ),
        default='PAINT',
    )

    detail_brush_radius: bpy.props.IntProperty(
        name="Radius",
        description="Brush radius in final texture pixels (Normal Edit uses two samples per pixel)",
        default=2,
        min=1,
        max=256,
    )

    detail_set_size: bpy.props.IntProperty(
        name="Size",
        description="Exact square Set area in output pixels or individual edit samples",
        default=1,
        min=1,
        max=256,
    )

    detail_smooth_radius: bpy.props.IntProperty(
        name="Radius",
        description="Smooth brush radius in final texture pixels",
        default=2,
        min=1,
        max=256,
    )

    detail_bulge_radius: bpy.props.IntProperty(
        name="Radius",
        description="Bulge brush radius in final texture pixels",
        default=4,
        min=1,
        max=256,
    )

    detail_dent_radius: bpy.props.IntProperty(
        name="Radius",
        description="Dent brush radius in final texture pixels",
        default=4,
        min=1,
        max=256,
    )

    detail_brush_strength: bpy.props.FloatProperty(
        name="Strength",
        description="Blend amount applied by one normal brush dab",
        default=0.35,
        min=0.0001,
        max=1.0,
        precision=4,
    )

    detail_normal_target: bpy.props.FloatVectorProperty(
        name="World Normal",
        description="Target world-space direction; it is normalized before painting",
        size=3,
        subtype='DIRECTION',
        default=(0.0, 0.0, 1.0),
        min=-1.0,
        max=1.0,
        precision=3,
    )

    detail_picker_mode: bpy.props.EnumProperty(
        name="Normal Picker",
        description="Choose arbitrary or angularly quantized world-normal directions",
        items=(
            ('CONTINUOUS', "Continuous", "Pick any camera-facing unit normal"),
            ('QUANTIZED', "Quantized", "Snap to a symmetric angular normal palette"),
        ),
        default='QUANTIZED',
    )

    detail_picker_divisions: bpy.props.IntProperty(
        name="Arc Divisions",
        description=(
            "Divide every 90 degree great-circle arc between signed global axes "
            "into this many equal angular steps"
        ),
        default=4,
        min=2,
        max=12,
    )

    detail_pixel_scope: bpy.props.EnumProperty(
        name="Pixel Size",
        description="Area replaced with the exact world-normal direction",
        items=(
            ('OUTPUT', "Output Pixel (2×2)", "Set all four editable samples behind one final pixel"),
            ('EDIT', "Edit Sample (1×1)", "Set one sample in the doubled-resolution source"),
        ),
        default='OUTPUT',
    )

    detail_preview_mode: bpy.props.EnumProperty(
        name="Preview",
        description="Switch between material, edited normals, and the original geometry-normal bake",
        items=(
            ('NORMAL_EDIT', "Edited", "Show the editable 2× encoded world-normal RGB without lighting"),
            (
                'FINAL_NORMAL',
                "Final",
                "Show the base-resolution World Normal actually used by the material",
            ),
            (
                'GEOMETRY_NORMAL',
                "Geometry",
                "Show the immutable base-resolution normal map generated from geometry",
            ),
            ('MATERIAL', "Material", "Show the regular lit project material"),
        ),
        default='MATERIAL',
        update=_update_detail_preview,
    )

    projection_padding: bpy.props.IntProperty(
        name="Canvas Padding",
        description="Transparent pixels kept around the maximum projected animation bounds",
        default=2,
        min=0,
        max=256,
    )

    projection_auto_grow: bpy.props.BoolProperty(
        name="Automatically Grow Canvas",
        description="Expand the shared Blender and Aseprite canvas when animation bounds grow",
        default=True,
    )

    projection_canvas_ready: bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    projection_bounds_dirty: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    projection_min_x: bpy.props.IntProperty(default=0, options={'HIDDEN'})
    projection_min_y: bpy.props.IntProperty(default=0, options={'HIDDEN'})
    projection_max_x: bpy.props.IntProperty(default=0, options={'HIDDEN'})
    projection_max_y: bpy.props.IntProperty(default=0, options={'HIDDEN'})


class SB_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    port: bpy.props.IntProperty(
        name="Port",
        description="Port used by the websocket server. Aseprite plugin must have the same value to connect",
        default=34613,
        min=1025,
        max=65535)

    localhost: bpy.props.BoolProperty(
        name="Only Local Connections",
        description="Only accept connections from localhost (127.0.0.1)",
        default=True)

    autostart: bpy.props.BoolProperty(
        name="Start Automatically",
        description="Set up the connection when Blender starts. Enabling increases blender's launch time",
        default=False)

    skip_modal: bpy.props.BoolProperty(
        name="No modal timers",
        description="Change the way the changes are applied to blender data. Degrades the experience but might fix some crashes",
        default=False)


    def template_box(self, layout, label="Box"):
        row = layout.row().split(factor=0.15)
        row.label(text=label)
        return row.box()


    def draw(self, context):
        layout = self.layout

        box = self.template_box(layout, label="Connection:")

        box.row().prop(self, "autostart")

        row = box.row()
        row.enabled = not addon.server_up
        row.prop(self, "localhost")
        row.prop(self, "port")

        if addon.server_up:
            box.row().operator("pribambase.stop_server")
        else:
            box.row().operator("pribambase.start_server")

        box = self.template_box(layout, label="Misc:")

        box.row().prop(self, "skip_modal")


class SB_OT_preferences(bpy.types.Operator):
    bl_idname = "pribambase.preferences"
    bl_label = "Preferences"
    bl_description = "Open this addon's settings"

    def execute(self, context):
        bpy.ops.preferences.addon_show(module=__package__)

        return {'FINISHED'}
