"""Blender-side saved-pair migration, invoked by pair_dev.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

arguments = sys.argv[sys.argv.index("--") + 1:]
project, dependencies, manifest, reference_directory = map(Path, arguments)
sys.path.insert(0, str(dependencies))
sys.path.insert(0, str(project / "tools"))
from addon_loader import load_addon_module

package = load_addon_module(project)
package.register()
from pribambase import normals, projection, util, workspace

scene = bpy.context.scene
workspace.load_manifest(scene, manifest)
workspace.ensure_projection_layout(scene)
references = []
original_frame = scene.frame_current
for frame in range(scene.frame_start, scene.frame_end + 1):
    normals.generate_default(scene, frame, force=True)
    for mode in normals.REFERENCE_MODES:
        image = normals.default_image(scene, frame, mode)
        filename = f"{mode.lower()}-{frame:04d}.rgba"
        (reference_directory / filename).write_bytes(util.get_mirrored_pixels(image))
        references.append({"frame": frame, "mode": mode, "file": filename,
                           "width": image.size[0], "height": image.size[1]})
scene.frame_set(original_frame)
projection.update_project_material(scene)
(reference_directory / "references.json").write_text(json.dumps(references), encoding="utf-8")
original_save_version = bpy.context.preferences.filepaths.save_version
try:
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    workspace.write_manifest(scene)
finally:
    bpy.context.preferences.filepaths.save_version = original_save_version
print("Blender source migrated; generated both normal references for every animation frame")
