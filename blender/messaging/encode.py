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

"""Encode Blender-to-Aseprite protocol messages."""

from typing import Iterable, Sequence, Tuple
from . import *


def batch(messages:Sequence[bytearray]) -> bytearray:
    data = bytearray()
    add_id(data, '[')
    add_uint(data, len(messages), 2)

    for msg in messages:
        add_data(data, msg)

    return data


def texture_list(images:Iterable[str]) -> bytearray:
    data = bytearray()
    add_id(data, 'L')

    for img in images:
        add_string(data, img)

    return data


def uv_map(size:Tuple[int, int], sprite:str, pixels:bytes, opacity:int, layer:str) -> bytearray:
    data = bytearray()
    add_id(data, 'M')
    add_uint(data, opacity, 1)
    add_uint(data, size[0], 2)
    add_uint(data, size[1], 2)
    add_string(data, layer)
    add_string(data, sprite)
    add_data(data, pixels)
    return data


def sprite_open(name:str) -> bytearray:
    data = bytearray()
    add_id(data, 'O')
    add_string(data, name)
    return data


def sprite_focus(name:str) -> bytearray:
    data = bytearray()
    add_id(data, 'F')
    add_string(data, name)
    return data


def frame(number:int) -> bytearray:
    data = bytearray()
    add_id(data, 'A')
    add_uint(data, number, 4)
    return data


def guide_frame(number:int) -> bytearray:
    data = bytearray()
    add_id(data, 'G')
    add_uint(data, number, 4)
    return data


def workspace(asset:str, sprite:str) -> bytearray:
    data = bytearray()
    add_id(data, 'W')
    add_string(data, asset)
    add_string(data, sprite)
    return data


def canvas(size:Tuple[int, int], origin:Tuple[int, int], sprite:str) -> bytearray:
    data = bytearray()
    add_id(data, 'V')
    add_uint(data, size[0], 2)
    add_uint(data, size[1], 2)
    add_sint(data, origin[0], 4)
    add_sint(data, origin[1], 4)
    add_string(data, sprite)
    return data
