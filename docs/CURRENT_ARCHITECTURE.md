# Current architecture

What this repository is today (branch `main`).
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
tools/vendor.py         unpacks the pinned wheels (Textual, rich, deps) into vendor/
installer/
  __init__.py           VERSION
  __main__.py           argparse, config file, plan, entry-point choice, exit codes
  paths.py              Paths: installer_root, source_root, build_root, state_root,
                        log_dir, sources_root, installer_runtime
  detect.py             /etc/os-release parsing, family map, 13 probes, blocked flag
  plan.py               Options -> [Step]; source/components/start ordering; argv only
  runner.py             StepRunner: argv, process group, streamed output, cancel
  manage.py             reads the ledger/snapshots/logs/deps through the product's tools
  strings.py            zh/en pairs, locale choice, CJK font probe
  backend/
    models.py           capability names, BackendInfo, BackendIncompatible, require()
    contract.py         packaging/installer-contract.json, then kosctl installer-info
    probe.py            capabilities evidenced by the checkout's files and usage
  source/               Git Source Manager (see section 5)
  core/
    events.py           Event: one classified line or state change from a worker
    session.py          InstallSession: runs the plan, reports events, cancels
  ui/
    app.py              KosApp: wizard state (Options, prepared source, steps),
                        thread workers, cancel/quit
    theme/app.tcss      the stylesheet: chrome, sidebar, lists, dialogs
    screens/            welcome, system, options, review, installation, result,
                        and the management area (units, snapshots, logs, management)
    widgets/confirm.py  modal confirmation used by the destructive actions
  render/
    plain.py            the same plan without a TTY; NO_COLOR aware
tests/                  133 offline unit tests (tests/, tests/core/, tests/ui/)
vendor/                 pinned Textual 8.2.8 + rich and its dependencies
docs/design.md          the independent-installer architecture proposal
docs/BACKEND_CONTRACT.md  capability names, contract shapes, probe fallback
```

`installer/ui/` is the only module that owns terminal state; everything it shows comes from
`detect`, `plan`, `manage` and `runner`.

## 3. Startup and flow

```
install.sh
  └─ python3 -m installer [flags]
       ├─ Paths.resolve(--root)
       ├─ detect(root=source_root)          # runs `kosctl doctor`, reads the guide
       ├─ backend contract read/probe       # contract.read(root) or probe.detect(root)
       ├─ Options from CLI + JSON config
       ├─ build_plan(..., backend=info)     # capability-filtered argv, nothing run
       └─ Textual UI (TTY and vendor/ has textual) | plain (no TTY, --plain, --yes,
          or textual missing — it says so on stderr)
            └─ on confirm: workflow.begin() -> stream the clone -> finish()
               -> re-detect backend from the workspace
               -> build_plan(..., prepared=..., backend=...)
```

Exit codes: `--check` returns 0 when nothing is blocked, 2 when a probe fails or the backend
cannot honour the selection; the plain executor returns the failing step's status, 130 when
cancelled.

`--check` is read-only. It runs probes (including `kosctl doctor`) and prints the plan,
then one backend line: `Backend: probe · N capabilities` or `Backend: contract v1`.

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

Two front ends, one plan:

- **Textual** (`installer/ui/`), vendored under `vendor/` and put on `PYTHONPATH` by
  `install.sh`. `KosApp` owns the wizard state (`opts`, prepared source, steps, cancel
  event) and holds the fixed chrome; `screens/` holds one `Screen` per step (welcome,
  system, options, review, installation, result) plus the management area (units,
  snapshots, logs, management); `widgets/confirm.py` is the modal confirmation; every
  style lives in `theme/app.tcss`. The step sidebar and the localized footer come from
  `screens/__init__.py`, so a screen only declares its body and its extra keys.
- **Workers**: preparation, the install and management actions run in
  `@work(thread=True)`. Every line they produce is a `core.events.Event` handed to the
  event loop with `call_from_thread`, so nothing blocks and a screen only ever shows what
  the runner reported. `action_quit` and `on_unmount` wait for the workers, so no install
  child outlives the UI.
- Install screen: stage list (done/current/waiting/failed/skipped), measured counters when
  the runner reports them, otherwise an explicit indeterminate bar; `p` pauses the log.
- `render/plain.py` is the non-TTY path (`--check`, `--yes`, `--plain`, no Textual): the
  same `strings`, `plan`, `detect` and exit codes, NO_COLOR aware.
- Status is text (`通过/注意/失败`, `PASS/WARN/FAIL`) plus colour, never colour alone.

## 7. Process execution

`StepRunner` runs an argv list with `start_new_session=True`, streams stdout+stderr through a
selector, classifies lines, and writes them to the run log. `cancel()` signals the process
group with SIGTERM and escalates to SIGKILL after five seconds; `close()` always waits, so the
child is reaped. No `shell=True` anywhere.

## 8. Backend surface actually used

The capability each call needs is declared in `installer/backend/models.py`; a
backend that does not declare it never receives the step (`docs/BACKEND_CONTRACT.md`).

| Call | Where | Present upstream? |
|---|---|---|
| `kosctl install`, `install apps [--only]`, `install lockscreen`, `start`, `update`, `doctor` | plan/manage | yes |
| `kosctl deps`, `deps --install` | plan/manage | **no** (local branch only) |
| `kos-state.py list/snapshots --json`, verb calls | manage | **no** (local branch only) |
| `install-debian13.sh --local` | plan | **no** (local branch only) |
| `source-release.py latest/select` | plan | `latest` yes, `select` yes |
| `packaging/installer-contract.json`, `kosctl installer-info --json` | backend | **no** (new work) |

Against upstream `main` the dependency probe and the management screens therefore degrade to
empty. This is a product-side gap, not an installer bug.

## 9. Verified state

- `PYTHONPATH=$PWD/vendor python3 -m unittest discover -s tests` → 133 tests, offline
  (bare repositories, `file://`); the Textual tests skip when `vendor/` is missing.
- Host: `./install.sh --root <checkout> --check` and `… --plain --check` →
  `KOS Installer — CachyOS (x86_64)`, exit 0, nothing cloned.
- Textual wizard captured in tmux at 100×30: Welcome and Options render inside the fixed
  chrome, Options shows the source, apps and advanced toggles.
- VM `arch-clean` (fresh Arch + Plasma 6.8/Wayland): installer cloned from GitHub and ran;
  `--check` and the TUI rendered; `kosctl deps` reported 10 missing packages;
  `kos-state.py list --json` → `{"schema":1,"units":{}}`;
  `source-release.py select main` fetched and detached to `3fa1d70`; a dirty tree was refused.

## 10. Known gaps

- The backend contract is implemented on the installer side only: the product still
  ships neither `packaging/installer-contract.json` nor `kosctl installer-info`, so
  `--check` reports `Backend: probe · N capabilities`. The probe is honest but narrow;
  the declared path (and its tests) exist and take over once the product ships a file.
- No CLI subcommands (`check`, `install`, `manage`): `__main__.py` is still one flow.
- No release artefact, self-update or CI; `pyproject.toml` exists and declares the console
  script only.
- `kosctl deps` and the `kos-state.py` verbs are missing upstream, so the dependency probe
  and the management screens are empty against `main`.
- `paths.build_root` is still not passed to the backend (`KOS_BUILD_DIR` unverified).
