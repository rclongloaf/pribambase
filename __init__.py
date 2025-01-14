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

# import wheel deps
import sys
import os.path as path
from glob import glob


import importlib
import pip

try:
    importlib.import_module('aiohttp')
except ImportError:
    pip.main(['install', 'aiohttp', '--target', (sys.exec_prefix) + '\lib\site-packages'])



thirdparty = path.join(path.dirname(__file__), "thirdparty", "*.whl")
sys.path += glob(thirdparty)


from bpy.app.handlers import persistent
from contextlib import contextmanager

from .async_loop import *
from .settings import *
from .sync import *
from .ui_2d import *
from .ui_3d import *
from .util import *
from .addon import addon


bl_info = {
    "name": "Pribambase",
    "author": "lampysprites",
    "description": "Paint pixelart textures in Blender using Aseprite",
    "blender": (2, 80, 0),
    "version": (2, 0, 2),
    "location": "\"Sync\" section in Tool settings; \"Sprite\" menu in UV/Image Editor",
    "category": "Paint"
}


classes = (
    SB_State,
    SB_Preferences,

    SB_OT_serv_start,
    SB_OT_serv_stop,
    SB_OT_config_offset,
    SB_OT_update_uv,
    SB_OT_update_camera,
    SB_OT_send_render,
    SB_OT_texture_list,
    SB_OT_open_sprite,
    SB_OT_new_sprite,
    SB_OT_edit_sprite,
    SB_OT_edit_sprite_copy,
    SB_OT_replace_sprite,
    SB_OT_update_image,

    SB_PT_panel_link,

    SB_MT_menu_2d,

    SB_OT_preferences,
    SB_OT_report
)


def register():
    async_loop.setup_asyncio_executor()

    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.Scene.sb_state = bpy.props.PointerProperty(type=SB_State)
    bpy.types.Image.sb_source = bpy.props.StringProperty(name="Sprite", subtype='FILE_PATH')
    bpy.types.Image.sb_scale = bpy.props.IntProperty(name="Scale", min=1, max=50, default=1)
    bpy.types.Image.sb_offset = bpy.props.IntVectorProperty(
        name="Offset",
        description="Offset of sprite center in pixels",
        size=2,
        default=(0, 0)
    )

    try:
        editor_menus = bpy.types.IMAGE_MT_editor_menus
    except AttributeError:
        editor_menus = bpy.types.MASK_MT_editor_menus
    editor_menus.append(SB_MT_menu_2d.header_draw)

    # delay is just in case something else happens at startup
    # `persistent` protects the timer if the user loads a file before it fires
    bpy.app.timers.register(start, first_interval=0.5, persistent=True)


def unregister():
    if addon.server_up:
        addon.stop_server()

    if bpy.app.timers.is_registered(start):
        bpy.app.timers.unregister(start)

    if sb_on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(sb_on_load_post)

    if sb_on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(sb_on_load_pre)

    if sb_on_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sb_on_depsgraph_update_post)

    try:
        editor_menus = bpy.types.IMAGE_MT_editor_menus
    except AttributeError:
        editor_menus = bpy.types.MASK_MT_editor_menus
    editor_menus.remove(SB_MT_menu_2d.header_draw)

    del bpy.types.Scene.sb_state
    del bpy.types.Image.sb_source
    del bpy.types.Image.sb_scale

    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)


# hash for the set of image sources/names that is used to check if new images were added
_images_hv = 0


@persistent
def start():
    global _images_hv
    _images_hv = hash(tuple(img.filepath for img in bpy.data.images))

    if addon.prefs.autostart:
        addon.start_server()

    if sb_on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(sb_on_load_post)

    if sb_on_load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(sb_on_load_pre)

    if sb_on_depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sb_on_depsgraph_update_post)


@persistent
def sb_on_load_post(scene):
    global _images_hv
    _images_hv = hash(frozenset(img.filepath for img in bpy.data.images))

    if addon.prefs.autostart:
        addon.start_server()


@persistent
def sb_on_load_pre(scene):
    if addon.server_up:
        addon.stop_server()


@persistent
def sb_on_depsgraph_update_post(scene):
    global _images_hv

    dg = bpy.context.evaluated_depsgraph_get()

    if dg.id_type_updated('IMAGE'):
        imgs = frozenset(util.image_name(img) for img in bpy.data.images)
        hv = hash(imgs)

        if _images_hv != hv:
            _images_hv = hv
            if addon.server_up:
                addon.server.send(encode.texture_list(imgs))


@contextmanager
def batch_depsgraph_updates():
    """disable depsgraph listener in the context"""
    assert sb_on_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post

    bpy.app.handlers.depsgraph_update_post.remove(sb_on_depsgraph_update_post)
    try:
        yield None
    finally:
        bpy.app.handlers.depsgraph_update_post.append(sb_on_depsgraph_update_post)