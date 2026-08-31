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

"""Handle incoming Aseprite-to-Blender protocol messages."""

import bpy
import asyncio
import re
import os
from typing import Tuple, Iterable
from os import path
from . import Handler
import numpy as np
# TODO move into local methods
from .. import util


async def wait_for_interface_unlock() -> None:
    """Keep inbound texture updates queued while a Blender job owns the UI."""
    try:
        while bpy.context.window_manager.is_interface_locked:
            await asyncio.sleep(0.05)
    except (AttributeError, ReferenceError):
        # Compatibility fallback for Blender versions without this state.
        return


class Batch(Handler):
    """Process batch messages"""
    id = "["

    def parse(self, args):
        count = self.take_uint(2)
        args.messages = [self.take_data() for _ in range(count)]


    async def execute(self, messages:Iterable[memoryview]):
        for m in messages:
            await self._handlers.process(m)


class Image(Handler):
    id = 'I'

    def parse(self, args):
        args.size = self.take_uint(2), self.take_uint(2)
        args.name = self.take_str()
        args.data = np.frombuffer(self.take_data(), dtype=np.ubyte)

    async def execute(self, *, size:Tuple[int, int], name:str, data:np.array):
        # Guide rendering can temporarily lock Blender immediately after a
        # channel toggle. Preserve the incoming texture instead of dropping it;
        # awaiting here also keeps successive off/on updates ordered.
        await wait_for_interface_unlock()
        # TODO separate cases for named and anonymous sprites
        util.update_image(size[0], size[1], name, data)


class NewImage(Image):
    """Same as image except it creates a named image if it doesn't exist"""
    id = 'N'

    async def execute(self, *, size:Tuple[int, int], name:str, data:np.array):
        _, short = path.split(name)
        img = util.new_packed_image(short, size[0], size[1])
        img.sb_source = name
        await super().execute(size=size, name=name, data=data)


class ChannelImage(Handler):
    """Receive an artist-authored packed material channel texture."""

    id = 'P'

    def parse(self, args):
        args.size = self.take_uint(2), self.take_uint(2)
        args.frame = self.take_uint(4)
        args.channel = self.take_str()
        args.source = self.take_str()
        args.data = np.frombuffer(self.take_data(), dtype=np.ubyte)

    async def execute(
        self,
        *,
        size: Tuple[int, int],
        frame: int,
        channel: str,
        source: str,
        data: np.array,
    ):
        if channel != "orme":
            print(f"Pribambase: unsupported material channel image {channel!r}")
            return

        from .. import projection, workspace
        scene = bpy.context.scene
        expected = workspace.resolved_sprite_path(scene)
        if expected:
            normalized_source = os.path.normcase(os.path.normpath(source))
            normalized_expected = os.path.normcase(os.path.normpath(expected))
            if (
                normalized_source != normalized_expected
                and os.path.basename(normalized_source) != os.path.basename(normalized_expected)
            ):
                return

        await wait_for_interface_unlock()
        image = projection.ensure_material_image(scene, size[0], size[1])
        util.update_image(size[0], size[1], image.name, data)
        scene.sb_state.material_frame = frame
        material = scene.sb_state.projection_material
        has_orme_node = (
            material is not None
            and material.use_nodes
            and any(
                node.get("pribambase_role") == "orme"
                for node in material.node_tree.nodes
            )
        )
        if scene.sb_state.projection_image is not None and not has_orme_node:
            material = projection.ensure_project_material(
                scene,
                scene.sb_state.projection_image,
            )
            projection.assign_project_material(scene, material)
        else:
            projection.update_project_material(scene)


class TextureList(Handler):
    """Send the list of available textures"""
    id = 'L'

    async def execute(self):
        bpy.ops.pribambase.texture_list()


class ChangeName(Handler):
    """Change textures' sources when aseprite saves the file under a new name"""
    id = 'C'

    def parse(self, args):
        args.old_name = self.take_str()
        args.new_name = self.take_str()


    async def execute(self, *, old_name, new_name):
        try:
            # FIXME there's a risk of race condition but it's pretty bad if the rename doesn't happen
            while bpy.context.window_manager.is_interface_locked:
                bpy.ops.pribambase.report(message_type='WARNING', message="UI is locked, waiting to update image source..")
                asyncio.sleep(0.1)
        except:
            # version 2.80... caveat emptor
            pass

        # avoid having identical sb_source on several images
        for img in bpy.data.images:
            if old_name in (img.sb_source, img.filepath, img.name):
                img.sb_source = new_name

                if re.search(r"\.(?:png|jpg|jpeg|bmp|tga)$", new_name):
                    img.filepath = new_name
                else:
                    img.filepath = ""

                bpy.ops.pribambase.texture_list()


class Frame(Handler):
    """Keep Blender's active animation frame aligned with Aseprite."""

    id = 'A'

    def parse(self, args):
        args.frame = self.take_uint(4)

    async def execute(self, *, frame):
        from ..workspace import apply_remote_frame

        apply_remote_frame(frame)
