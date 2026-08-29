"""Build, test, install, and run the Pribambase Aseprite client."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = PROJECT_ROOT / "client"
BUILD_ROOT = PROJECT_ROOT / "build" / "aseprite"
DIST_ROOT = PROJECT_ROOT / "dist"
SMOKE_TEST = PROJECT_ROOT / "tests" / "aseprite" / "smoke_test.lua"
DEV_MARKER = ".pribambase-dev"


class DevError(RuntimeError):
    """An actionable Aseprite development error."""


@dataclass(frozen=True)
class BuildResult:
    name: str
    version: str
    directory: Path
    archive: Path


def load_dotenv(dotenv: Path) -> None:
    """Load a small KEY=VALUE subset without overriding the shell."""
    if not dotenv.is_file():
        return

    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def find_aseprite(explicit: str | None = None) -> Path:
    configured = explicit or os.environ.get("ASEPRITE_EXECUTABLE")
    if configured:
        executable = Path(configured).expanduser().resolve()
        if executable.is_file():
            return executable
        raise DevError(f"ASEPRITE_EXECUTABLE does not point to a file: {executable}")

    command = shutil.which("aseprite")
    if command:
        return Path(command).resolve()

    candidates: list[Path] = []
    if sys.platform == "win32":
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if not base:
                continue
            root = Path(base)
            candidates.extend(
                (
                    root / "Aseprite" / "Aseprite.exe",
                    root / "Programs" / "Aseprite" / "Aseprite.exe",
                    root / "Steam" / "steamapps" / "common" / "Aseprite" / "Aseprite.exe",
                )
            )
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Aseprite.app/Contents/MacOS/aseprite"))
    else:
        candidates.extend((Path("/usr/bin/aseprite"), Path("/usr/local/bin/aseprite")))

    executable = next((path for path in candidates if path.is_file()), None)
    if executable is not None:
        return executable.resolve()

    raise DevError(
        "Aseprite was not found. Set ASEPRITE_EXECUTABLE in .env "
        "(copy the format from .env.example)."
    )


def user_config_path() -> Path:
    configured = os.environ.get("ASEPRITE_USER_FOLDER") or os.environ.get("ASEPRITE_USER_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()

    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            raise DevError("APPDATA is unavailable; set ASEPRITE_USER_FOLDER in .env.")
        return (Path(base) / "Aseprite").resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "Aseprite").resolve()

    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return (base / "aseprite").resolve()


def read_manifest() -> dict[str, object]:
    path = CLIENT_ROOT / "package.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DevError(f"Aseprite manifest is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DevError(f"Invalid Aseprite manifest {path}: {exc}") from exc

    name = manifest.get("name")
    version = manifest.get("version")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
        raise DevError("client/package.json must contain a safe lowercase package name.")
    if not isinstance(version, str) or not version:
        raise DevError("client/package.json must contain a non-empty version.")

    contributes = manifest.get("contributes")
    scripts = contributes.get("scripts") if isinstance(contributes, dict) else None
    if not isinstance(scripts, list) or not scripts:
        raise DevError("client/package.json must contribute at least one script.")

    for script in scripts:
        relative = script.get("path") if isinstance(script, dict) else None
        if not isinstance(relative, str):
            raise DevError("Every contributed script must have a path.")
        source = (CLIENT_ROOT / relative).resolve()
        if CLIENT_ROOT.resolve() not in source.parents or not source.is_file():
            raise DevError(f"Contributed script is missing or outside /client: {relative}")

    return manifest


def clear_generated_directory(path: Path) -> None:
    project = PROJECT_ROOT.resolve()
    resolved = path.resolve()
    if resolved == project or project not in resolved.parents:
        raise DevError(f"Refusing to clear a path outside generated project output: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def client_files() -> list[Path]:
    return sorted(
        path
        for path in CLIENT_ROOT.rglob("*")
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(CLIENT_ROOT).parts)
    )


def build_client() -> BuildResult:
    manifest = read_manifest()
    name = str(manifest["name"])
    version = str(manifest["version"])
    destination = BUILD_ROOT / name

    clear_generated_directory(BUILD_ROOT)
    destination.mkdir(parents=True)
    for source in client_files():
        relative = source.relative_to(CLIENT_ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    archive = DIST_ROOT / f"{name}.aseprite-extension"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for source in sorted(path for path in destination.rglob("*") if path.is_file()):
            package.write(source, source.relative_to(destination).as_posix())

    print(f"Built Aseprite client {name} {version}")
    print(f"Directory: {destination}")
    print(f"Package: {archive}")
    return BuildResult(name, version, destination, archive)


def install_client(build: BuildResult, *, force: bool = False) -> Path:
    extensions = user_config_path() / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    target = extensions / build.name

    if target.exists() and not (target / DEV_MARKER).is_file():
        if not force:
            raise DevError(
                f"An unmanaged extension already exists at {target}. "
                "Remove it in Aseprite or rerun with --force to preserve it as a backup."
            )
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = extensions / f"{build.name}.backup-{suffix}"
        target.rename(backup)
        print(f"Moved the existing extension to {backup}")

    stage = extensions / f".{build.name}-dev-stage-{os.getpid()}"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(build.directory, stage)
    (stage / DEV_MARKER).write_text(
        f"Managed from {PROJECT_ROOT}\n",
        encoding="utf-8",
    )

    if target.exists():
        shutil.rmtree(target)
    stage.rename(target)
    print(f"Installed development client: {target}")
    return target


def run_command(command: list[str]) -> int:
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def launch_aseprite(executable: Path) -> int:
    command = [str(executable)]
    print(f"> {subprocess.list2cmdline(command)}", flush=True)
    process = subprocess.Popen(command, cwd=PROJECT_ROOT)
    print(f"Aseprite started (PID {process.pid}).")
    return 0


def test_client(aseprite: Path) -> int:
    build = build_client()
    result_marker = BUILD_ROOT / ".smoke-test-ok"
    if result_marker.exists():
        result_marker.unlink()
    code = run_command(
        [
            str(aseprite),
            "--batch",
            "--script-param",
            f"client={build.directory}",
            "--script-param",
            f"result={result_marker}",
            "--script",
            str(SMOKE_TEST),
        ]
    )
    if code:
        return code
    if not result_marker.is_file() or result_marker.read_text(encoding="utf-8") != "ok\n":
        raise DevError("Aseprite did not complete the client smoke test.")
    print("Pribambase Aseprite client smoke test passed")
    return 0


def aseprite_is_running(executable: Path) -> bool:
    if sys.platform != "win32":
        return False
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {executable.name}", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return f'"{executable.name}"'.casefold() in result.stdout.casefold()


def show_info(aseprite: Path) -> int:
    manifest = read_manifest()
    target = user_config_path() / "extensions" / str(manifest["name"])
    print(f"Project: {PROJECT_ROOT}")
    print(f"Aseprite: {aseprite}")
    print(f"Aseprite user config: {user_config_path()}")
    print(f"Client: {manifest['name']} {manifest['version']}")
    print(f"Development client installed: {'yes' if (target / DEV_MARKER).is_file() else 'no'}")
    print(f"Aseprite running: {'yes' if aseprite_is_running(aseprite) else 'no'}")
    return 0


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="info",
        choices=("info", "build", "install", "test", "run", "all"),
    )
    parser.add_argument("--aseprite", help="Path to the Aseprite executable")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Back up and replace an extension not installed by this runner",
    )
    args = parser.parse_args()

    if args.command == "build":
        build_client()
        return 0

    aseprite = find_aseprite(args.aseprite)
    if args.command == "info":
        return show_info(aseprite)
    if args.command == "install":
        install_client(build_client(), force=args.force)
        return 0
    if args.command == "test":
        return test_client(aseprite)
    if args.command == "all":
        return test_client(aseprite)
    if args.command == "run":
        install_client(build_client(), force=args.force)
        if aseprite_is_running(aseprite):
            print(
                "Warning: Aseprite is already running; starting a separate development instance "
                "so the updated client is loaded."
            )
        return launch_aseprite(aseprite)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DevError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
