"""NextKDE Installer — entry module.

The installer is independent of the product checkout: it detects the system,
lets the user pick a product source and options, and runs the product's own
install path. ``--root`` (or ``KOS_ROOT``) names that checkout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import VERSION
from .detect import detect
from .paths import Paths
from .plan import ALL_APPS, Options, build_plan, unsupported
from .render import curses_ui, plain
from .strings import Strings, choose_language

CONFIG_KEYS = ("source", "apps", "lockscreen", "start", "all", "proxy", "spatial")


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


def _apply_apps(opts: Options, value) -> None:
    """`apps` is true/false in older configs and a list in the documented one."""
    if isinstance(value, list):
        opts.apps = True
        opts.app_set = {str(name) for name in value}
    else:
        opts.apps = bool(value)


def _options(args, config: dict) -> Options:
    opts = Options()
    if "source" in config:
        opts.source = str(config["source"])
    if "apps" in config:
        _apply_apps(opts, config["apps"])
    for name in ("lockscreen", "start", "proxy", "spatial"):
        if name in config:
            setattr(opts, name, bool(config[name]))
    if config.get("all"):
        opts.apps = True
        opts.lockscreen = True
    if args.source:
        opts.source = args.source
    if args.apps:
        if args.apps == "all":
            opts.apps = True
        else:
            _apply_apps(opts, [name.strip() for name in args.apps.split(",") if name.strip()])
    if args.lockscreen:
        opts.lockscreen = True
    if args.start:
        opts.start = True
    if args.all:
        opts.apps = True
        opts.lockscreen = True
    if args.no_proxy:
        opts.proxy = False
    return opts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/install.sh",
        description="KOS installer UI shell: detect the distribution and run the matching install path.",
    )
    parser.add_argument("--root", metavar="DIR",
                        help="NextKDE checkout to install (default: $KOS_ROOT or ~/NextKde)")
    parser.add_argument("--check", action="store_true", help="report only; change nothing")
    parser.add_argument("--yes", action="store_true", help="non-interactive, accept the plan")
    parser.add_argument("--plain", action="store_true", help="force the plain renderer")
    parser.add_argument("--config", metavar="FILE", help="JSON options file")
    parser.add_argument("--lang", choices=("zh", "en"))
    parser.add_argument("--source", choices=("stable", "main", "local"),
                        help="source release to install; local keeps this checkout untouched")
    parser.add_argument("--apps", nargs="?", const="all", metavar="LIST",
                        help="also install the standalone apps; LIST narrows it (calendar,todo)")
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
    # The installer is its own repository: the product checkout is an input,
    # never something inferred from __file__.
    paths = Paths.resolve(args.root)
    config = _load_config(args.config) if args.config else {}
    if config.get("source") not in (None, "stable", "main", "local"):
        parser.error("config source must be 'stable', 'main' or 'local'")
    opts = _options(args, config)
    unknown = opts.app_set - set(ALL_APPS)
    if unknown:
        parser.error("unknown apps: " + ", ".join(sorted(unknown)))

    system = detect(root=paths.source_root)
    steps = build_plan(system.family, opts, paths)
    blocked_options = unsupported(system.family, opts)

    if args.check:
        plain.print_report(system, steps, strings)
        if blocked_options:
            print(strings("unsupported_options") % ", ".join(blocked_options), file=sys.stderr)
        return 2 if system.blocked or blocked_options else 0

    if blocked_options:
        print(strings("unsupported_options") % ", ".join(blocked_options), file=sys.stderr)
        return 2

    if not steps:
        plain.print_report(system, steps, strings)
        return 0 if system.method == "report" else 2

    if system.blocked:
        plain.print_report(system, steps, strings)
        print(strings("review_blocked"), file=sys.stderr)
        return 2

    interactive = sys.stdout.isatty() and sys.stdin.isatty() and not args.plain and not args.yes
    if not interactive:
        # Redirected to a file or a pipe, stdout is block-buffered: a long
        # install would show nothing until it ends.
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except AttributeError:
            pass
    if not interactive:
        return plain.execute(system, steps, paths, strings)

    return curses_ui.UI(system, paths, strings, lang_explicit=bool(args.lang)).run()


if __name__ == "__main__":
    raise SystemExit(main())
