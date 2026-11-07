"""NextKDE Installer — entry module.

The installer is independent of the product checkout: it detects the system,
lets the user pick a product source and options, and runs the product's own
install path. ``--root`` (or ``KOS_ROOT``) names that checkout.
"""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from . import VERSION, settings, workflow
from .backend import contract, probe
from .backend.models import BackendIncompatible
from .core.askpass import Askpass, sudo_ready
from .detect import deps_report, detect
from .paths import Paths
from .plan import ALL_APPS, Options, build_plan, unsupported
from .render import plain
from .source import DEFAULT_SOURCE, DISABLED_SOURCES
from .strings import Strings, choose_language

CONFIG_KEYS = ("source", "apps", "lockscreen", "start", "all", "proxy", "spatial",
               "theme", "keys")


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


def _options(args, config: dict, remembered_source: str | None = None) -> Options:
    opts = Options()
    if remembered_source in settings.SOURCES:
        opts.source = remembered_source
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
    if getattr(args, "no_start", False):
        opts.start = False
    if args.all:
        opts.apps = True
        opts.lockscreen = True
    if args.no_proxy:
        opts.proxy = False
    return opts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install.sh",
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
    parser.add_argument("--theme", choices=("system", "dark", "light"),
                        help="terminal appearance; dark is the default, "
                             "system follows the terminal's background")
    parser.add_argument("--apps", nargs="?", const="all", metavar="LIST",
                        help="also install the standalone apps; LIST narrows it (calendar,todo)")
    parser.add_argument("--lockscreen", action="store_true", help="also install the lock screen theme")
    parser.add_argument("--start", action="store_true",
                        help="start services after install (the default)")
    parser.add_argument("--no-start", action="store_true",
                        help="do not start services after install")
    parser.add_argument("--all", action="store_true", help="include apps and lock screen")
    parser.add_argument("--no-proxy", action="store_true", help="do not pass proxy variables through")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)

    # The installer is its own repository: the product checkout is an input,
    # never something inferred from __file__.
    paths = Paths.resolve(args.root)
    remembered = settings.load(paths)
    lang, no_cjk = choose_language(args.lang or remembered.get("lang"))
    strings = Strings(lang)
    if no_cjk:
        # Say why the interface is English; otherwise it looks like a missing translation.
        print(strings("note_no_cjk"), file=sys.stderr)
    config = _load_config(args.config) if args.config else {}
    if config.get("source") not in (None, "stable", "main", "local"):
        parser.error("config source must be 'stable', 'main' or 'local'")
    if config.get("theme") not in (None, "system", "dark", "light"):
        parser.error("config theme must be 'system', 'dark' or 'light'")
    opts = _options(args, config, remembered.get("source"))
    unknown = opts.app_set - set(ALL_APPS)
    if unknown:
        parser.error("unknown apps: " + ", ".join(sorted(unknown)))
    if opts.source in DISABLED_SOURCES:
        if args.source or "source" in config:
            parser.error(strings("source_unavailable_cli")
                         % (opts.source, DEFAULT_SOURCE))
        # A remembered channel may have been sealed since it was saved.
        opts.source = DEFAULT_SOURCE

    interactive = sys.stdout.isatty() and sys.stdin.isatty() and not args.plain and not args.yes
    if interactive and importlib.util.find_spec("textual") is None:
        # The vendored UI is optional (tools/vendor.py builds it): without it the
        # same plan still runs, it just cannot be shown interactively.
        print(strings("note_no_textual"), file=sys.stderr)
        interactive = False

    # The package probe shells out to kosctl doctor, one pacman call per package
    # (~6s here). The UI needs it only for the Review preview, so do not make the
    # wizard wait for it: KosApp checks in a worker once it is on screen.
    system = detect(root=paths.source_root, fallback_root=paths.sources_root,
                    check_packages=not interactive)
    steps = build_plan(system.family, opts, paths,
                       deps_missing=bool(system.missing_packages),
                       missing_packages=system.missing_packages)
    blocked_options = unsupported(system.family, opts)

    if args.check:
        # Read-only: the ref may be resolved (a network read), nothing is fetched.
        source = None
        try:
            source = workflow.identity(opts.source, opts, paths)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"{strings('prepare_failed')}: {error}", file=sys.stderr)
        if source is not None:
            if Path(source.path).is_dir():
                system.missing_packages = deps_report(Path(source.path))[1]
            # The report must name the workspace the run would use, not the
            # --root stand-in it was built with before the ref was resolved.
            steps = build_plan(system.family, opts, paths, source,
                               deps_missing=bool(system.missing_packages),
                               missing_packages=system.missing_packages)
        backend = None
        try:
            # The checkout given by --root is the product under inspection; an
            # unresolved workspace must not be probed as if it existed.
            root = (Path(source.path) if source is not None
                    and Path(source.path).is_dir() else paths.source_root)
            backend = contract.read(root) or probe.detect(root)
        except BackendIncompatible as error:
            print(strings("backend_incompatible") % error, file=sys.stderr)
            return 2
        plain.print_report(system, steps, strings, source=source)
        if backend is not None:
            detail = ("contract v1" if backend.source == "contract"
                      else f"probe · {len(backend.capabilities)} capabilities")
            print(f"  Backend: {detail}")
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

    if not interactive:
        # Redirected to a file or a pipe, stdout is block-buffered: a long
        # install would show nothing until it ends.
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except AttributeError:
            pass
        # No event loop here to answer an askpass request mid-run, so the
        # password is asked up front. Children get no tty, so without one the
        # run cannot succeed and stops before any step.
        askpass = None
        try:
            if not sudo_ready():
                if not sys.stdin.isatty():
                    print(strings("sudo_needs_password"), file=sys.stderr)
                    return 2
                askpass = Askpass()
                try:
                    askpass.set_password(
                        getpass.getpass(strings("sudo_password_prompt")))
                except (EOFError, KeyboardInterrupt):
                    print(strings("sudo_needs_password"), file=sys.stderr)
                    return 2
                # The plain path runs its children from this process's env.
                os.environ.update(askpass.env)
            # The installer owns the source: fetch the chosen commit first, then run
            # the plan built for that workspace.
            try:
                preparation = workflow.begin(opts.source, opts, paths)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f"{strings('prepare_failed')}: {error}", file=sys.stderr)
                return 1
            def plan_from_workspace() -> list:
                """The plan for the workspace that was just fetched (design §10.7)."""
                prepared = preparation.prepared
                root = Path(prepared.path)
                system.missing_packages = deps_report(root)[1]
                info = contract.read(root) or probe.detect(root)
                return build_plan(system.family, opts, paths, prepared,
                                  backend=info,
                                  deps_missing=bool(system.missing_packages),
                                  missing_packages=system.missing_packages)

            try:
                return plain.execute(system, plan_from_workspace, paths, strings,
                                     preparation=preparation)
            except BackendIncompatible as error:
                print(strings("backend_incompatible") % error, file=sys.stderr)
                return 2
        finally:
            if askpass is not None:
                askpass.close()

    # Imported here: the module needs Textual, which the branch above just checked.
    from .ui import keymap
    from .ui.app import KosApp

    if config.get("keys"):
        try:
            keymap.apply_overrides(config["keys"])
        except (TypeError, ValueError) as error:
            parser.error(str(error))

    # The screen starts from the same Options the flags and config made, so
    # `--source local --apps todo` is already selected when it opens. The theme
    # defaults to dark; the flag wins over the config, both over KOS_THEME.
    return int(KosApp(opts=opts, paths=paths, lang=lang, system=system,
                      remember=True, check_packages=True,
                      mode=args.theme or config.get("theme")).run() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
