#!/usr/bin/env bash
# NextKDE Installer — entry point.
#
# The installer is independent of the product: this wrapper only guarantees a
# Python interpreter and starts the wizard. Name the product checkout with
# `--root DIR` or KOS_ROOT; it defaults to ~/NextKde.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

python_ok() {
    command -v python3 >/dev/null 2>&1 \
        && python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

if ! python_ok; then
    {
        echo "python3 3.10 or newer is required to run the installer." >&2
        echo >&2
        echo "Install it with the command for this system:" >&2
        if command -v apt-get >/dev/null 2>&1; then
            echo "  sudo apt-get install -y python3" >&2
        elif command -v pacman >/dev/null 2>&1; then
            echo "  sudo pacman -S --needed python" >&2
        elif command -v dnf >/dev/null 2>&1; then
            echo "  sudo dnf install -y python3" >&2
        elif command -v zypper >/dev/null 2>&1; then
            echo "  sudo zypper install -y python3" >&2
        else
            echo "  install python3 with your package manager" >&2
        fi
    }
    exit 2
fi

# Vendored Textual lives in vendor/ (tools/vendor.py builds it); it is optional,
# so a checkout without it falls back to the plain renderer.
vendor_path=
if [ -d "$here/vendor" ]; then
    vendor_path="$here/vendor:"
fi

exec env PYTHONPATH="$vendor_path$here${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m installer "$@"
