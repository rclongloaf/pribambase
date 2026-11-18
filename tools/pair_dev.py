"""Migrate a saved source pair, backing up all three sources before changing them."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import aseprite_dev
import blender_dev

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def migrate(manifest: Path) -> int:
    manifest = manifest.expanduser().resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema_version") not in {1, 2, 3, 4, 5}:
        raise blender_dev.DevError("Unsupported pair manifest version")
    sources = {}
    for kind in ("blender", "aseprite"):
        value = data.get("sources", {}).get(kind)
        if not value:
            raise blender_dev.DevError(f"Missing {kind} source in {manifest}")
        path = Path(value)
        sources[kind] = (manifest.parent / path).resolve() if not path.is_absolute() else path
        if not sources[kind].is_file():
            raise blender_dev.DevError(f"Missing source: {sources[kind]}")
    blender = blender_dev.find_blender()
    aseprite = aseprite_dev.find_aseprite()
    blender_dev.require_venv()
    backups = PROJECT_ROOT / "build" / "migrations"
    backups.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=backups))
    originals = {**sources, "manifest": manifest}
    copies = {}
    for kind, source in originals.items():
        target = backup / kind / source.name
        target.parent.mkdir()
        shutil.copy2(source, target)
        copies[kind] = target
    print(f"Source backup: {backup}", flush=True)
    references = backup / "references"
    references.mkdir()
    try:
        code = blender_dev.run_blender(
            blender, PROJECT_ROOT / "tools" / "migrate_blend.py", background=True,
            project_file=sources["blender"], script_arguments=[str(manifest), str(references)],
        )
        if code:
            raise blender_dev.DevError(f"Blender migration failed (exit {code})")
        env = os.environ.copy()
        env["ASEPRITE_USER_FOLDER"] = str(backup / "aseprite-profile")
        marker = backup / "sprite-migrated-ok"
        command = [str(aseprite), "--batch", "--script-param", f"source={sources['aseprite']}",
                   "--script-param", f"references={references}", "--script-param",
                   f"extension={PROJECT_ROOT / 'aseprite'}", "--script-param", f"result={marker}",
                   "--script", str(PROJECT_ROOT / "tools" / "migrate_sprite.lua")]
        print("> " + blender_dev.format_command(command), flush=True)
        code = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False).returncode
        if code or not marker.is_file():
            raise blender_dev.DevError(f"Aseprite migration failed (exit {code}); see console output")
    except BaseException:
        for kind, source in originals.items():
            shutil.copy2(copies[kind], source)
        print("Migration failed; restored all three original source files.", flush=True)
        raise
    print(f"Migrated source pair: {manifest}\nOriginal files retained in: {backup}")
    return 0


def main() -> int:
    blender_dev.load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("migrate",))
    parser.add_argument("manifest", type=Path, help="Path to the saved *.pribambase.json source pair")
    args = parser.parse_args()
    return migrate(args.manifest)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (blender_dev.DevError, OSError, ValueError) as error:
        print(f"error: {error}")
        raise SystemExit(2) from error
