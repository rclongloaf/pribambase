"""Development entry point for running and testing the add-on with Blender."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = PROJECT_ROOT / ".venv"


class DevError(RuntimeError):
    """An actionable development-environment error."""


def load_dotenv(dotenv: Path) -> None:
    """Load a deliberately small KEY=VALUE subset without overriding the shell."""
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


def version_key(path: Path) -> tuple[int, ...]:
    matches = re.findall(r"\d+", path.parent.name)
    return tuple(int(value) for value in matches) or (0,)


def find_blender(explicit: str | None = None) -> Path:
    configured = explicit or os.environ.get("BLENDER_EXECUTABLE")
    if configured:
        blender = Path(configured).expanduser().resolve()
        if blender.is_file():
            return blender
        raise DevError(f"BLENDER_EXECUTABLE does not point to a file: {blender}")

    command = shutil.which("blender")
    if command:
        return Path(command).resolve()

    candidates: list[Path] = []
    if sys.platform == "win32":
        for variable in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if not base:
                continue
            candidates.extend(Path(base).glob("Blender Foundation/Blender */blender.exe"))
    elif sys.platform == "darwin":
        candidates.extend(Path("/Applications").glob("Blender*.app/Contents/MacOS/Blender"))
    else:
        candidates.extend(Path("/opt").glob("blender*/blender"))

    existing = sorted((path for path in candidates if path.is_file()), key=version_key)
    if existing:
        return existing[-1].resolve()

    raise DevError(
        "Blender was not found. Set BLENDER_EXECUTABLE in .env "
        "(copy the format from .env.example)."
    )


def format_command(command: Iterable[object]) -> str:
    parts = [str(part) for part in command]
    return subprocess.list2cmdline(parts) if sys.platform == "win32" else shlex.join(parts)


def run(command: list[str], *, env: dict[str, str] | None = None) -> int:
    print(f"> {format_command(command)}", flush=True)
    return subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False).returncode


def capture(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise DevError(result.stderr.strip() or result.stdout.strip() or format_command(command))
    return result.stdout.strip()


def python_is_usable(python: Path) -> bool:
    if not python.is_file():
        return False
    try:
        return subprocess.run(
            [str(python), "--version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        return False


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def find_blender_python(blender: Path) -> Path:
    marker = "PRIBAMBASE_PYTHON_PREFIX="
    expression = f"import sys; print('{marker}' + sys.prefix)"
    output = capture(
        [
            str(blender),
            "--background",
            "--factory-startup",
            "--offline-mode",
            "--python-exit-code",
            "1",
            "--python-expr",
            expression,
        ]
    )
    prefix_line = next((line for line in output.splitlines() if line.startswith(marker)), None)
    if not prefix_line:
        raise DevError("Blender did not report its Python prefix.")

    prefix = Path(prefix_line.removeprefix(marker).strip())
    candidates = [prefix / "bin" / "python.exe"]
    candidates.extend(sorted((prefix / "bin").glob("python3*"), reverse=True))
    for candidate in candidates:
        if python_is_usable(candidate):
            return candidate.resolve()
    raise DevError(f"Blender's bundled Python executable was not found under {prefix}.")


def backup_broken_venv() -> Path | None:
    if not VENV_DIR.exists() or python_is_usable(venv_python()):
        return None

    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = VENV_DIR.with_name(f"{VENV_DIR.name}.broken-{suffix}")
    VENV_DIR.rename(backup)
    print(f"Moved broken environment to {backup.name}")
    return backup


def setup(blender: Path) -> int:
    backup_broken_venv()
    python = venv_python()

    if not python_is_usable(python):
        blender_python = find_blender_python(blender)
        code = run([str(blender_python), "-m", "venv", str(VENV_DIR)])
        if code:
            return code

    commands = [
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        [str(python), "-m", "pip", "install", "-r", "requirements-dev.txt"],
    ]
    for command in commands:
        code = run(command)
        if code:
            return code

    print("\nDevelopment environment is ready.")
    print(f"PyCharm interpreter: {python}")
    print("Next: run .\\dev.ps1 all")
    return 0


def require_venv() -> Path:
    python = venv_python()
    if not python_is_usable(python):
        raise DevError("The development environment is missing. Run .\\dev.ps1 setup first.")
    try:
        capture([str(python), "-c", "import aiohttp"])
    except DevError as exc:
        raise DevError("Development dependencies are incomplete. Run .\\dev.ps1 setup.") from exc
    return python


def site_packages(python: Path) -> Path:
    expression = (
        "import site; from pathlib import Path; "
        "paths = site.getsitepackages(); "
        "print(next(path for path in paths if Path(path).name in {'site-packages', 'dist-packages'}))"
    )
    output = capture([str(python), "-c", expression])
    return Path(output.splitlines()[-1]).resolve()


def blender_environment(python: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(PROJECT_ROOT.parent), str(site_packages(python))]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PRIBAMBASE_DEV"] = "1"
    return env


def run_blender(
    blender: Path,
    script: Path,
    *,
    background: bool,
    script_arguments: list[str] | None = None,
) -> int:
    python = require_venv()
    dependencies = site_packages(python)
    command = [str(blender)]
    if background:
        command.append("--background")
    command.extend(
        [
            "--factory-startup",
            "--offline-mode",
            "--python-use-system-env",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            str(PROJECT_ROOT),
            str(dependencies),
            *(script_arguments or []),
        ]
    )
    return run(command, env=blender_environment(python))


def show_info(blender: Path) -> int:
    print(f"Project: {PROJECT_ROOT}")
    print(f"Blender: {blender}")
    version = capture([str(blender), "--version"]).splitlines()[0]
    print(f"Version: {version}")
    python = venv_python()
    print(f"PyCharm interpreter: {python}")
    print(f"Environment ready: {'yes' if python_is_usable(python) else 'no'}")
    return 0


def debug_address() -> tuple[str, int]:
    host = os.environ.get("BLENDER_DEBUG_HOST", "127.0.0.1")
    raw_port = os.environ.get("BLENDER_DEBUG_PORT", "5678")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise DevError(f"BLENDER_DEBUG_PORT must be an integer, got {raw_port!r}.") from exc
    if not 1 <= port <= 65535:
        raise DevError(f"BLENDER_DEBUG_PORT must be between 1 and 65535, got {port}.")
    return host, port


def ensure_debug_port_available(host: str, port: int) -> None:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DevError(f"Could not resolve BLENDER_DEBUG_HOST {host!r}.") from exc

    for family, socktype, protocol, _canonical_name, address in addresses:
        with socket.socket(family, socktype, protocol) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(address) == 0:
                raise DevError(
                    f"Debug address {host}:{port} is already in use. "
                    "Stop the previous debug session or change BLENDER_DEBUG_PORT in .env."
                )


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="info",
        choices=("setup", "info", "run", "debug", "test", "unit", "lint", "all"),
    )
    parser.add_argument("--blender", help="Path to Blender executable")
    args = parser.parse_args()

    blender = find_blender(args.blender)
    if args.command == "setup":
        return setup(blender)
    if args.command == "info":
        return show_info(blender)
    if args.command == "run":
        return run_blender(blender, PROJECT_ROOT / "tools" / "blender_startup.py", background=False)
    if args.command == "debug":
        host, port = debug_address()
        ensure_debug_port_available(host, port)
        return run_blender(
            blender,
            PROJECT_ROOT / "tools" / "blender_startup.py",
            background=False,
            script_arguments=["--debug", host, str(port)],
        )
    if args.command == "test":
        return run_blender(blender, PROJECT_ROOT / "tests" / "blender" / "smoke_test.py", background=True)

    python = require_venv()
    if args.command == "unit":
        return run(
            [
                str(python),
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests/unit",
                "-p",
                "test_*.py",
                "-v",
            ]
        )
    if args.command == "lint":
        return run([str(python), "-m", "ruff", "check", "."])
    if args.command == "all":
        for command in (
            [str(python), "-m", "ruff", "check", "."],
            [
                str(python),
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests/unit",
                "-p",
                "test_*.py",
                "-v",
            ],
        ):
            code = run(command)
            if code:
                return code
        code = run_blender(
            blender,
            PROJECT_ROOT / "tests" / "blender" / "smoke_test.py",
            background=True,
        )
        if code:
            return code
        return run(
            [
                str(python),
                str(PROJECT_ROOT / "tools" / "aseprite_dev.py"),
                "test",
            ]
        )
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DevError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
