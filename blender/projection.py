"""Canonical world-space projection, animation canvas, camera, and material setup."""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass

import bpy
import numpy as np
from mathutils import Vector


PROFILE_NAME = "global_iso_v1"
PIXELS_PER_UNIT = 20.0
PROJECTION_ELEVATION = math.radians(30.0)
CAMERA_ROTATION_X = math.radians(60.0)
CAMERA_DISTANCE = 20.0
PROJECTION_GROUP_NAME = "PB_GlobalProjection_v1"
MASTER_GROUP_NAME = "PB_MasterShader_v3"
MASTER_GROUP_SCHEMA = 3
PROJECT_MATERIAL_SCHEMA = 3
PIXEL_FILTER_SIZE = 0.01

_scanning = False


@dataclass(frozen=True)
class Layout:
    min_x: int
    min_y: int
    max_x: int
    max_y: int

    @property
    def width(self) -> int:
        return self.max_x - self.min_x

    @property
    def height(self) -> int:
        return self.max_y - self.min_y

    @property
    def origin_x(self) -> int:
        return -self.min_x

    @property
    def origin_y(self) -> int:
        return -self.min_y

    def union(self, other: "Layout") -> "Layout":
        return Layout(
            min(self.min_x, other.min_x),
            min(self.min_y, other.min_y),
            max(self.max_x, other.max_x),
            max(self.max_y, other.max_y),
        )


def is_scanning() -> bool:
    return _scanning


def state_layout(scene: bpy.types.Scene) -> Layout | None:
    state = scene.sb_state
    if not state.projection_canvas_ready:
        return None
    layout = Layout(
        state.projection_min_x,
        state.projection_min_y,
        state.projection_max_x,
        state.projection_max_y,
    )
    return layout if layout.width > 0 and layout.height > 0 else None


def set_state_layout(scene: bpy.types.Scene, layout: Layout) -> None:
    state = scene.sb_state
    state.projection_min_x = layout.min_x
    state.projection_min_y = layout.min_y
    state.projection_max_x = layout.max_x
    state.projection_max_y = layout.max_y
    state.projection_canvas_ready = True
    state.projection_bounds_dirty = False


def projection_collection(scene: bpy.types.Scene) -> bpy.types.Collection:
    return scene.sb_state.projection_collection or scene.collection


def projection_objects(scene: bpy.types.Scene) -> tuple[bpy.types.Object, ...]:
    collection = projection_collection(scene)
    return tuple(
        obj
        for obj in collection.all_objects
        if obj.type == 'MESH' and not obj.hide_render
    )


def project_world_point(point: Vector) -> tuple[float, float]:
    return (
        point.x * PIXELS_PER_UNIT,
        (
            point.y * math.sin(PROJECTION_ELEVATION)
            + point.z * math.cos(PROJECTION_ELEVATION)
        )
        * PIXELS_PER_UNIT,
    )


def calculate_animation_layout(scene: bpy.types.Scene) -> Layout:
    global _scanning
    objects = projection_objects(scene)
    if not objects:
        raise RuntimeError("Projection collection does not contain renderable mesh objects")

    original_frame = scene.frame_current
    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    _scanning = True
    try:
        for frame in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            for obj in objects:
                evaluated = obj.evaluated_get(depsgraph)
                mesh = evaluated.to_mesh()
                try:
                    matrix = evaluated.matrix_world
                    for vertex in mesh.vertices:
                        x, y = project_world_point(matrix @ vertex.co)
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        max_x = max(max_x, x)
                        max_y = max(max_y, y)
                finally:
                    evaluated.to_mesh_clear()
    finally:
        if scene.frame_current != original_frame:
            scene.frame_set(original_frame)
        _scanning = False

    if not math.isfinite(min_x):
        raise RuntimeError("Could not evaluate projection bounds")

    padding = scene.sb_state.projection_padding
    # World zero is the stable pivot and must remain inside the shared canvas.
    min_x = min(min_x, 0.0)
    min_y = min(min_y, 0.0)
    max_x = max(max_x, 0.0)
    max_y = max(max_y, 0.0)
    return Layout(
        math.floor(min_x - padding),
        math.floor(min_y - padding),
        math.ceil(max_x + padding),
        math.ceil(max_y + padding),
    )


def centered_layout(width: int, height: int) -> Layout:
    min_x = -(width // 2)
    min_y = -(height // 2)
    return Layout(min_x, min_y, min_x + width, min_y + height)


def resize_image_canvas(
    image: bpy.types.Image,
    old_layout: Layout,
    new_layout: Layout,
    fill_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> None:
    if tuple(image.size) == (new_layout.width, new_layout.height):
        return
    if not image.has_data:
        image.scale(new_layout.width, new_layout.height)
        return

    old_width, old_height = image.size
    pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(old_height, old_width, 4)
    canvas = np.empty((new_layout.height, new_layout.width, 4), dtype=np.float32)
    canvas[:] = fill_color
    shift_x = new_layout.origin_x - old_layout.origin_x
    shift_y = new_layout.origin_y - old_layout.origin_y

    source_x = max(0, -shift_x)
    source_y = max(0, -shift_y)
    target_x = max(0, shift_x)
    target_y = max(0, shift_y)
    copy_width = min(old_width - source_x, new_layout.width - target_x)
    copy_height = min(old_height - source_y, new_layout.height - target_y)
    if copy_width > 0 and copy_height > 0:
        canvas[
            target_y : target_y + copy_height,
            target_x : target_x + copy_width,
        ] = pixels[
            source_y : source_y + copy_height,
            source_x : source_x + copy_width,
        ]

    image.scale(new_layout.width, new_layout.height)
    image.pixels.foreach_set(canvas.ravel())
    image.update()


def _new_group_socket(tree, name: str, in_out: str, socket_type: str):
    return tree.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)


def ensure_projection_group() -> bpy.types.ShaderNodeTree:
    existing = bpy.data.node_groups.get(PROJECTION_GROUP_NAME)
    if existing is not None:
        return existing

    tree = bpy.data.node_groups.new(PROJECTION_GROUP_NAME, 'ShaderNodeTree')
    for name in ("Canvas Min X", "Canvas Min Y", "Canvas Width", "Canvas Height"):
        socket = _new_group_socket(tree, name, 'INPUT', 'NodeSocketFloat')
        socket.default_value = 1.0 if name in {"Canvas Width", "Canvas Height"} else 0.0
    _new_group_socket(tree, "Vector", 'OUTPUT', 'NodeSocketVector')

    nodes = tree.nodes
    links = tree.links
    group_input = nodes.new('NodeGroupInput')
    group_output = nodes.new('NodeGroupOutput')
    geometry = nodes.new('ShaderNodeNewGeometry')
    separate = nodes.new('ShaderNodeSeparateXYZ')
    x_scale = nodes.new('ShaderNodeMath')
    x_scale.operation = 'MULTIPLY'
    x_scale.inputs[1].default_value = PIXELS_PER_UNIT
    x_offset = nodes.new('ShaderNodeMath')
    x_offset.operation = 'SUBTRACT'
    x_normalize = nodes.new('ShaderNodeMath')
    x_normalize.operation = 'DIVIDE'

    y_scale = nodes.new('ShaderNodeMath')
    y_scale.operation = 'MULTIPLY'
    y_scale.inputs[1].default_value = PIXELS_PER_UNIT * math.sin(PROJECTION_ELEVATION)
    z_scale = nodes.new('ShaderNodeMath')
    z_scale.operation = 'MULTIPLY'
    z_scale.inputs[1].default_value = PIXELS_PER_UNIT * math.cos(PROJECTION_ELEVATION)
    projected_y = nodes.new('ShaderNodeMath')
    projected_y.operation = 'ADD'
    y_offset = nodes.new('ShaderNodeMath')
    y_offset.operation = 'SUBTRACT'
    y_normalize = nodes.new('ShaderNodeMath')
    y_normalize.operation = 'DIVIDE'
    combine = nodes.new('ShaderNodeCombineXYZ')

    links.new(geometry.outputs['Position'], separate.inputs['Vector'])
    links.new(separate.outputs['X'], x_scale.inputs[0])
    links.new(x_scale.outputs[0], x_offset.inputs[0])
    links.new(group_input.outputs['Canvas Min X'], x_offset.inputs[1])
    links.new(x_offset.outputs[0], x_normalize.inputs[0])
    links.new(group_input.outputs['Canvas Width'], x_normalize.inputs[1])
    links.new(x_normalize.outputs[0], combine.inputs['X'])

    links.new(separate.outputs['Y'], y_scale.inputs[0])
    links.new(separate.outputs['Z'], z_scale.inputs[0])
    links.new(y_scale.outputs[0], projected_y.inputs[0])
    links.new(z_scale.outputs[0], projected_y.inputs[1])
    links.new(projected_y.outputs[0], y_offset.inputs[0])
    links.new(group_input.outputs['Canvas Min Y'], y_offset.inputs[1])
    links.new(y_offset.outputs[0], y_normalize.inputs[0])
    links.new(group_input.outputs['Canvas Height'], y_normalize.inputs[1])
    links.new(y_normalize.outputs[0], combine.inputs['Y'])
    links.new(combine.outputs['Vector'], group_output.inputs['Vector'])
    tree["pribambase_profile"] = PROFILE_NAME
    return tree


def ensure_master_group() -> bpy.types.ShaderNodeTree:
    existing = bpy.data.node_groups.get(MASTER_GROUP_NAME)
    if existing is not None and existing.get("pribambase_material_schema") == MASTER_GROUP_SCHEMA:
        return existing

    if existing is not None:
        bpy.data.node_groups.remove(existing)

    tree = bpy.data.node_groups.new(MASTER_GROUP_NAME, 'ShaderNodeTree')
    color = _new_group_socket(tree, "Base Color", 'INPUT', 'NodeSocketColor')
    color.default_value = (0.8, 0.8, 0.8, 1.0)
    ao = _new_group_socket(tree, "Ambient Occlusion", 'INPUT', 'NodeSocketFloat')
    ao.default_value = 1.0
    roughness = _new_group_socket(tree, "Roughness", 'INPUT', 'NodeSocketFloat')
    roughness.default_value = 0.5
    metallic = _new_group_socket(tree, "Metallic", 'INPUT', 'NodeSocketFloat')
    metallic.default_value = 0.0
    emission = _new_group_socket(tree, "Emission Mask", 'INPUT', 'NodeSocketFloat')
    emission.default_value = 0.0
    emission_strength = _new_group_socket(tree, "Emission Strength", 'INPUT', 'NodeSocketFloat')
    emission_strength.default_value = 2.0
    _new_group_socket(tree, "EEVEE Shader", 'OUTPUT', 'NodeSocketShader')
    _new_group_socket(tree, "Cycles Shader", 'OUTPUT', 'NodeSocketShader')

    nodes = tree.nodes
    links = tree.links
    group_input = nodes.new('NodeGroupInput')
    group_output = nodes.new('NodeGroupOutput')

    # EEVEE has no material AO input in Blender 5.2. Evaluate the regular PBR
    # shader first, then weight the painted AO by the resulting light level.
    # Dark areas receive almost no extra darkening, while lit non-metals show
    # the painted cavity information. Emission is added afterwards and stays
    # completely independent from AO.
    eevee_pbr = nodes.new('ShaderNodeBsdfPrincipled')
    eevee_pbr["pribambase_role"] = "eevee-pbr-lighting"
    shader_to_rgb = nodes.new('ShaderNodeShaderToRGB')
    shader_to_rgb["pribambase_role"] = "eevee-lighting-color"
    luminance = nodes.new('ShaderNodeRGBToBW')
    luminance["pribambase_role"] = "eevee-lighting-luminance"
    brightness_floor = nodes.new('ShaderNodeMath')
    brightness_floor.operation = 'MAXIMUM'
    brightness_floor.inputs[1].default_value = 0.0
    brightness_floor["pribambase_role"] = "ao-brightness-floor"
    brightness_ceiling = nodes.new('ShaderNodeMath')
    brightness_ceiling.operation = 'MINIMUM'
    brightness_ceiling.inputs[1].default_value = 1.0
    brightness_ceiling["pribambase_role"] = "ao-brightness-ceiling"
    inverse_ao = nodes.new('ShaderNodeMath')
    inverse_ao.operation = 'SUBTRACT'
    inverse_ao.inputs[0].default_value = 1.0
    inverse_ao["pribambase_role"] = "ao-inverse"
    inverse_roughness = nodes.new('ShaderNodeMath')
    inverse_roughness.operation = 'SUBTRACT'
    inverse_roughness.inputs[0].default_value = 1.0
    inverse_roughness["pribambase_role"] = "ao-inverse-roughness"
    smooth_metal = nodes.new('ShaderNodeMath')
    smooth_metal.operation = 'MULTIPLY'
    smooth_metal["pribambase_role"] = "ao-smooth-metal"
    material_ao_weight = nodes.new('ShaderNodeMath')
    material_ao_weight.operation = 'SUBTRACT'
    material_ao_weight.inputs[0].default_value = 1.0
    material_ao_weight["pribambase_role"] = "ao-material-weight"
    occlusion_by_light = nodes.new('ShaderNodeMath')
    occlusion_by_light.operation = 'MULTIPLY'
    occlusion_by_light["pribambase_role"] = "ao-by-light"
    occlusion_by_material = nodes.new('ShaderNodeMath')
    occlusion_by_material.operation = 'MULTIPLY'
    occlusion_by_material["pribambase_role"] = "ao-by-material"
    light_factor = nodes.new('ShaderNodeMath')
    light_factor.operation = 'SUBTRACT'
    light_factor.inputs[0].default_value = 1.0
    light_factor["pribambase_role"] = "ao-light-factor"
    ao_mix = nodes.new('ShaderNodeMixRGB')
    ao_mix.blend_type = 'MULTIPLY'
    ao_mix.inputs[0].default_value = 1.0
    ao_mix["pribambase_role"] = "ao-lit-color"

    emission_multiply = nodes.new('ShaderNodeMath')
    emission_multiply.operation = 'MULTIPLY'
    emission_multiply["pribambase_role"] = "emission-mask-strength"
    emission_color = nodes.new('ShaderNodeMixRGB')
    emission_color.blend_type = 'MULTIPLY'
    emission_color.inputs[0].default_value = 1.0
    emission_color["pribambase_role"] = "emission-color"
    add_emission = nodes.new('ShaderNodeMixRGB')
    add_emission.blend_type = 'ADD'
    add_emission.inputs[0].default_value = 1.0
    add_emission["pribambase_role"] = "eevee-final-color"
    eevee_output = nodes.new('ShaderNodeEmission')
    eevee_output.inputs['Strength'].default_value = 1.0
    eevee_output["pribambase_role"] = "eevee-output"

    links.new(group_input.outputs['Base Color'], eevee_pbr.inputs['Base Color'])
    links.new(group_input.outputs['Roughness'], eevee_pbr.inputs['Roughness'])
    links.new(group_input.outputs['Metallic'], eevee_pbr.inputs['Metallic'])
    links.new(eevee_pbr.outputs['BSDF'], shader_to_rgb.inputs['Shader'])
    links.new(shader_to_rgb.outputs['Color'], luminance.inputs['Color'])
    links.new(luminance.outputs['Val'], brightness_floor.inputs[0])
    links.new(brightness_floor.outputs[0], brightness_ceiling.inputs[0])
    links.new(group_input.outputs['Ambient Occlusion'], inverse_ao.inputs[1])
    links.new(group_input.outputs['Roughness'], inverse_roughness.inputs[1])
    links.new(group_input.outputs['Metallic'], smooth_metal.inputs[0])
    links.new(inverse_roughness.outputs[0], smooth_metal.inputs[1])
    links.new(smooth_metal.outputs[0], material_ao_weight.inputs[1])
    links.new(inverse_ao.outputs[0], occlusion_by_light.inputs[0])
    links.new(brightness_ceiling.outputs[0], occlusion_by_light.inputs[1])
    links.new(occlusion_by_light.outputs[0], occlusion_by_material.inputs[0])
    links.new(material_ao_weight.outputs[0], occlusion_by_material.inputs[1])
    links.new(occlusion_by_material.outputs[0], light_factor.inputs[1])
    links.new(shader_to_rgb.outputs['Color'], ao_mix.inputs[1])
    links.new(light_factor.outputs[0], ao_mix.inputs[2])
    links.new(group_input.outputs['Emission Mask'], emission_multiply.inputs[0])
    links.new(group_input.outputs['Emission Strength'], emission_multiply.inputs[1])
    links.new(group_input.outputs['Base Color'], emission_color.inputs[1])
    links.new(emission_multiply.outputs[0], emission_color.inputs[2])
    links.new(ao_mix.outputs[0], add_emission.inputs[1])
    links.new(emission_color.outputs[0], add_emission.inputs[2])
    links.new(add_emission.outputs[0], eevee_output.inputs['Color'])
    links.new(eevee_output.outputs['Emission'], group_output.inputs['EEVEE Shader'])

    # Cycles cannot separate direct and indirect light inside a material node
    # tree. Keep the proper metallic Principled material and let geometry/GI
    # provide occlusion instead of baking the AO map into the albedo.
    cycles_pbr = nodes.new('ShaderNodeBsdfPrincipled')
    cycles_pbr["pribambase_role"] = "cycles-pbr"
    emission_multiply = tree.nodes.new('ShaderNodeMath')
    emission_multiply.operation = 'MULTIPLY'
    emission_multiply["pribambase_role"] = "cycles-emission-mask-strength"

    emission_color_input = cycles_pbr.inputs.get('Emission Color') or cycles_pbr.inputs.get('Emission')
    emission_strength_input = cycles_pbr.inputs.get('Emission Strength')
    links.new(group_input.outputs['Base Color'], cycles_pbr.inputs['Base Color'])
    links.new(group_input.outputs['Roughness'], cycles_pbr.inputs['Roughness'])
    links.new(group_input.outputs['Metallic'], cycles_pbr.inputs['Metallic'])
    if emission_color_input is not None:
        links.new(group_input.outputs['Base Color'], emission_color_input)
    if emission_strength_input is not None:
        links.new(group_input.outputs['Emission Mask'], emission_multiply.inputs[0])
        links.new(group_input.outputs['Emission Strength'], emission_multiply.inputs[1])
        links.new(emission_multiply.outputs[0], emission_strength_input)
    links.new(cycles_pbr.outputs['BSDF'], group_output.inputs['Cycles Shader'])

    tree["pribambase_material_schema"] = MASTER_GROUP_SCHEMA
    tree["pribambase_ao_mode"] = "light-weighted-eevee"
    return tree


def _safe_asset_name(scene: bpy.types.Scene) -> str:
    value = "".join(
        char if char.isalnum() else "_"
        for char in scene.sb_state.asset_name
    ).strip("_")
    return value or scene.name


def ensure_material_image(
    scene: bpy.types.Scene,
    width: int | None = None,
    height: int | None = None,
) -> bpy.types.Image:
    state = scene.sb_state
    image = state.material_image
    if image is None:
        layout = state_layout(scene)
        if width is None:
            width = layout.width if layout is not None else 1
        if height is None:
            height = layout.height if layout is not None else 1
        name = f"PB_{_safe_asset_name(scene)}_ORME"
        image = bpy.data.images.get(name) or bpy.data.images.new(
            name,
            width=max(1, width),
            height=max(1, height),
            alpha=True,
        )
        state.material_image = image
        image.alpha_mode = 'CHANNEL_PACKED'
        try:
            image.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass
        pixels = np.empty((image.size[1], image.size[0], 4), dtype=np.float32)
        pixels[:] = (1.0, 128.0 / 255.0, 0.0, 0.0)
        image.pixels.foreach_set(pixels.ravel())
        image.update()
        image.pack()
    image.use_fake_user = True
    if image.alpha_mode != 'CHANNEL_PACKED':
        image.alpha_mode = 'CHANNEL_PACKED'
    if image.colorspace_settings.name != 'Non-Color':
        try:
            image.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass
    return image


def update_material_layout(material: bpy.types.Material, layout: Layout) -> None:
    if material is None or not material.use_nodes:
        return
    for node in material.node_tree.nodes:
        if node.get("pribambase_role") == "projection":
            node.inputs['Canvas Min X'].default_value = layout.min_x
            node.inputs['Canvas Min Y'].default_value = layout.min_y
            node.inputs['Canvas Width'].default_value = layout.width
            node.inputs['Canvas Height'].default_value = layout.height


def ensure_project_material(
    scene: bpy.types.Scene,
    image: bpy.types.Image,
) -> bpy.types.Material:
    state = scene.sb_state
    state.projection_image = image
    material = state.projection_material
    if material is None:
        name = f"PB_{_safe_asset_name(scene)}_Projected"
        material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        state.projection_material = material

    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    eevee_output = nodes.new('ShaderNodeOutputMaterial')
    eevee_output.target = 'EEVEE'
    eevee_output.location = (520, 100)
    eevee_output["pribambase_role"] = "eevee-material-output"
    cycles_output = nodes.new('ShaderNodeOutputMaterial')
    cycles_output.target = 'CYCLES'
    cycles_output.location = (520, -100)
    cycles_output["pribambase_role"] = "cycles-material-output"
    master = nodes.new('ShaderNodeGroup')
    master.node_tree = ensure_master_group()
    master.location = (260, 0)
    master["pribambase_role"] = "master"
    master.inputs['Emission Strength'].default_value = state.emission_strength
    texture = nodes.new('ShaderNodeTexImage')
    texture.image = image
    texture.interpolation = 'Closest'
    texture.extension = 'CLIP'
    texture.location = (-40, 80)
    texture["pribambase_role"] = "albedo"
    material_image = ensure_material_image(scene, image.size[0], image.size[1])
    packed = nodes.new('ShaderNodeTexImage')
    packed.image = material_image
    packed.interpolation = 'Closest'
    packed.extension = 'CLIP'
    packed.location = (-40, -180)
    packed["pribambase_role"] = "orme"
    separate = nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    separate.location = (150, -180)
    separate["pribambase_role"] = "orme-separate"
    projection = nodes.new('ShaderNodeGroup')
    projection.node_tree = ensure_projection_group()
    projection.location = (-300, 80)
    projection["pribambase_role"] = "projection"

    links = material.node_tree.links
    links.new(projection.outputs['Vector'], texture.inputs['Vector'])
    links.new(projection.outputs['Vector'], packed.inputs['Vector'])
    links.new(texture.outputs['Color'], master.inputs['Base Color'])
    links.new(packed.outputs['Color'], separate.inputs['Color'])
    links.new(separate.outputs['Red'], master.inputs['Ambient Occlusion'])
    links.new(separate.outputs['Green'], master.inputs['Roughness'])
    links.new(separate.outputs['Blue'], master.inputs['Metallic'])
    links.new(packed.outputs['Alpha'], master.inputs['Emission Mask'])
    links.new(master.outputs['EEVEE Shader'], eevee_output.inputs['Surface'])
    links.new(master.outputs['Cycles Shader'], cycles_output.inputs['Surface'])
    material["pribambase_project_material"] = True
    material["pribambase_profile"] = PROFILE_NAME
    material["pribambase_material_schema"] = PROJECT_MATERIAL_SCHEMA
    layout = state_layout(scene)
    if layout is not None:
        update_material_layout(material, layout)
    return material


def assign_project_material(scene: bpy.types.Scene, material: bpy.types.Material) -> int:
    assigned = 0
    for obj in projection_objects(scene):
        materials = obj.data.materials
        try:
            index = list(materials).index(material)
        except ValueError:
            materials.append(material)
            index = len(materials) - 1
        for polygon in obj.data.polygons:
            polygon.material_index = index
        assigned += 1
    return assigned


def update_project_material(scene: bpy.types.Scene) -> None:
    layout = state_layout(scene)
    material = scene.sb_state.projection_material
    if material is None:
        return
    if (
        material.get("pribambase_material_schema") != PROJECT_MATERIAL_SCHEMA
        or not material.use_nodes
        or not any(
            node.get("pribambase_role") == "master"
            and node.node_tree is not None
            and node.node_tree.get("pribambase_material_schema") == MASTER_GROUP_SCHEMA
            for node in material.node_tree.nodes
        )
    ):
        image = scene.sb_state.projection_image
        if image is None:
            return
        material = ensure_project_material(scene, image)
    if layout is not None:
        update_material_layout(material, layout)
    if not material.use_nodes:
        return
    for node in material.node_tree.nodes:
        role = node.get("pribambase_role")
        if role == "master" and node.inputs.get('Emission Strength') is not None:
            node.inputs['Emission Strength'].default_value = scene.sb_state.emission_strength
        elif role == "albedo":
            node.image = scene.sb_state.projection_image
        elif role == "orme":
            node.image = scene.sb_state.material_image


def apply_pixel_perfect_render_settings(scene: bpy.types.Scene) -> None:
    """Disable render-side smoothing that creates sub-pixel guide colors."""
    scene.render.filter_size = PIXEL_FILTER_SIZE


def apply_projection_camera(scene: bpy.types.Scene, camera_object: bpy.types.Object) -> None:
    layout = state_layout(scene)
    if layout is None:
        raise RuntimeError("Calculate the animation canvas first")
    if camera_object.type != 'CAMERA':
        raise RuntimeError("Projection view requires a camera object")

    center_x = (layout.min_x + layout.max_x) / (2.0 * PIXELS_PER_UNIT)
    center_y = (layout.min_y + layout.max_y) / (2.0 * PIXELS_PER_UNIT)
    up = Vector((0.0, math.sin(PROJECTION_ELEVATION), math.cos(PROJECTION_ELEVATION)))
    camera_axis = Vector((0.0, -math.cos(PROJECTION_ELEVATION), math.sin(PROJECTION_ELEVATION)))
    target = Vector((center_x, 0.0, 0.0)) + up * center_y
    camera_object.location = target + camera_axis * CAMERA_DISTANCE
    camera_object.rotation_euler = (CAMERA_ROTATION_X, 0.0, 0.0)
    camera_object.scale = (1.0, 1.0, 1.0)
    camera_object.data.type = 'ORTHO'
    # Blender applies ortho_scale to the fitted (wider or taller) sensor axis.
    # Using the larger canvas dimension keeps one world pixel exactly aligned
    # with one render pixel for both landscape and portrait canvases.
    camera_object.data.ortho_scale = max(layout.width, layout.height) / PIXELS_PER_UNIT
    camera_object.data.shift_x = 0.0
    camera_object.data.shift_y = 0.0
    camera_object.data.clip_start = 0.01
    camera_object.data.clip_end = 1000.0
    camera_object.data.dof.use_dof = False
    scene.camera = camera_object
    scene.render.resolution_x = layout.width
    scene.render.resolution_y = layout.height
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0
    scene.render.film_transparent = True
    apply_pixel_perfect_render_settings(scene)
    bpy.context.view_layer.update()


def restore_projection_camera(scene: bpy.types.Scene) -> bpy.types.Object:
    camera = scene.camera
    if camera is None or camera.type != 'CAMERA':
        data = bpy.data.cameras.new("PB_ProjectionCamera")
        camera = bpy.data.objects.new("PB_ProjectionCamera", data)
        scene.collection.objects.link(camera)
    apply_projection_camera(scene, camera)
    return camera


@contextmanager
def projection_render_context(scene: bpy.types.Scene):
    original_camera = scene.camera
    created = original_camera is None or original_camera.type != 'CAMERA'
    if created:
        data = bpy.data.cameras.new("PB_TemporaryProjectionCamera")
        camera = bpy.data.objects.new("PB_TemporaryProjectionCamera", data)
        scene.collection.objects.link(camera)
    else:
        camera = original_camera

    matrix = camera.matrix_world.copy()
    camera_values = (
        camera.data.type,
        camera.data.ortho_scale,
        camera.data.shift_x,
        camera.data.shift_y,
        camera.data.clip_start,
        camera.data.clip_end,
        camera.data.dof.use_dof,
    )
    render_values = (
        scene.render.resolution_x,
        scene.render.resolution_y,
        scene.render.resolution_percentage,
        scene.render.pixel_aspect_x,
        scene.render.pixel_aspect_y,
        scene.render.film_transparent,
        scene.render.filter_size,
    )
    try:
        apply_projection_camera(scene, camera)
        yield camera
    finally:
        scene.camera = original_camera
        if created:
            data = camera.data
            bpy.data.objects.remove(camera, do_unlink=True)
            bpy.data.cameras.remove(data)
        else:
            camera.matrix_world = matrix
            (
                camera.data.type,
                camera.data.ortho_scale,
                camera.data.shift_x,
                camera.data.shift_y,
                camera.data.clip_start,
                camera.data.clip_end,
                camera.data.dof.use_dof,
            ) = camera_values
        (
            scene.render.resolution_x,
            scene.render.resolution_y,
            scene.render.resolution_percentage,
            scene.render.pixel_aspect_x,
            scene.render.pixel_aspect_y,
            scene.render.film_transparent,
            scene.render.filter_size,
        ) = render_values
        bpy.context.view_layer.update()
