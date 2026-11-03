#!/usr/bin/env bash
# NextKDE Installer — entry point.
#
# The installer is independent of the product: this wrapper only guarantees a
# checkout, the vendored UI and a Python interpreter, then starts the wizard.
# Name the product checkout with `--root DIR` or KOS_ROOT; it defaults to
# ~/NextKde (only `local` mode reads it).
set -euo pipefail

here=""
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fi

# `curl | bash` leaves no checkout around this file: fetch the installer, build
# its vendored UI, and continue from there. One command, no manual clone.
if [[ ! -f "$here/installer/__main__.py" ]]; then
    repo="${KOS_INSTALLER_REPO:-https://github.com/SKJrpg/NextKDE-Installer.git}"
    ref="${KOS_INSTALLER_REF:-main}"
    target="${KOS_INSTALLER_DIR:-$HOME/NextKde-Installer}"
    command -v git >/dev/null || { echo "git is required to fetch the installer." >&2; exit 2; }
    if [[ -e "$target" && ! -f "$target/install.sh" ]]; then
        echo "$target exists but is not an installer checkout; set KOS_INSTALLER_DIR." >&2
        exit 2
    fi
    if [[ ! -d "$target/.git" ]]; then
        echo "fetching the installer into $target" >&2
        git clone --quiet --depth 1 --branch "$ref" "$repo" "$target" || exit 1
    fi
    if [[ ! -d "$target/vendor/textual" ]]; then
        echo "fetching the vendored UI dependencies" >&2
        python3 "$target/tools/vendor.py" >&2 \
            || echo "vendor build failed; continuing without the interactive UI" >&2
    fi
    # The piped script has no terminal on stdin; hand the wizard a real one.
    if [[ ! -t 0 ]] && { : </dev/tty; } 2>/dev/null; then
        exec "$target/install.sh" "$@" </dev/tty
    fi
    exec "$target/install.sh" "$@"
fi

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
