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

"""Pribambase add-on entry point for Blender."""

# import wheel deps
import sys
import os.path as path
from glob import glob

import os
import site

# 1. Добавляем ВСЕ возможные пути в САМОМ НАЧАЛЕ
addon_dir = os.path.dirname(__file__)

# Путь для vendor (если он есть и полный)
vendor_path = os.path.join(addon_dir, "vendor")


# Проверяем, есть ли ВСЕ зависимости в vendor
def check_vendor_complete():
    """Проверяет, что vendor содержит все необходимые пакеты"""
    if not os.path.exists(vendor_path):
        return False

    required_packages = ["aiohttp", "multidict", "yarl", "attrs", "frozenlist", "async_timeout"]
    for pkg in required_packages:
        pkg_path = os.path.join(vendor_path, pkg)
        if not os.path.exists(pkg_path):
            print(f"В vendor отсутствует: {pkg}")
            return False

    return True


# Только если vendor полный - добавляем его
if check_vendor_complete():
    sys.path.insert(0, vendor_path)
    print(f"✓ Использую зависимости из vendor: {vendor_path}")
else:
    print("✗ Vendor неполный или отсутствует, проверяю пользовательские пути...")

# 2. Добавляем путь к AppData (даже если он пустой сейчас)
try:
    user_site = site.getusersitepackages()
    if os.path.exists(user_site):
        if user_site not in sys.path:
            sys.path.append(user_site)
        print(f"✓ Добавлен пользовательский путь: {user_site}")

        # Проверяем, что там есть
        import os

        items = os.listdir(user_site) if os.path.exists(user_site) else []
        print(f"  Содержимое: {items}")
except Exception as e:
    print(f"Не удалось получить user_site: {e}")


# 3. Функция для установки зависимостей ДО импорта
def install_dependencies():
    """Устанавливает все необходимые зависимости"""
    print("\n" + "=" * 60)
    print("Pribambase: установка зависимостей...")

    try:
        import subprocess
        import sys

        # Устанавливаем aiohttp со всеми зависимостями
        result = subprocess.run([
            sys.executable, "-m", "pip", "install",
            "aiohttp>=3.8.0",
            "--user",
            "--quiet"
        ], capture_output=True, text=True)

        if result.returncode == 0:
            print("✓ Зависимости успешно установлены!")

            # Обновляем путь после установки
            try:
                user_site = site.getusersitepackages()
                if user_site not in sys.path:
                    sys.path.append(user_site)
            except:
                pass

            return True
        else:
            print(f"✗ Ошибка установки: {result.stderr}")
            return False

    except Exception as e:
        print(f"✗ Не удалось запустить pip: {e}")
        return False


# 4. Пытаемся импортировать aiohash СРАЗУ
try:
    import aiohttp

    print(f"✓ aiohttp найден: {aiohttp.__file__}")
    aiohttp_available = True
except ImportError as e:
    print(f"✗ aiohttp не найден: {e}")
    aiohttp_available = False

# 5. Если aiohttp не найден - пытаемся установить
if not aiohttp_available:
    if install_dependencies():
        # Пробуем снова импортировать после установки
        try:
            import aiohttp

            print(f"✓ aiohttp загружен после установки: {aiohttp.__file__}")
            aiohttp_available = True
        except ImportError:
            aiohttp_available = False
    else:
        print("\n" + "=" * 60)
        print("НЕ УДАЛОСЬ УСТАНОВИТЬ ЗАВИСИМОСТИ")
        print("Установите вручную:")
        print("1. Откройте командную строку (Win+R -> cmd)")
        print("2. Выполните: python -m pip install aiohttp --user")
        print("3. Перезапустите Blender")
        print("=" * 60)

# 6. Если aiohttp так и не доступен - не загружаем аддон
if not aiohttp_available:
    raise ModuleNotFoundError(
        "Pribambase cannot be loaded because the aiohttp dependency is unavailable."
    )

# 7. Только если aiohttp доступен - продолжаем загрузку аддона
print("=" * 60)
print("Pribambase: все зависимости загружены")
print("=" * 60)


from bpy.app.handlers import persistent
from contextlib import contextmanager

from .async_loop import *
from .settings import *
from .sync import *
from .ui_3d import *
from . import projection
from . import workspace
from .workspace import *
from .util import *
from .addon import addon


bl_info = {
    "name": "Pribambase",
    "author": "lampysprites",
    "description": "Paint pixelart textures in Blender using Aseprite",
    "blender": (4, 0, 0),
    "version": (2, 3, 0),
    "location": "\"Pribambase\" panel in the 3D Viewport sidebar",
    "category": "Paint"
}


classes = (
    SB_State,
    SB_Preferences,

    SB_OT_serv_start,
    SB_OT_serv_stop,
    SB_OT_sync_start,
    SB_OT_sync_stop,
    SB_OT_pair_save,
    SB_OT_pair_load,
    SB_OT_pair_open_sprite,
    SB_OT_projection_current,
    SB_OT_projection_dirty,
    SB_OT_projection_recalculate,
    SB_OT_projection_restore_camera,
    SB_OT_projection_setup_material,
    SB_OT_texture_list,
    SB_PT_panel_link,

    SB_OT_preferences,
    SB_OT_report
)


def register():
    async_loop.setup_asyncio_executor()

    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.Scene.sb_state = bpy.props.PointerProperty(type=SB_State)
    bpy.types.Image.sb_source = bpy.props.StringProperty(
        name="Sprite",
        subtype='FILE_PATH',
        options={'PATH_SUPPORTS_BLEND_RELATIVE'},
    )

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

    if sb_on_frame_change_post in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(sb_on_frame_change_post)

    if sb_on_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(sb_on_save_post)

    workspace.reset_runtime()

    del bpy.types.Scene.sb_state
    del bpy.types.Image.sb_source

    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)


# hash for the set of image sources/names that is used to check if new images were added
_images_hv = 0


def repair_project_material():
    try:
        projection.update_project_material(bpy.context.scene)
    except Exception as error:
        print(f"Pribambase: could not upgrade project material: {error}")


@persistent
def start():
    global _images_hv
    _images_hv = hash(tuple(img.filepath for img in bpy.data.images))
    repair_project_material()

    if addon.prefs.autostart:
        addon.start_server()

    if sb_on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(sb_on_load_post)

    if sb_on_load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(sb_on_load_pre)

    if sb_on_depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sb_on_depsgraph_update_post)

    if sb_on_frame_change_post not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(sb_on_frame_change_post)

    if sb_on_save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(sb_on_save_post)


@persistent
def sb_on_load_post(scene):
    global _images_hv
    workspace.reset_runtime()
    _images_hv = hash(frozenset(img.filepath for img in bpy.data.images))
    repair_project_material()

    if addon.prefs.autostart:
        addon.start_server()


@persistent
def sb_on_load_pre(scene):
    if addon.server_up:
        addon.stop_server()
    workspace.reset_runtime()


@persistent
def sb_on_depsgraph_update_post(scene):
    global _images_hv

    dg = bpy.context.evaluated_depsgraph_get()
    workspace.on_depsgraph_update(scene, dg)

    if dg.id_type_updated('IMAGE'):
        imgs = frozenset(util.image_name(img) for img in bpy.data.images)
        hv = hash(imgs)

        if _images_hv != hv:
            _images_hv = hv
            if addon.server_up:
                addon.server.send(encode.texture_list(imgs))


@persistent
def sb_on_frame_change_post(scene, depsgraph=None):
    workspace.on_frame_change(scene)


@persistent
def sb_on_save_post(filepath):
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        workspace.on_save(scene)


@contextmanager
def batch_depsgraph_updates():
    """disable depsgraph listener in the context"""
    assert sb_on_depsgraph_update_post in bpy.app.handlers.depsgraph_update_post

    bpy.app.handlers.depsgraph_update_post.remove(sb_on_depsgraph_update_post)
    try:
        yield None
    finally:
        bpy.app.handlers.depsgraph_update_post.append(sb_on_depsgraph_update_post)
