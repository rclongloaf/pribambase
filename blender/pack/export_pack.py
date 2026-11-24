#!/usr/bin/env python3
"""Export one camera-painted prop or rebuild all props independently."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


PACK = Path(__file__).resolve().parent
ASSET_ID = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
TEXTURE_FILENAME = re.compile(r"(?:base_color|emission|orm|world_normal)_(?:00|atlas_[0-9]{2,})\.png")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def binary(name, explicit):
    title = "Aseprite" if name == "aseprite" else "Blender"
    executable = title if name == "blender" else name
    candidate = explicit or shutil.which(name) or f"/Applications/{title}.app/Contents/MacOS/{executable}"
    resolved = shutil.which(candidate)
    if not resolved:
        raise ValueError(f"Set --{name} to the {title} executable.")
    return str(Path(resolved).resolve())


def read_pair(project, ident):
    if not re.fullmatch(ASSET_ID, ident):
        raise ValueError("Use the asset ID from the assets directory.")
    folder = (project / "assets" / ident).resolve()
    manifests = list(folder.glob("*.pribambase.json"))
    if len(manifests) != 1:
        raise ValueError(f"Expected one Pribambase pair manifest in {folder}.")
    path = manifests[0]
    pair = read(path)
    if pair["asset"] != ident:
        raise ValueError(f"Invalid pair identity at {path}")
    projection = pair["projection"]
    if projection["profile"] != "global_iso_v1":
        raise ValueError("Unsupported projection.")
    density = float(projection["pixels_per_unit"])
    if not math.isfinite(density) or density <= 0:
        raise ValueError("Projection pixels per unit must be positive and finite.")
    canvas = projection["canvas"]
    record = {
        "id": ident,
        "collection": projection["collection"],
        "pixelsPerUnit": density,
        "width": int(canvas["width"]),
        "height": int(canvas["height"]),
        "left": int(canvas["min_x"]),
        "bottom": int(canvas["min_y"]),
        "emissionStrength": float(projection["emission_strength"]),
    }
    for source, key in [("blender", "blend"), ("aseprite", "sprite")]:
        file = (folder / pair["sources"][source]).resolve(strict=True)
        if file.parent != folder:
            raise ValueError(f"Source must live next to its pair manifest: {file}")
        record[key] = str(file)
    return record


def create_manifest(out, asset, texture_data):
    ident = asset["id"]
    durations = texture_data["durations"]
    channels = texture_data["channels"]
    if not durations or any(ms <= 0 for ms in durations):
        raise ValueError(f"{ident}: invalid duration.")
    poses = asset["poses"]
    if len(poses) not in (1, len(durations)):
        raise ValueError(f"{ident}: Blender pose count must match the Aseprite frame count.")

    for channel in channels.values():
        filenames = [channel["file"]] if len(durations) == 1 else channel["pages"]
        for filename in filenames:
            if Path(filename).name != filename or not (out / "textures" / filename).is_file():
                raise ValueError(f"{ident}: missing texture {filename}")

    manifest = {"version": 1}
    if len(durations) == 1:
        return manifest

    frames = []
    for index, duration in enumerate(durations):
        pose = poses[0] if len(poses) == 1 else poses[index]
        frame = {
            "durationMs": duration,
            "rects": {name: data["rects"][index] for name, data in sorted(channels.items())},
        }
        if "meshSlot" in pose:
            frame["meshSlot"] = pose["meshSlot"]
        if "offsetM" in pose:
            frame["offsetM"] = pose["offsetM"]
        frames.append(frame)
    manifest["frames"] = frames
    return manifest


def legacy_texture_paths(manifest):
    previous = read(manifest) if manifest.is_file() else None
    model = f"{manifest.stem}.fbx"
    if isinstance(previous, dict):
        if previous.keys() == {"model", "textures"} and previous["model"] == model:
            return list(previous["textures"].values())
        if previous.keys() == {"model", "frames"} and previous["model"] == model:
            return [path for frame in previous["frames"] for path in frame["textures"].values()]
        if previous.keys() == {"frames"} and all(
            frame.get("model") == model for frame in previous["frames"]
        ):
            return [path for frame in previous["frames"] for path in frame["textures"].values()]
        if previous.keys() == {"atlases", "frames"} and all(
            frame.get("model") == model for frame in previous["frames"]
        ):
            return [path for pages in previous["atlases"].values() for path in pages]
        if (previous.get("schemaVersion") == 3 and previous.get("id") == manifest.stem
                and previous.get("model") == model):
            frames = previous.get("animation", {}).get("frames", [])
            maps = [previous["material"]["textures"], *(frame["textures"] for frame in frames)]
            return [path for group in maps for path in group.values()]
    raise ValueError(f"Existing folder is not an export of this asset: {manifest.parent}")


def previous_export_files(output):
    ident = output.name
    manifest = output / f"{ident}.rbprop"
    if manifest.is_file() and not manifest.is_symlink():
        previous = read(manifest)
        if (not isinstance(previous, dict)
                or type(previous.get("version")) is not int or previous["version"] != 1
                or previous.keys() - {"version", "frames"}):
            raise ValueError(f"Existing folder is not an export of this asset: {output}")

        # The .rbprop has no paths. Only the exporter's reserved PNG names are owned by this pack.
        directory = output / "textures"
        textures = set()
        if directory.is_dir() and not directory.is_symlink():
            for entry in directory.iterdir():
                name = entry.name.removesuffix(".meta")
                if entry.is_file() and TEXTURE_FILENAME.fullmatch(name):
                    textures.add(Path("textures", name))
    else:
        manifest = output / f"{ident}.json"
        textures = set(map(Path, legacy_texture_paths(manifest)))
    return {Path(manifest.name), Path(f"{ident}.fbx")} | textures


def publish(out, output):
    lock = output.with_name(f".{output.name}.camera-props-lock")
    lock.mkdir()
    try:
        if output.is_symlink():
            raise ValueError(f"Choose a real output directory: {output}")
        if not output.exists():
            out.rename(output)
            return
        generated = previous_export_files(output)
        folders = {Path("textures")} | {p for file in generated for p in file.parents if p.name}
        meta = {p.with_name(p.name + ".meta") for p in generated | folders}
        allowed = generated | folders | meta
        for file in output.rglob("*"):
            relative = file.relative_to(output)
            if file.is_symlink() or relative not in allowed:
                raise ValueError(f"Move this extra item outside the export folder: {file}")
            if relative in meta and (out / relative.with_suffix("")).exists():
                shutil.copy2(file, out / relative)
        backup = out.parent.with_name(out.parent.name + "-previous")
        output.rename(backup)
        try:
            out.rename(output)
        except OSError:
            backup.rename(output)
            raise
        shutil.rmtree(backup)
    finally:
        lock.rmdir()


def export_asset(asset, output, blender, aseprite, normal_fallback):
    with tempfile.TemporaryDirectory(prefix=".camera-props-", dir=output) as scratch:
        tmp = Path(scratch)
        out = tmp / asset["id"]
        (out / "textures").mkdir(parents=True)
        job = tmp / "job.json"
        metadata = tmp / "textures.json"
        job_data = {
            "output": str(out), "asset": asset, "metadata": str(metadata),
            "normalRoot": str(tmp / "geometry-normals"),
        }
        if normal_fallback is not None:
            job_data["normalFallback"] = normal_fallback
        write(job, job_data)
        subprocess.run(
            [blender, "--background", "--factory-startup", "--python-exit-code", "1",
             "--python", str(PACK / "export_geometry.py"), "--", str(job)], check=True,
        )
        subprocess.run(
            [aseprite, "--batch", "--script-param", f"job={job}",
             "--script", str(PACK / "export_textures.lua")], check=True,
        )
        texture_data = read(metadata)
        if "error" in texture_data:
            raise ValueError(texture_data["error"])
        manifest_name = f"{asset['id']}.rbprop"
        write(out / manifest_name, create_manifest(out, read(job)["asset"], texture_data))
        publish(out, output / asset["id"])
    return output / asset["id"] / manifest_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="Project folder containing assets/.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--asset", metavar="ID", help="Export one ID from the assets directory.")
    selection.add_argument("--all", action="store_true", help="Export every pair (the default).")
    parser.add_argument(
        "--normal-fallback", choices=("flat", "smooth"),
        help="Fill missing World Normal pixels with the selected geometry reference.",
    )
    parser.add_argument("--blender", default=os.getenv("BLENDER"))
    parser.add_argument("--aseprite", default=os.getenv("ASEPRITE"))
    parser.add_argument("--output", type=Path, help="Parent of the exported asset folders (default: project/export).")
    args = parser.parse_args()
    try:
        project = args.project.resolve(strict=True)
        blender = binary("blender", args.blender)
        aseprite = binary("aseprite", args.aseprite)
        asset_ids = [args.asset] if args.asset is not None else sorted({
            path.parent.name for path in (project / "assets").glob("*/*.pribambase.json")
        })
        if not asset_ids:
            raise ValueError("No source pairs were found.")
        output = (args.output or project / "export").absolute()
        if output.is_symlink():
            raise ValueError(f"Choose a real output directory: {output}")
        output.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Export failed: {exc}\n")

    failures = []
    for ident in asset_ids:
        try:
            manifest = export_asset(
                read_pair(project, ident), output, blender, aseprite, args.normal_fallback
            )
            print(f"Exported {ident} → {manifest}", flush=True)
        except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
            failures.append(ident)
            print(f"{ident}: {exc}", file=sys.stderr)
    if failures:
        parser.exit(1, f"Export failed for {', '.join(failures)}.\n")


if __name__ == "__main__":
    main()
