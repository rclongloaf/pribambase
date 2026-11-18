#!/bin/bash
# macOS/Linux entry point; also works from WebStorm's bundled Shell Script runner.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

target="${1:-info}"
if [[ $# -gt 0 ]]; then shift; fi
case "$target" in
    blender|aseprite|sample)
        runner="$target"
        ;;
    setup|info|run|debug|test|unit|lint|all)
        runner=blender
        set -- "$target" "$@"
        ;;
    *)
        echo "Usage: ./dev.sh {setup|info|run|debug|test|unit|lint|all}" >&2
        echo "       ./dev.sh {blender|aseprite|sample} COMMAND [OPTIONS]" >&2
        exit 2
        ;;
esac

python="$project_root/.venv/bin/python"
if [[ ! -x "$python" ]] || ! "$python" --version >/dev/null 2>&1; then
    python="$(command -v python3 || true)"
    if [[ -z "$python" ]]; then
        echo "Python 3 was not found. Install the macOS Command Line Tools: xcode-select --install" >&2
        exit 2
    fi
fi

exec "$python" "$project_root/tools/${runner}_dev.py" "$@"
