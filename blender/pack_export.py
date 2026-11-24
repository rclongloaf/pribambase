"""Run the bundled pack exporter for the open Blender project's saved sources."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import bpy

EXPORTER = Path(__file__).resolve().parent / "pack" / "export_pack.py"
MISSING_EXPORT_FOLDER = "Choose an Export Folder before exporting"
_running = None


def is_exporting():
    return _running is not None and _running.poll() is None


def find_project(blend_path):
    if blend_path:
        for parent in Path(blend_path).resolve().parents:
            if any((parent / "assets").glob("*/*.pribambase.json")):
                return parent
    return None


def paired_asset(project, blend_path):
    if not blend_path:
        return None
    blend = Path(blend_path).resolve()
    if (
        blend.parent.parent == project / "assets"
        and blend.with_suffix(".pribambase.json").is_file()
    ):
        return blend.parent.name
    return None


def python_executable():
    prefix = Path(sys.exec_prefix)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = (
        prefix / "bin" / version,
        prefix / "bin" / "python.exe",
        prefix / "python.exe",
        shutil.which("python3"),
    )
    for candidate in candidates:
        if candidate and (executable := shutil.which(str(candidate))):
            return executable
    raise RuntimeError("Could not find Blender's Python interpreter.")


class SB_OT_export_pack(bpy.types.Operator):
    bl_idname = "pribambase.export_pack"
    bl_label = "Export Pack"
    bl_description = "Export FBX, textures and JSON from the project's saved Blender and Aseprite files"

    all_props: bpy.props.BoolProperty(name="All Props", default=False)
    normal_fallback: bpy.props.EnumProperty(
        name="Missing World Normals",
        items=(
            ("strict", "Require Painted Normals", "Stop this prop's export if a painted normal is missing"),
            ("flat", "Flat", "Fill missing pixels with polygon normals"),
            ("smooth", "Smooth", "Fill missing pixels with smooth normals"),
        ),
        default="strict",
    )

    @classmethod
    def poll(cls, context):
        if is_exporting():
            cls.poll_message_set("A pack export is already running")
            return False
        if not context.scene.sb_state.pack_output_directory.strip():
            cls.poll_message_set(MISSING_EXPORT_FOLDER)
            return False
        return True

    def invoke(self, context, event):
        project = find_project(bpy.data.filepath)
        if project is None:
            self.report({"ERROR"}, "Open a saved Blender file in a project with Pribambase pairs under assets/.")
            return {"CANCELLED"}
        self.asset_id = paired_asset(project, bpy.data.filepath)
        self.all_props = self.asset_id is None
        return context.window_manager.invoke_props_dialog(self, width=430)

    def draw(self, context):
        layout = self.layout
        if self.asset_id:
            layout.prop(self, "all_props")
            if not self.all_props:
                layout.label(text=self.asset_id)
        else:
            layout.label(text="All props · one pack per object")
        layout.prop(self, "normal_fallback")
        layout.label(text="Exports the saved Blender and Aseprite files.", icon="INFO")
        if self.asset_id and bpy.data.is_dirty:
            layout.label(text="This Blender file has unsaved changes.", icon="ERROR")

    def execute(self, context):
        global _running
        directory = context.scene.sb_state.pack_output_directory
        if not directory.strip():
            self.report({"ERROR"}, MISSING_EXPORT_FOLDER)
            return {"CANCELLED"}
        project = find_project(bpy.data.filepath)
        if project is None:
            self.report({"ERROR"}, "Open a saved Blender file in a project with Pribambase pairs under assets/.")
            return {"CANCELLED"}
        asset = paired_asset(project, bpy.data.filepath)
        if not self.all_props and asset is None:
            self.report({"ERROR"}, "Open an asset's Blender source or select All Props.")
            return {"CANCELLED"}
        try:
            self.destination = project / Path(bpy.path.abspath(directory)).expanduser()
            selection = ["--all"] if self.all_props else ["--asset", asset]
            args = [
                python_executable(), "-u", str(EXPORTER), "--project", str(project),
                *selection, "--blender", bpy.app.binary_path,
                "--output", str(self.destination),
            ]
            if self.normal_fallback != "strict":
                args.extend(("--normal-fallback", self.normal_fallback))
            self.log_dir = Path(tempfile.mkdtemp(prefix="pribambase-export-"))
            self.error_log = self.log_dir / "errors.log"
            with (self.log_dir / "output.log").open("wb") as output, self.error_log.open("wb") as errors:
                self.process = subprocess.Popen(args, cwd=project, stdout=output, stderr=errors)
        except (OSError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        _running = self.process
        self.report({"INFO"}, "Exporting project packs…" if self.all_props else f"Exporting {asset}…")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        global _running
        if event.type != "TIMER" or (status := self.process.poll()) is None:
            return {"PASS_THROUGH"}
        context.window_manager.event_timer_remove(self.timer)
        if _running is self.process:
            _running = None
        if context.area:
            context.area.tag_redraw()
        if status == 0:
            self.report({"INFO"}, f"Export complete · {self.destination}")
            return {"FINISHED"}
        message = self.error_log.read_text(encoding="utf-8", errors="replace").strip()
        print(f"Pribambase Pack Export log: {self.log_dir}\n{message}")
        normal_error = next((line for line in message.splitlines() if ": World Normal," in line), "")
        self.report({"ERROR"}, normal_error or f"Pack export failed. Logs: {self.log_dir}")
        return {"CANCELLED"}
