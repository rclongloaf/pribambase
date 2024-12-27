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

import bpy
import numpy as np
from os import path

from .messaging import encode
from . import util
from .addon import addon
from .render import *
from .uvutils import *


COLOR_MODES = [
    ('rgba', "RGBA", "32-bit color with transparency. If not sure, pick this one"),
    ('indexed', "Indexed", "Palettized image with arbitrary palette"),
    ('gray', "Grayscale", "Palettized with 256 levels of gray")]

UV_DEST = [
    ('texture', "Texture Source", "Show UV map in the file of the image editor's texture"),
    ('active', "Active Sprite", "Show UV map in the currently open documet")
]

class SB_OT_config_offset(bpy.types.Operator):
    bl_idname = "pribambase.config_offset"
    bl_label = "Config sprite offset"
    bl_description = "Move center of sprite for uv and camera"

    offset: bpy.props.IntVectorProperty(
        name="Offset",
        description="Offset of sprite center in pixels",
        size=2,
        default=(0, 0)
    )

    @classmethod
    def poll(self, context):
        return context.object is not None and context.edit_image is not None

    def invoke(self, context, event):
        self.offset = context.edit_image.sb_offset
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        context.edit_image.sb_offset = self.offset
        bpy.ops.pribambase.update_uv()
        bpy.ops.pribambase.update_camera()
        return {"FINISHED"}

class SB_OT_update_uv(bpy.types.Operator):
    bl_idname = "pribambase.update_uv"
    bl_label = "Update UV"
    bl_description = "Update UV for mesh"

    @classmethod
    def poll(self, context):
        return context.object is not None and context.edit_image is not None

    def execute(self, context):
        w, h = context.edit_image.size
        if context.edit_object is not None:
            bpy.ops.object.editmode_toggle()

        offset_x, offset_y = context.edit_image.sb_offset

        setup_uv(context.object, w, h, offset_x, offset_y)
        bpy.ops.object.editmode_toggle()
        return {"FINISHED"}


class SB_OT_update_camera(bpy.types.Operator):
    bl_idname = "pribambase.update_camera"
    bl_label = "Update Camera"
    bl_description = "Update Camera settings"

    @classmethod
    def poll(self, context):
        return context.edit_image is not None

    def execute(self, context):
        w, h = context.edit_image.size

        offset_x, offset_y = context.edit_image.sb_offset

        setup_camera_config(context.scene.camera, w, h, offset_x, offset_y)
        setup_render_config(context.scene.render, context.scene.eevee, w, h)

        return {"FINISHED"}

class SB_OT_send_render(bpy.types.Operator):
    bl_idname = "pribambase.send_render"
    bl_label = "Send Render"
    bl_description = "Show Render in Aseprite"

    @classmethod
    def poll(self, context):
        return addon.connected and context.edit_image is not None

    def execute(self, context):
        source = ""

        image = get_render_image()
        width = image.size[0]
        height = image.size[1]
        buf = util.get_mirrored_pixels(image)

        # send data
        msg = encode.uv_map(
                size=(width, height),
                sprite=source,
                pixels=buf,
                layer=addon.prefs.uv_layer,
                opacity=int(addon.prefs.uv_color[3] * 255))
        if source:
            msg = encode.batch((encode.sprite_focus(source), msg))

        addon.server.send(msg)

        return {"FINISHED"}



class SB_OT_open_sprite(bpy.types.Operator):
    bl_idname = "pribambase.open_sprite"
    bl_label = "Open..."
    bl_description = "Set up a texture from a file using Aseprite"
    bl_options = {'REGISTER', 'UNDO'}


    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    # dialog settings
    filter_glob: bpy.props.StringProperty(default="*.ase;*.aseprite;.bmp;.flc;.fli;.gif;.ico;.jpeg;.jpg;.pcx;.pcc;.png;.tga;.webp", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})


    @classmethod
    def poll(self, context):
        return addon.connected


    def execute(self, context):
        source = bpy.path.abspath(self.filepath)
        _, name = path.split(source)
        img = None

        for i in bpy.data.images:
            # we might have this image opened already
            if i.sb_source == source:
                img = i
                break
        else:
            # create a stub that will be filled after receiving data
            img = util.new_packed_image(name, 1, 1)
            img.sb_source = source

        # switch to the image in the editor
        if context.area.type == 'IMAGE_EDITOR':
            context.area.spaces.active.image = img

        msg = encode.sprite_open(source)
        addon.server.send(msg)

        return {'FINISHED'}


    def invoke(self, context, event):
        self.invoke_context = context
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SB_OT_new_sprite(bpy.types.Operator):
    bl_idname = "pribambase.new_sprite"
    bl_label = "New"
    bl_description = "Set up a new texture using Aseprite"
    bl_options={'REGISTER', 'UNDO'}

    sprite: bpy.props.StringProperty(
        name="Name",
        description="Name of the texture. It will also be displayed on the tab in Aseprite until you save the file",
        default="Sprite")

    size: bpy.props.IntVectorProperty(
        name="Size",
        description="Size of the created canvas",
        default=(128, 128),
        size=2,
        min=1,
        max=65535)

    mode: bpy.props.EnumProperty(
        name="Color Mode",
        description="Color mode of the created sprite",
        items=COLOR_MODES,
        default='rgba')


    @classmethod
    def poll(self, context):
        return addon.connected


    def execute(self, context):
        if not self.sprite:
            self.report({'ERROR'}, "The sprite must have a name")
            return {'CANCELLED'}

        # create a stub that will be filled after receiving data
        img = util.new_packed_image(self.sprite, 1, 1)
        img.sb_source = img.name # can get an additional suffix, e.g. "Sprite.001"
        # switch to it in the editor
        if context.area.type == 'IMAGE_EDITOR':
            context.area.spaces.active.image = img

        mode = 0
        for i,m in enumerate(COLOR_MODES):
            if m[0] == self.mode:
                mode = i

        msg = encode.sprite_new(
            name=img.sb_source,
            size=self.size,
            mode=mode)

        addon.server.send(msg)

        return {'FINISHED'}


    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class SB_OT_edit_sprite(bpy.types.Operator):
    bl_idname = "pribambase.edit_sprite"
    bl_label = "Edit"
    bl_description = "Open the file for this texture with Aseprite"


    @classmethod
    def poll(self, context):
        return addon.connected and context.area.type == 'IMAGE_EDITOR' \
            and context.edit_image and context.edit_image.has_data


    def execute(self, context):
        img = context.edit_image
        edit_name = util.image_name(img)
        msg = None

        if path.exists(edit_name):
            msg = encode.sprite_open(name=edit_name)
        else:
            pixels = np.asarray(np.array(img.pixels) * 255, dtype=np.ubyte)
            pixels.shape = (img.size[1], pixels.size // img.size[1])
            pixels = np.ravel(pixels[::-1,:])

            msg = encode.image(
                name=img.name,
                size=img.size,
                pixels=pixels.tobytes())

        addon.server.send(msg)

        return {'FINISHED'}


class SB_OT_edit_sprite_copy(bpy.types.Operator):
    bl_idname = "pribambase.edit_sprite_copy"
    bl_label = "Edit Copy"
    bl_description = "Open copy of the image in a new file in Aseprite, without syncing"


    @classmethod
    def poll(self, context):
        return addon.connected and context.area.type == 'IMAGE_EDITOR' \
            and context.edit_image and context.edit_image.has_data


    def execute(self, context):
        img = context.edit_image

        pixels = np.asarray(np.array(img.pixels) * 255, dtype=np.ubyte)
        pixels.shape = (img.size[1], pixels.size // img.size[1])
        pixels = np.ravel(pixels[::-1,:])

        msg = encode.image(
            name="",
            size=img.size,
            pixels=pixels.tobytes())

        addon.server.send(msg)

        return {'FINISHED'}


class SB_OT_replace_sprite(bpy.types.Operator):
    bl_description = "Replace current texture with a file using Aseprite"
    bl_idname = "pribambase.replace_sprite"
    bl_label = "Replace..."
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    # dialog settings
    filter_glob: bpy.props.StringProperty(default="*.ase;*.aseprite;.bmp;.flc;.fli;.gif;.ico;.jpeg;.jpg;.pcx;.pcc;.png;.tga;.webp", options={'HIDDEN'})
    use_filter: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return addon.connected and context.area.type == 'IMAGE_EDITOR'

    def execute(self, context):
        source = bpy.path.abspath(self.filepath)
        context.edit_image.sb_source = source
        msg = encode.sprite_open(source)
        addon.server.send(msg)

        return {'FINISHED'}


    def invoke(self, context, event):
        self.invoke_context = context
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SB_MT_menu_2d(bpy.types.Menu):
    bl_label = "Sprite"
    bl_idname = "SB_MT_menu_2d"

    def draw(self, context):
        layout = self.layout

        layout.operator("pribambase.new_sprite", icon='FILE_NEW')
        layout.operator("pribambase.open_sprite", icon='FILE_FOLDER')
        layout.operator("pribambase.edit_sprite", icon='GREASEPENCIL')
        layout.operator("pribambase.edit_sprite_copy")
        layout.operator("pribambase.replace_sprite")
        layout.separator()
        layout.operator("pribambase.config_offset")
        layout.operator("pribambase.update_uv", icon='UV_VERTEXSEL')
        layout.operator("pribambase.update_camera")
        layout.operator("pribambase.send_render")


    def header_draw(self, context):
        # deceiptively, self is not the menu here but the header
        self.layout.menu("SB_MT_menu_2d")
