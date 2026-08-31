"""Load the Blender add-on from its source directory under a stable module name."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


ADDON_MODULE_NAME = "pribambase"
ADDON_DIRECTORY_NAME = "blender"


def addon_source(project_root: Path) -> Path:
    source = (project_root / ADDON_DIRECTORY_NAME).resolve()
    if not (source / "__init__.py").is_file():
        raise RuntimeError(f"Blender add-on source is missing: {source}")
    return source


def load_addon_module(
    project_root: Path,
    module_name: str = ADDON_MODULE_NAME,
) -> ModuleType:
    """Import blender/__init__.py as the stable `pribambase` package."""
    source = addon_source(project_root)
    entrypoint = source / "__init__.py"
    existing = sys.modules.get(module_name)
    existing_file = getattr(existing, "__file__", None)
    if existing_file is not None and Path(existing_file).resolve() == entrypoint:
        return existing

    prefix = f"{module_name}."
    for loaded_name in tuple(sys.modules):
        if loaded_name == module_name or loaded_name.startswith(prefix):
            del sys.modules[loaded_name]

    spec = importlib.util.spec_from_file_location(
        module_name,
        entrypoint,
        submodule_search_locations=[str(source)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create an import spec for {entrypoint}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module
