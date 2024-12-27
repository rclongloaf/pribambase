import math

def setup_uv(target_object, width, height, offset_x, offset_y):
    mesh = target_object.data
    matrix_world = target_object.matrix_world.inverted()

    PPU = 20

    angle = math.pi / 6

    vertices = mesh.vertices

    def calc_y(y, z):
        return y * math.sin(angle) + z * math.cos(angle)

    face_corners = mesh.loops
    uv = mesh.uv_layers['UVMap'].uv

    center_x = (width / 2 + offset_x)
    center_y = (height / 2 + offset_y)

    for i in range(len(face_corners)):
        vertex_ind = face_corners[i].vertex_index
        pos = vertices[vertex_ind].co @ matrix_world
        x = (pos.x * PPU + center_x) / width
        y = (calc_y(pos.y, pos.z) * PPU + center_y) / height
        uv[i].vector = (x, y)