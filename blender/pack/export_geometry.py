"""Blender entry point for baking the Pribambase camera lookup into FBX UVs."""

import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


PIXELS_PER_METER = 32.0


def smooth_at_hit(point, triangle, vertices, corner_normals, flat_normal):
    a, b, c = (vertices[index] for index in triangle.vertices)
    ab, ac, ap = b - a, c - a, point - a
    aa, bb, cc = ab.dot(ab), ab.dot(ac), ac.dot(ac)
    determinant = aa * cc - bb * bb
    if determinant <= 0:
        return flat_normal
    ab_weight = (cc * ap.dot(ab) - bb * ap.dot(ac)) / determinant
    ac_weight = (aa * ap.dot(ac) - bb * ap.dot(ab)) / determinant
    na, nb, nc = (corner_normals[index] for index in triangle.loops)
    normal = na + (nb - na) * ab_weight + (nc - na) * ac_weight
    return normal.normalized() if normal.length_squared > 1e-8 else flat_normal


def bake_normal_reference(mesh, asset, path, fallback, projected_origin):
    # Raycast the same texel centers used by CameraUV, with the top row first for Aseprite.
    width, height = asset["width"], asset["height"]
    density = asset["pixelsPerUnit"]
    left = asset["left"] - projected_origin[0]
    bottom = asset["bottom"] - projected_origin[1]
    tilt = math.sqrt(3) / 2
    up = Vector((0, 0.5, tilt))
    view = Vector((0, -tilt, 0.5))
    vertices = [vertex.co.copy() for vertex in mesh.vertices]
    front = view * (1 + max(vertex.dot(view) for vertex in vertices))
    mesh.calc_loop_triangles()
    triangles = list(mesh.loop_triangles)
    bvh = BVHTree.FromPolygons(vertices, [tri.vertices for tri in triangles], all_triangles=True)

    corner_normals = None
    if fallback == "smooth":
        smoothed = mesh.copy()
        for polygon in smoothed.polygons:
            polygon.use_smooth = True
        corner_normals = [corner.vector.copy() for corner in smoothed.corner_normals]
        bpy.data.meshes.remove(smoothed)

    pixels = bytearray(bytes((128, 128, 255, 0)) * (width * height))
    for y in range(height):
        row = front + up * ((bottom + height - y - 0.5) / density)
        for x in range(width):
            origin = row + Vector(((left + x + 0.5) / density, 0, 0))
            point, normal, index, _ = bvh.ray_cast(origin, -view)
            if normal is not None:
                if corner_normals is not None:
                    normal = smooth_at_hit(point, triangles[index], vertices, corner_normals, normal)
                at = (y * width + x) * 4
                for channel, component in enumerate(normal):
                    pixels[at + channel] = round(255 * (min(1, max(-1, component)) + 1) / 2)
                pixels[at + 3] = 255
    path.write_bytes(pixels)


def project_position(position, density):
    x, y, z = position
    half_density = 0.5 * density
    return density * x, half_density * y + half_density * math.sqrt(3) * z


def camera_uv(mesh, asset, pivot, offset, frame):
    density = asset["pixelsPerUnit"]
    anchor = project_position(pivot, density)
    delta = project_position(offset, density)
    points = [project_position(vertex.co, density) for vertex in mesh.vertices]
    shift = []
    projected_origin = []
    for coordinates, base, motion, start, size in zip(
        zip(*points), anchor, delta, (asset["left"], asset["bottom"]),
        (asset["width"], asset["height"]),
    ):
        moved_min = min(coordinates) + base + motion - start
        moved_max = max(coordinates) + base + motion - start
        if moved_min < -1e-4 or moved_max > size + 1e-4:
            raise ValueError(
                f"{asset['id']}, frame {frame}: recalculate the Pribambase canvas."
            )
        # Keep both the painted pose and the recentered PNG inside the same canvas.
        pixels = min(max(round(motion), math.ceil(moved_max - size - 1e-4)),
                     math.floor(moved_min + 1e-4))
        residual = motion - pixels
        shift.append(pixels)
        projected_origin.append(base + (0 if abs(residual) < 1e-4 else residual))

    for uv in tuple(mesh.uv_layers):
        mesh.uv_layers.remove(uv)
    uv = mesh.uv_layers.new(name="CameraUV")
    for loop in mesh.loops:
        x, y = points[loop.vertex_index]
        uv.data[loop.index].uv = (
            (x + projected_origin[0] - asset["left"]) / asset["width"],
            (y + projected_origin[1] - asset["bottom"]) / asset["height"],
        )
    return tuple(projected_origin), shift


def mesh_signature(mesh, projected_origin):
    return (
        projected_origin,
        tuple(tuple(vertex.co) for vertex in mesh.vertices),
        tuple((tuple(face.vertices), face.use_smooth) for face in mesh.polygons),
        tuple(tuple(edge.vertices) for edge in mesh.edges if edge.use_edge_sharp),
        tuple(tuple(normal.vector) for normal in mesh.corner_normals),
    )


def bake_asset(asset, output, normal_root, normal_fallback):
    with bpy.data.libraries.load(asset["blend"], link=False) as (source, target):
        if len(source.scenes) != 1:
            raise ValueError(f"{asset['id']}: the pair must contain one scene.")
        target.scenes = source.scenes
    scene = target.scenes[0]
    bpy.context.window.scene = scene
    collection = next((c for c in scene.collection.children_recursive
                       if c.name == asset["collection"]), None)
    if collection is None:
        raise ValueError(f"{asset['id']}: projected collection not found.")
    if scene.frame_start != 1:
        raise ValueError(f"{asset['id']}: start at frame 1.")
    meters_per_unit = asset["pixelsPerUnit"] / PIXELS_PER_METER

    ident = asset["id"]
    material = bpy.data.materials.new(ident)
    pivot = None
    poses = []
    shared = {}
    export_objects = []
    normal_root.mkdir()
    for index, frame in enumerate(range(scene.frame_start, scene.frame_end + 1)):
        scene.frame_set(frame)
        visible = [
            obj for obj in collection.all_objects if obj.type == "MESH" and not obj.hide_render
        ]
        if len(visible) != 1:
            raise ValueError(f"{ident}, frame {frame}: expected exactly one renderable mesh.")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = visible[0].evaluated_get(depsgraph)
        transform = evaluated.matrix_world.copy()
        position = transform.translation.copy()
        transform.translation = (0, 0, 0)
        if pivot is None:
            pivot = position
        offset = position - pivot

        mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=depsgraph)
        if not mesh.polygons:
            raise ValueError(f"{ident}, frame {frame}: evaluated mesh has no faces.")
        mesh.transform(transform)
        if transform.determinant() < 0:
            mesh.flip_normals()
        mesh.update()
        projected_origin, shift = camera_uv(mesh, asset, pivot, offset, frame)
        signature = mesh_signature(mesh, projected_origin)
        if signature in shared:
            bpy.data.meshes.remove(mesh)
            mesh_slot, normal_path = shared[signature]
        else:
            mesh_slot = f"frame_{index:02d}" if index else None
            name = f"{ident}_{mesh_slot}" if mesh_slot else ident
            normal_path = normal_root / f"{name}.rgba"
            bake_normal_reference(mesh, asset, normal_path, normal_fallback, projected_origin)
            mesh.materials.clear()
            mesh.materials.append(material)
            mesh.transform(Matrix.Scale(meters_per_unit, 4))
            mesh.rename(name, mode="ALWAYS")
            obj = bpy.data.objects.new(name, mesh)
            obj.rename(name, mode="ALWAYS")
            export_objects.append(obj)
            shared[signature] = (mesh_slot, normal_path)

        # Match the axes of Mesh sub-assets imported into Unity from this FBX.
        dx, dy, dz = offset
        offset_m = {axis: round(value * meters_per_unit, 8) or 0
                    for axis, value in zip("xyz", (-dx, dz, -dy))}
        pose = {"shift": shift, "normalReference": str(normal_path)}
        if mesh_slot is not None:
            pose["meshSlot"] = mesh_slot
        if any(offset_m.values()):
            pose["offsetM"] = offset_m
        poses.append(pose)

    asset["poses"] = poses[:1] if all(pose == poses[0] for pose in poses) else poses
    export_scene = bpy.data.scenes.new("Prop export")
    export_scene.unit_settings.system = scene.unit_settings.system
    bpy.context.window.scene = export_scene
    for obj in export_objects:
        export_scene.collection.objects.link(obj)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = export_objects[0]
    bpy.context.view_layer.update()

    model_path = output / f"{ident}.fbx"
    status = bpy.ops.export_scene.fbx(
        filepath=str(model_path), use_selection=True, object_types={"MESH"},
        apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z", axis_up="Y", bake_space_transform=True,
        use_triangles=True, bake_anim=False, mesh_smooth_type="FACE",
        path_mode="STRIP", embed_textures=False,
    )
    if "FINISHED" not in status or not model_path.is_file():
        raise RuntimeError(f"{asset['id']}: missing FBX after export.")
    return asset


job_path = Path(sys.argv[sys.argv.index("--") + 1])
job = json.loads(job_path.read_text(encoding="utf-8"))
job["asset"] = bake_asset(
    job["asset"], Path(job["output"]), Path(job["normalRoot"]), job.get("normalFallback")
)
job_path.write_text(json.dumps(job), encoding="utf-8")
