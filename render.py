import bpy
import math

PPU = 20

def setup_camera_config(camera_object, width, height, offset_x, offset_y):
    camera = camera_object.data
    camera.type = 'ORTHO'
    max_size = max(width, height)
    camera.ortho_scale = max_size / PPU
    distance = 20
    angle = math.pi / 3
    camera_object.location = (
        -offset_x / PPU,
        -distance * math.sin(angle),
        distance * math.cos(angle) + (-offset_y / PPU) / math.sin(angle)
    )
    camera_object.rotation_euler = (angle, 0, 0)

def setup_render_config(render, eevee, width, height):
    render.resolution_x = width
    render.resolution_y = height
    render.film_transparent = True
    eevee.taa_render_samples = 1


def get_render_image():
    image_name = 'render_result.png'

    origin_filepath = bpy.data.scenes["Scene"].render.filepath
    render_path = origin_filepath + image_name
    bpy.data.scenes["Scene"].render.filepath = render_path

    if image_name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[image_name])

    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(render_path)
    bpy.data.scenes["Scene"].render.filepath = origin_filepath
    return image