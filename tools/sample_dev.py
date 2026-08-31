"""Build, validate, and open the Pribambase round-trip sample."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import aseprite_dev
import blender_dev


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = PROJECT_ROOT / "examples" / "roundtrip"
GENERATOR = SAMPLE_ROOT / "generate_sample.py"
ASEPRITE_GENERATOR = SAMPLE_ROOT / "generate_aseprite.lua"
BLEND_FILE = SAMPLE_ROOT / "pribambase_roundtrip.blend"
PNG_FILE = SAMPLE_ROOT / "roundtrip_texture.png"
PROJECTION_FILE = SAMPLE_ROOT / "roundtrip_projection.png"
ASEPRITE_FILE = SAMPLE_ROOT / "roundtrip_texture.aseprite"
PAIR_FILE = SAMPLE_ROOT / "pribambase_roundtrip.pribambase.json"
SAMPLE_TEST = PROJECT_ROOT / "tests" / "blender" / "roundtrip_sample_test.py"
ASEPRITE_SAMPLE_TEST = PROJECT_ROOT / "tests" / "aseprite" / "sample_test.lua"


def require_sample() -> None:
    missing = [
        path
        for path in (BLEND_FILE, PNG_FILE, PROJECTION_FILE, ASEPRITE_FILE, PAIR_FILE)
        if not path.is_file()
    ]
    if missing:
        paths = ", ".join(str(path) for path in missing)
        raise blender_dev.DevError(f"Sample artifacts are missing: {paths}. Run .\\sample.ps1 build.")


def build_sample(blender: Path, aseprite: Path) -> int:
    code = blender_dev.run_blender(
        blender,
        GENERATOR,
        background=True,
        script_arguments=[str(SAMPLE_ROOT)],
    )
    if code:
        return code

    if ASEPRITE_FILE.exists():
        ASEPRITE_FILE.unlink()
    isolated_profile = PROJECT_ROOT / "build" / "aseprite-sample-profile"
    isolated_profile.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["ASEPRITE_USER_FOLDER"] = str(isolated_profile)
    command = [
        str(aseprite),
        "--batch",
        "--script-param",
        f"source={PNG_FILE}",
        "--script-param",
        f"output={ASEPRITE_FILE}",
        "--script-param",
        f"channels={PROJECT_ROOT / 'aseprite' / 'Channels.lua'}",
        "--script",
        str(ASEPRITE_GENERATOR),
    ]
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    code = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False).returncode
    if code:
        return code
    if not ASEPRITE_FILE.is_file():
        raise blender_dev.DevError("Aseprite did not create roundtrip_texture.aseprite.")

    print(f"Generated Aseprite sample: {ASEPRITE_FILE}")
    return 0


def test_sample(blender: Path, aseprite: Path) -> int:
    require_sample()
    code = blender_dev.run_blender(
        blender,
        SAMPLE_TEST,
        background=True,
        script_arguments=[str(SAMPLE_ROOT)],
        project_file=BLEND_FILE,
    )
    if code:
        return code
    command = [
        str(aseprite),
        "--batch",
        "--script-param",
        f"sprite={ASEPRITE_FILE}",
        "--script-param",
        f"channels={PROJECT_ROOT / 'aseprite' / 'Channels.lua'}",
        "--script",
        str(ASEPRITE_SAMPLE_TEST),
    ]
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def run_sample(blender: Path, aseprite: Path, *, force: bool) -> int:
    require_sample()
    extension = aseprite_dev.build_extension()
    aseprite_dev.install_extension(extension, force=force)
    aseprite_dev.launch_aseprite(aseprite, [ASEPRITE_FILE])
    return blender_dev.run_blender(
        blender,
        PROJECT_ROOT / "tools" / "blender_startup.py",
        background=False,
        project_file=BLEND_FILE,
    )


def main() -> int:
    blender_dev.load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="info",
        choices=("info", "build", "test", "run", "all"),
    )
    parser.add_argument("--blender", help="Path to the Blender executable")
    parser.add_argument("--aseprite", help="Path to the Aseprite executable")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Back up an unmanaged Aseprite extension install",
    )
    args = parser.parse_args()

    blender = blender_dev.find_blender(args.blender)
    aseprite = aseprite_dev.find_aseprite(args.aseprite)
    if args.command == "info":
        print(f"Sample directory: {SAMPLE_ROOT}")
        print(f"Blender project: {BLEND_FILE}")
        print(f"Aseprite sprite: {ASEPRITE_FILE}")
        print(f"Source pair: {PAIR_FILE}")
        print(f"Blender: {blender}")
        print(f"Aseprite: {aseprite}")
        artifacts = (BLEND_FILE, PNG_FILE, PROJECTION_FILE, ASEPRITE_FILE, PAIR_FILE)
        print(f"Sample ready: {'yes' if all(path.is_file() for path in artifacts) else 'no'}")
        return 0
    if args.command == "build":
        return build_sample(blender, aseprite)
    if args.command == "test":
        return test_sample(blender, aseprite)
    if args.command == "run":
        return run_sample(blender, aseprite, force=args.force)
    if args.command == "all":
        code = build_sample(blender, aseprite)
        return code if code else test_sample(blender, aseprite)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (blender_dev.DevError, aseprite_dev.DevError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
