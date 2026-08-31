import bpy
# Render output is normalized to a temporary PNG before protocol encoding.
import shutil
import tempfile
from pathlib import Path

def get_render_image():
    """Render the active scene and load a temporary image with accessible pixels."""
    scene = bpy.context.scene
    original_filepath = scene.render.filepath
    original_file_format = scene.render.image_settings.file_format
    original_color_mode = scene.render.image_settings.color_mode
    temporary_directory = tempfile.mkdtemp(prefix="pribambase-render-")
    render_path = Path(temporary_directory) / "render_result.png"
    scene.render.filepath = str(render_path)
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    try:
        bpy.ops.render.render(write_still=True)
        if not render_path.is_file():
            raise RuntimeError("Blender did not produce a render result")
        image = bpy.data.images.load(str(render_path), check_existing=False)
        image["pribambase_temporary_render"] = temporary_directory
        return image
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise
    finally:
        scene.render.filepath = original_filepath
        scene.render.image_settings.file_format = original_file_format
        scene.render.image_settings.color_mode = original_color_mode


def remove_render_image(image):
    """Remove an image returned by get_render_image and its temporary directory."""
    temporary_directory = image.get("pribambase_temporary_render")
    bpy.data.images.remove(image)
    if temporary_directory:
        shutil.rmtree(temporary_directory, ignore_errors=True)
