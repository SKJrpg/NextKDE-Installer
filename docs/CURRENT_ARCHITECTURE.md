# Current architecture

What this repository is today (branch `main`, commit at the time of writing: `7981afe`).
It is written from the code, not from intent: every claim below is something the tree does.

## 1. What the installer is

A standalone Python program that installs NextKDE. It owns the wizard, the system checks,
the source choice and the plan; it does **not** own building or deploying the desktop.
That stays in the product repository (`NextKde/NextKde`): `tools/kosctl`,
`tools/install-debian13.sh`, `tools/kos-state.py`.

The product checkout is an input (`--root`, `KOS_ROOT`, default `~/NextKde`), never inferred
from `__file__`.

## 2. Layout

```
install.sh              python3 >= 3.10 check, then `python3 -m installer`
installer/
  __init__.py           VERSION
  __main__.py           argparse, config file, plan, renderer choice, exit codes
  paths.py              Paths: installer_root, source_root, build_root, state_root,
                        log_dir, sources_root, installer_runtime
  detect.py             /etc/os-release parsing, family map, 13 probes, blocked flag
  plan.py               Options -> [Step]; source/components/start ordering; argv only
  runner.py             StepRunner: argv, process group, streamed output, cancel
  manage.py             reads the ledger/snapshots/logs/deps through the product's tools
  strings.py            zh/en pairs, locale choice, CJK font probe
  source/               Git Source Manager (see section 5)
  render/
    curses_ui.py        the wizard (screens, keys, action runner, install loop)
    plain.py            the same plan without a TTY; NO_COLOR aware
    theme.py            semantic roles, Unicode/ASCII glyph sets
    layout.py           narrow/standard/wide geometry, list stacking, scrolling
    widgets.py          one Canvas per frame, rules, bars, rows, dialogs, width/clip/wrap
tests/                  134 offline unit tests
docs/design.md          the independent-installer architecture proposal
```

`installer/render/curses_ui.py` is the only module that owns terminal state; everything it
shows comes from `detect`, `plan`, `manage` and `runner`.

## 3. Startup and flow

```
install.sh
  └─ python3 -m installer [flags]
       ├─ Paths.resolve(--root)
       ├─ detect(root=source_root)          # runs `kosctl doctor`, reads the guide
       ├─ Options from CLI + JSON config
       ├─ build_plan(family, opts, paths)   # argv steps, nothing executed
       └─ curses UI (TTY) | plain (no TTY, --plain, --yes)
            └─ on confirm: workflow.begin() -> stream the clone -> finish()
               -> build_plan(..., prepared=...) -> run
```

Exit codes: `--check` returns 0 when nothing is blocked, 2 when a probe fails or the backend
cannot honour the selection; the plain executor returns the failing step's status, 130 when
cancelled.

`--check` is read-only. It runs probes (including `kosctl doctor`) and prints the plan.

## 4. The plan

`plan.build_plan()` returns `Step(key, title, argv, env, note)` objects. Nothing else executes
commands. Today's steps:

| Family | Steps |
|---|---|
| debian | `install-debian13.sh --dir <root> --spatial … [--repo <origin>] [--local]`, then apps/lockscreen, then `start` |
| nixos | `kosctl nix install`, then `start` |
| arch / ubuntu / fedora | `kosctl update <ref>` only when nothing was prepared; otherwise `kosctl install`, `kosctl install apps [--only …]`, `kosctl install lockscreen`, `kosctl start` inside the prepared workspace |
| opensuse / unknown | nothing; the UI reports only |

`KOS_BUILD_SPATIAL=ON|OFF` and the proxy/session variables are placed in each step's env.
`paths.build_root` is defined but deliberately not exported yet: the backend's handling of
`KOS_BUILD_DIR` / `KOS_APPS_BUILD_DIR` is unverified.

## 5. Source manager

`installer/source/` resolves a mode to exactly one commit and one immutable workspace:

| Mode | Meaning | Git writes |
|---|---|---|
| stable | newest release tag of the configured repository (`NextKde/NextKde`) | clone only |
| development | the `main` branch of that repository | clone only |
| local | the `--root` checkout as it is | none: no fetch, checkout, reset or remote edit |

- The ref is resolved with `git ls-remote` **before** anything is cloned; the commit is the
  identity.
- Managed workspaces: `<XDG_DATA_HOME>/nextkde/sources/<repository-id>/<commit>/`, cloned
  `--depth 1` into `<commit>.tmp`, HEAD verified, `source.json` written, then the directory is
  renamed into place. A prepared commit is never rewritten.
- Reuse requires the directory's HEAD and the manifest's repository to match; otherwise the
  error says to remove it.
- Wired: `workflow.begin()` resolves the channel and returns a `Preparation` (already prepared
  for local or a reused workspace, otherwise one streamable clone step); `finish()` verifies,
  records and renames. `plan.build_plan(..., prepared=...)` runs every step inside the prepared
  workspace and emits no `kosctl update`; `--check` resolves the identity read-only.

## 6. Rendering

- One `Canvas` per frame, so two writers cannot share a cell (asserted by a test).
- `layout_for(w, h)` returns narrow (<80) / standard (80–109) / wide (110+) / tiny geometry.
- Unicode glyphs with an ASCII set chosen from terminal capability; status is text
  (`通过/注意/失败`, `PASS/WARN/FAIL`) plus colour, never colour alone.
- Install screen: stage list (done/current/waiting/failed/skipped), measured counters when the
  runner reports them, otherwise an explicit indeterminate bar; `p` pauses the log.
- Plain mode shares `strings`, `plan`, `detect`, and the same exit codes.

## 7. Process execution

`StepRunner` runs an argv list with `start_new_session=True`, streams stdout+stderr through a
selector, classifies lines, and writes them to the run log. `cancel()` signals the process
group with SIGTERM and escalates to SIGKILL after five seconds; `close()` always waits, so the
child is reaped. No `shell=True` anywhere.

## 8. Backend surface actually used

| Call | Where | Present upstream? |
|---|---|---|
| `kosctl install`, `install apps [--only]`, `install lockscreen`, `start`, `update`, `doctor` | plan/manage | yes |
| `kosctl deps`, `deps --install` | plan/manage | **no** (local branch only) |
| `kos-state.py list/snapshots --json`, verb calls | manage | **no** (local branch only) |
| `install-debian13.sh --local` | plan | **no** (local branch only) |
| `source-release.py latest/select` | plan | `latest` yes, `select` yes |

Against upstream `main` the dependency probe and the management screens therefore degrade to
empty. This is a product-side gap, not an installer bug.

## 9. Verified state

- `python3 -m unittest discover -s tests` → 134 tests, offline (bare repositories, `file://`).
- Host: `./install.sh --root <checkout> --check` → `KOS Installer — CachyOS (x86_64)`, exit 0.
- VM `arch-clean` (fresh Arch + Plasma 6.8/Wayland): installer cloned from GitHub and ran;
  `--check` and the TUI rendered; `kosctl deps` reported 10 missing packages;
  `kos-state.py list --json` → `{"schema":1,"units":{}}`;
  `source-release.py select main` fetched and detached to `3fa1d70`; a dirty tree was refused.

## 10. Known gaps

- No Textual UI, no `core/` or `backend/` layer, no backend contract, no CLI subcommands.
- No `pyproject.toml`, no release artefact, no self-update, no CI.
- Preparation is not wired into the flow (Phase 3b in progress).
- The curses UI is one 1600-line module; `render/screens/` was deliberately not split.
