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
from .addon import addon
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
    bl_label = "Sync"
    bl_category = "Tool"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"


    def draw(self, context):
        layout = self.layout

        row = layout.row()
        status = "Off"
        icon = 'UNLINKED'
        if addon.connected:
            status = "Connected"
            icon = 'CHECKMARK'
        elif addon.server_up:
            status = "Waiting..."
            icon = 'SORTTIME'

        row.label(text=status, icon=icon)

        row = row.row()
        row.alignment = 'RIGHT'
        if addon.server_up:
            row.operator("pribambase.stop_server", text="Stop", icon="DECORATE_LIBRARY_OVERRIDE")
        else:
            row.operator("pribambase.start_server", text="Connect", icon="DECORATE_LINKED")
        row.operator("pribambase.preferences", icon='PREFERENCES', text="", emboss=False)
