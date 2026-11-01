"""KOS installer UI shell — entry module.

The shell detects the distribution, picks the install path that already exists
for it, and runs it. See docs/superpowers/specs/2026-11-01-installer-tui-design.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import VERSION
from .detect import detect
from .plan import Options, build_plan
from .render import curses_ui, plain
from .strings import Strings, choose_language

CONFIG_KEYS = ("source", "apps", "lockscreen", "start", "all", "proxy")


def _load_config(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    unknown = set(data) - set(CONFIG_KEYS) - {"components"}
    if unknown:
        raise SystemExit(f"unknown config keys: {', '.join(sorted(unknown))}")
    components = data.pop("components", []) or []
    if "apps" in components:
        data.setdefault("apps", True)
    if "lockscreen" in components:
        data.setdefault("lockscreen", True)
    return data


def _options(args, config: dict) -> Options:
    opts = Options()
    if "source" in config:
        opts.source = str(config["source"])
    for name in ("apps", "lockscreen", "start", "proxy"):
        if name in config:
            setattr(opts, name, bool(config[name]))
    if "all" in config:
        opts.install_all = bool(config["all"])
    if args.source:
        opts.source = args.source
    for name in ("apps", "lockscreen", "start", "all"):
        if getattr(args, name):
            if name == "all":
                opts.install_all = True
            else:
                setattr(opts, name, True)
    if args.no_proxy:
        opts.proxy = False
    return opts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/install.sh",
        description="KOS installer UI shell: detect the distribution and run the matching install path.",
    )
    parser.add_argument("--check", action="store_true", help="report only; change nothing")
    parser.add_argument("--yes", action="store_true", help="non-interactive, accept the plan")
    parser.add_argument("--plain", action="store_true", help="force the plain renderer")
    parser.add_argument("--config", metavar="FILE", help="JSON options file")
    parser.add_argument("--lang", choices=("zh", "en"))
    parser.add_argument("--source", choices=("stable", "main"), help="source release to install")
    parser.add_argument("--apps", action="store_true", help="also install the standalone apps")
    parser.add_argument("--lockscreen", action="store_true", help="also install the lock screen theme")
    parser.add_argument("--start", action="store_true", help="start services after install")
    parser.add_argument("--all", action="store_true", help="include apps and lock screen")
    parser.add_argument("--no-proxy", action="store_true", help="do not pass proxy variables through")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)

    lang, no_cjk = choose_language(args.lang)
    strings = Strings(lang)
    if no_cjk:
        # Say why the interface is English; otherwise it looks like a missing translation.
        print(strings("note_no_cjk"), file=sys.stderr)
    root = Path(__file__).resolve().parents[2]
    config = _load_config(args.config) if args.config else {}
    if config.get("source") not in (None, "stable", "main"):
        parser.error("config source must be 'stable' or 'main'")
    opts = _options(args, config)

    system = detect()
    steps = build_plan(system.family, opts, root)

    if args.check:
        plain.print_report(system, steps, strings)
        return 2 if system.blocked else 0

    if not steps:
        plain.print_report(system, steps, strings)
        return 0 if system.method == "report" else 2

    interactive = sys.stdout.isatty() and sys.stdin.isatty() and not args.plain and not args.yes
    if not interactive:
        # Redirected to a file or a pipe, stdout is block-buffered: a long
        # install would show nothing until it ends.
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except AttributeError:
            pass
    log_dir = Path.home() / ".local" / "state" / "kos" / "installer"
    if not interactive:
        log_path = log_dir / "install.log"
        return plain.execute(system, steps, root, log_path, strings)

    return curses_ui.UI(system, root, strings, log_dir).run()


if __name__ == "__main__":
    raise SystemExit(main())
