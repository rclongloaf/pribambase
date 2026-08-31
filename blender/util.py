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

"""Blender image and UI utility functions."""

import bpy
import imbuf
import os
from os import path
import tempfile
import numpy as np

from .addon import addon


def refresh():
    """Tag the ui for redrawing"""
    ctx = bpy.context
    if not ctx or not ctx.window_manager:
        return
    
    for win in ctx.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


class ModalExecuteMixin:
    """
    bpy.types.Operator mixin that makes operator execute once via modal timer, allowing to modify 
    blender state from non-operator code with fewer surprizes. Uses a non-modal fallback for older
    versions. To use, define modal_execute(self, ctx) method
    """

    def modal_execute(self, context):
        raise NotImplementedError()

    def modal(self, context, event):
        if event.type == 'TIMER':
            context.window_manager.event_timer_remove(self.timer)
            return self.modal_execute(context)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if context and context.window and not addon.prefs.skip_modal:
            context.window_manager.modal_handler_add(self)
            self.timer = context.window_manager.event_timer_add(0.000001, window=context.window)
            return {'RUNNING_MODAL'}
        else:
            return self.modal_execute(context)


def image_name(img):
    fp = img.filepath

    if img.sb_source:
        return bpy.path.abspath(img.sb_source) if img.sb_source.startswith("//") else img.sb_source

    elif not img.packed_file and fp:
        return bpy.path.abspath(fp) if fp.startswith("//") else fp

    return img.name


def new_packed_image(name, w, h):
    """Create a packed image with data that will be saved (unlike bpy.data.images.new that is cleaned when the file is opened)"""
    img = bpy.data.images.new(name, w, h, alpha=True)
    tmp = path.join(tempfile.gettempdir(), "__sb__delete_me.png")
    img.filepath = tmp
    img.save() # the file needs to exist for pack() to work
    img.pack()
    img.filepath=""
    img.use_fake_user = True
    os.remove(tmp)
    return img

def get_mirrored_pixels(image):
    pixels_in_row = image.size[0] * 4
    height = image.size[1]
    pixels = [0.0] * pixels_in_row * height

    for i, p in enumerate(image.pixels):
        row = (i // pixels_in_row)
        pixels[(height - 1 - row) * pixels_in_row + (i % pixels_in_row)] = p

    return bytearray((int(p * 255) for p in pixels))

def update_image(w, h, name, pixels):
    # aiohttp is advanced by Blender's own app timer, so this callback already
    # runs on Blender's main thread. Apply each message completely before the
    # receive loop processes the next one. Keep this as a direct data update,
    # not an Operator with bl_options={'UNDO'}, so external texture refreshes
    # do not insert steps into the artist's Blender undo history.
    _apply_image_update(w, h, name, np.array(pixels, copy=True))


def _apply_image_update(w, h, name, pixels):
    """Replace one Blender image with an owned RGBA byte buffer."""
    img = None

    for candidate in bpy.data.images:
        if image_name(candidate) == name:
            img = candidate
            break
    else:
        # Avoid accidentally reviving images deliberately removed by the user.
        return

    if not img.has_data:
        # Load some data first so Blender allows the generated image to be packed.
        ib = imbuf.new((w, h))
        tmp = path.join(tempfile.gettempdir(), "__sb__delete_me.png")
        try:
            try:
                imbuf.write(ib, filepath=tmp)
            except TypeError:
                # Blender versions before the keyword-only ImBuf API.
                imbuf.write(ib, tmp)
            img.filepath = tmp
            img.reload()
            img.pack()
            img.filepath = ""
            img.use_fake_user = True
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    elif img.size[0] != w or img.size[1] != h:
        img.scale(w, h)

    converted = np.float32(pixels) / 255.0
    # Aseprite and Blender store image rows in opposite directions.
    converted.shape = (h, converted.size // h)
    converted = converted[::-1, :].ravel()

    try:
        img.pixels.foreach_set(converted)
    except AttributeError:
        img.pixels[:] = converted

    img.update()
    img.update_tag()
    refresh()


class SB_OT_report(bpy.types.Operator, ModalExecuteMixin):
    bl_idname = "pribambase.report"
    bl_label = "Report"
    bl_description = "Report the message"
    bl_options = {'INTERNAL'}

    message_type: bpy.props.StringProperty(name="Message Type", default='INFO')
    message: bpy.props.StringProperty(name="Message", default='Someone forgot to change the message text')

    def modal_execute(self, context):
        self.report({self.message_type}, self.message)
        return {'FINISHED'}
