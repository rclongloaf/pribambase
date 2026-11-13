"""Viewport Normal Ball used by the direct world-normal painter."""

from __future__ import annotations

import math
import traceback
from functools import lru_cache

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import projection


BALL_RADIUS = 96.0
BALL_SEGMENTS = 48
BALL_RINGS = 12
MIN_DIVISIONS = 2
MAX_DIVISIONS = 12

RIGHT = Vector((1.0, 0.0, 0.0))
UP = Vector(
    (
        0.0,
        math.sin(projection.PROJECTION_ELEVATION),
        math.cos(projection.PROJECTION_ELEVATION),
    )
)
FRONT = Vector(
    (
        0.0,
        -math.cos(projection.PROJECTION_ELEVATION),
        math.sin(projection.PROJECTION_ELEVATION),
    )
)
VISIBLE_AXES = tuple(
    axis
    for axis in (
        Vector((1.0, 0.0, 0.0)),
        Vector((-1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, -1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
        Vector((0.0, 0.0, -1.0)),
    )
    if axis.dot(FRONT) >= -1e-6
)

_sessions: set["NormalPickerSession"] = set()


def normalized(value) -> Vector:
    vector = Vector(value)
    if vector.length_squared < 1e-12:
        return FRONT.copy()
    vector.normalize()
    return vector


def direction_from_disk(u: float, v: float) -> Vector:
    length_squared = u * u + v * v
    if length_squared > 1.0:
        scale = 1.0 / math.sqrt(length_squared)
        u *= scale
        v *= scale
        length_squared = 1.0
    depth = math.sqrt(max(0.0, 1.0 - length_squared))
    return normalized(RIGHT * u + UP * v + FRONT * depth)


def disk_from_direction(direction) -> tuple[float, float]:
    vector = normalized(direction)
    return vector.dot(RIGHT), vector.dot(UP)


def encoded_color(direction, alpha: float = 1.0) -> tuple[float, float, float, float]:
    vector = normalized(direction)
    return (
        vector.x * 0.5 + 0.5,
        vector.y * 0.5 + 0.5,
        vector.z * 0.5 + 0.5,
        alpha,
    )


@lru_cache(maxsize=MAX_DIVISIONS - MIN_DIVISIONS + 1)
def palette_directions(divisions: int) -> tuple[Vector, ...]:
    """Subdivide signed global-axis octants without ordered rotations.

    The sine-weighted symmetric coordinates make every octahedron edge an
    exact great-circle subdivision: N=2 gives 45°, N=3 gives 30°, and so on.
    Interior points use the same formula for X/Y/Z simultaneously, so their
    direction is independent of any Euler rotation order.
    """
    divisions = max(MIN_DIVISIONS, min(MAX_DIVISIONS, int(divisions)))
    unique: dict[tuple[float, float, float], Vector] = {}
    quarter_turn = math.pi / 2.0
    for sign_x in (-1.0, 1.0):
        for sign_y in (-1.0, 1.0):
            for sign_z in (-1.0, 1.0):
                axis_x = Vector((sign_x, 0.0, 0.0))
                axis_y = Vector((0.0, sign_y, 0.0))
                axis_z = Vector((0.0, 0.0, sign_z))
                for x_step in range(divisions + 1):
                    for y_step in range(divisions - x_step + 1):
                        z_step = divisions - x_step - y_step
                        direction = normalized(
                            axis_x * math.sin(quarter_turn * x_step / divisions)
                            + axis_y * math.sin(quarter_turn * y_step / divisions)
                            + axis_z * math.sin(quarter_turn * z_step / divisions)
                        )
                        if direction.dot(FRONT) < -1e-6:
                            continue
                        key = tuple(round(component, 7) for component in direction)
                        unique[key] = direction
    return tuple(
        sorted(
            unique.values(),
            key=lambda direction: (
                round(math.acos(max(-1.0, min(1.0, direction.dot(FRONT)))), 7),
                round(math.atan2(direction.dot(UP), direction.dot(RIGHT)), 7),
            ),
        )
    )


def quantize_direction(direction, divisions: int) -> Vector:
    vector = normalized(direction)
    return max(palette_directions(divisions), key=vector.dot).copy()


def snap_to_axis(direction) -> Vector:
    vector = normalized(direction)
    return max(VISIBLE_AXES, key=vector.dot).copy()


def _window_region(context):
    return next(
        (region for region in context.area.regions if region.type == 'WINDOW'),
        None,
    )


def _draw_polyline(points, color, width: float = 1.0, *, cyclic: bool = False) -> None:
    if cyclic and points:
        points = [*points, points[0]]
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    shader.uniform_float("color", color)
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    batch_for_shader(shader, 'LINE_STRIP', {"pos": points}).draw(shader)


def _draw_points(points, colors, size: float) -> None:
    if not points:
        return
    gpu.state.point_size_set(size)
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch_for_shader(shader, 'POINTS', {"pos": points, "color": colors}).draw(shader)


def _draw_text(x: float, y: float, text: str, color=(1.0, 1.0, 1.0, 1.0)) -> None:
    font_id = 0
    blf.position(font_id, x, y, 0)
    blf.size(font_id, 12.0)
    blf.color(font_id, *color)
    blf.draw(font_id, text)


class NormalPickerSession:
    def __init__(self, context, event):
        region = _window_region(context)
        if region is None:
            raise RuntimeError("Normal Picker requires a 3D Viewport window region")
        self.area = context.area
        self.region = region
        self.state = context.scene.sb_state
        local_x = event.mouse_x - region.x
        local_y = event.mouse_y - region.y
        if not (0 <= local_x < region.width and 0 <= local_y < region.height):
            local_x = region.width / 2.0
            local_y = region.height / 2.0
        margin = BALL_RADIUS + 12.0
        self.anchor = (
            min(max(local_x, margin), max(margin, region.width - margin)),
            min(max(local_y, margin + 42.0), max(margin + 42.0, region.height - margin)),
        )
        self.selected = normalized(self.state.detail_normal_target)
        self.current_normal: Vector | None = None
        self.hit_location: Vector | None = None
        self.last_uv = disk_from_direction(self.selected)
        self._handle_pixel = bpy.types.SpaceView3D.draw_handler_add(
            _draw_picker_pixel,
            (self,),
            'WINDOW',
            'POST_PIXEL',
        )
        self._handle_world = bpy.types.SpaceView3D.draw_handler_add(
            _draw_picker_world,
            (self,),
            'WINDOW',
            'POST_VIEW',
        )
        self.active = True
        _sessions.add(self)
        context.area.tag_redraw()

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        if self._handle_pixel is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_pixel, 'WINDOW')
            self._handle_pixel = None
        if self._handle_world is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle_world, 'WINDOW')
            self._handle_world = None
        _sessions.discard(self)
        try:
            self.area.tag_redraw()
        except ReferenceError:
            pass

    def update_world(self, location, current_normal) -> None:
        self.hit_location = Vector(location) if location is not None else None
        self.current_normal = (
            normalized(current_normal)
            if current_normal is not None
            else None
        )

    def _select(self, context, event) -> None:
        local_x = event.mouse_x - self.region.x
        local_y = event.mouse_y - self.region.y
        u = (local_x - self.anchor[0]) / BALL_RADIUS
        v = (local_y - self.anchor[1]) / BALL_RADIUS
        length = math.hypot(u, v)
        if length > 1.0:
            u /= length
            v /= length
        self.last_uv = (u, v)
        direction = direction_from_disk(u, v)
        if event.ctrl:
            direction = snap_to_axis(direction)
        elif self.state.detail_picker_mode == 'QUANTIZED':
            direction = quantize_direction(direction, self.state.detail_picker_divisions)
        self.selected = direction
        context.area.tag_redraw()

    def _reselect(self, context, event) -> None:
        proxy = type(
            "PickerEvent",
            (),
            {
                "mouse_x": self.region.x + self.anchor[0] + self.last_uv[0] * BALL_RADIUS,
                "mouse_y": self.region.y + self.anchor[1] + self.last_uv[1] * BALL_RADIUS,
                "ctrl": event.ctrl,
            },
        )()
        self._select(context, proxy)

    def handle_event(self, context, event) -> str:
        if event.type == 'MOUSEMOVE':
            self._select(context, event)
            return 'RUNNING'
        if event.value == 'PRESS' and event.type == 'Q':
            self.state.detail_picker_mode = (
                'CONTINUOUS'
                if self.state.detail_picker_mode == 'QUANTIZED'
                else 'QUANTIZED'
            )
            self._reselect(context, event)
            return 'RUNNING'
        if event.value == 'PRESS' and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            change = 1 if event.type == 'WHEELUPMOUSE' else -1
            self.state.detail_picker_divisions = max(
                MIN_DIVISIONS,
                min(MAX_DIVISIONS, self.state.detail_picker_divisions + change),
            )
            self.state.detail_picker_mode = 'QUANTIZED'
            self._reselect(context, event)
            return 'RUNNING'
        if event.type in {'LEFT_CTRL', 'RIGHT_CTRL'}:
            self._reselect(context, event)
            return 'RUNNING'
        if event.value == 'PRESS' and event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'N'}:
            if event.type == 'LEFTMOUSE':
                self._select(context, event)
            self.state.detail_normal_target = tuple(self.selected)
            self.stop()
            return 'CONFIRM'
        if event.value == 'PRESS' and event.type in {'RIGHTMOUSE', 'ESC'}:
            self.stop()
            return 'CANCEL'
        return 'RUNNING'


def _draw_picker_pixel(session: NormalPickerSession) -> None:
    if not session.active or bpy.context.area != session.area:
        return
    try:
        gpu.state.blend_set('ALPHA')
        center_x, center_y = session.anchor
        positions = [(center_x, center_y)]
        colors = [encoded_color(FRONT, 0.96)]
        for ring in range(1, BALL_RINGS + 1):
            disk_radius = ring / BALL_RINGS
            for index in range(BALL_SEGMENTS):
                angle = math.tau * index / BALL_SEGMENTS
                u = disk_radius * math.cos(angle)
                v = disk_radius * math.sin(angle)
                positions.append(
                    (center_x + u * BALL_RADIUS, center_y + v * BALL_RADIUS)
                )
                colors.append(encoded_color(direction_from_disk(u, v), 0.96))
        indices = []
        first_ring = 1
        for index in range(BALL_SEGMENTS):
            indices.append(
                (0, first_ring + index, first_ring + (index + 1) % BALL_SEGMENTS)
            )
        for ring in range(1, BALL_RINGS):
            inner = 1 + (ring - 1) * BALL_SEGMENTS
            outer = 1 + ring * BALL_SEGMENTS
            for index in range(BALL_SEGMENTS):
                next_index = (index + 1) % BALL_SEGMENTS
                indices.extend(
                    (
                        (inner + index, outer + index, outer + next_index),
                        (inner + index, outer + next_index, inner + next_index),
                    )
                )
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        batch_for_shader(
            shader,
            'TRIS',
            {"pos": positions, "color": colors},
            indices=indices,
        ).draw(shader)

        outline = [
            (
                center_x + math.cos(math.tau * index / BALL_SEGMENTS) * BALL_RADIUS,
                center_y + math.sin(math.tau * index / BALL_SEGMENTS) * BALL_RADIUS,
            )
            for index in range(BALL_SEGMENTS)
        ]
        _draw_polyline(outline, (1.0, 1.0, 1.0, 0.8), 2.0, cyclic=True)

        for axis, color, label in (
            (Vector((1.0, 0.0, 0.0)), (1.0, 0.15, 0.15, 0.9), "+X"),
            (Vector((-1.0, 0.0, 0.0)), (0.75, 0.08, 0.08, 0.9), "-X"),
            (Vector((0.0, -1.0, 0.0)), (0.2, 1.0, 0.2, 0.9), "-Y"),
            (Vector((0.0, 0.0, 1.0)), (0.25, 0.5, 1.0, 0.9), "+Z"),
        ):
            u, v = disk_from_direction(axis)
            endpoint = (
                center_x + u * BALL_RADIUS * 0.86,
                center_y + v * BALL_RADIUS * 0.86,
            )
            _draw_polyline([(center_x, center_y), endpoint], color, 1.5)
            _draw_text(endpoint[0] + 3, endpoint[1] + 3, label, color)

        if session.state.detail_picker_mode == 'QUANTIZED':
            palette = palette_directions(session.state.detail_picker_divisions)
            palette_points = []
            palette_colors = []
            for direction in palette:
                u, v = disk_from_direction(direction)
                palette_points.append(
                    (center_x + u * BALL_RADIUS, center_y + v * BALL_RADIUS)
                )
                palette_colors.append(encoded_color(direction))
            _draw_points(palette_points, [(0.0, 0.0, 0.0, 0.9)] * len(palette_points), 10.0)
            _draw_points(palette_points, palette_colors, 6.0)

        selected_u, selected_v = disk_from_direction(session.selected)
        selected_point = (
            center_x + selected_u * BALL_RADIUS,
            center_y + selected_v * BALL_RADIUS,
        )
        selected_color = encoded_color(session.selected)
        _draw_polyline(
            [(center_x, center_y), selected_point],
            selected_color,
            3.0,
        )
        _draw_points([selected_point], [(0.0, 0.0, 0.0, 1.0)], 14.0)
        _draw_points([selected_point], [selected_color], 9.0)

        mode = session.state.detail_picker_mode.title()
        if session.state.detail_picker_mode == 'QUANTIZED':
            divisions = session.state.detail_picker_divisions
            mode += (
                f" · 1/{divisions} · {90.0 / divisions:g}°"
                f" · {len(palette_directions(divisions))} dirs"
            )
        vector = session.selected
        rgb = tuple(round(channel * 255) for channel in encoded_color(vector)[:3])
        _draw_text(
            center_x - BALL_RADIUS,
            center_y - BALL_RADIUS - 22,
            f"{mode} · Q mode · Wheel divisions · Ctrl axes",
        )
        _draw_text(
            center_x - BALL_RADIUS,
            center_y - BALL_RADIUS - 40,
            f"XYZ {vector.x:+.3f} {vector.y:+.3f} {vector.z:+.3f} · RGB {rgb[0]} {rgb[1]} {rgb[2]}",
        )
    except Exception:
        traceback.print_exc()
    finally:
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set('NONE')


def _draw_picker_world(session: NormalPickerSession) -> None:
    if (
        not session.active
        or bpy.context.area != session.area
        or session.hit_location is None
    ):
        return
    try:
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.line_width_set(3.0)
        origin = session.hit_location
        length = 5.0 / projection.PIXELS_PER_UNIT
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        if session.current_normal is not None:
            current_end = origin + session.current_normal * length
            shader.uniform_float("color", encoded_color(session.current_normal, 0.38))
            batch_for_shader(shader, 'LINES', {"pos": (origin, current_end)}).draw(shader)
        selected_end = origin + session.selected * length
        shader.uniform_float("color", encoded_color(session.selected, 1.0))
        batch_for_shader(shader, 'LINES', {"pos": (origin, selected_end)}).draw(shader)
        gpu.state.point_size_set(7.0)
        batch_for_shader(shader, 'POINTS', {"pos": (selected_end,)}).draw(shader)
    except Exception:
        traceback.print_exc()
    finally:
        gpu.state.point_size_set(1.0)
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def stop_all() -> None:
    for session in tuple(_sessions):
        session.stop()
