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
    askpass.py          sudo shim + askpass helper: one answer per blocked sudo call
  ui/
    app.py              KosApp: wizard state (Options, prepared source, steps),
                        thread workers, cancel/quit
    theme.py            resolve_mode: --theme / KOS_THEME / COLORFGBG → dark|light
    theme/app.tcss      the stylesheet: chrome, sidebar, lists, dialogs
    screens/            welcome, system, options, review, installation, result,
                        and the management area (units, snapshots, logs, management)
    widgets/confirm.py  modal confirmation used by the destructive actions
    widgets/password.py modal that answers one blocked sudo call
  render/
    plain.py            the same plan without a TTY; NO_COLOR aware
tests/                  171 offline unit tests (tests/, tests/core/, tests/ui/)
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
| arch / ubuntu / fedora | `kosctl update <ref>` only when nothing was prepared; `kosctl deps --install` first when the probe found missing packages; then `kosctl install`, `kosctl install apps [--only …]`, `kosctl install lockscreen`, `kosctl start` inside the prepared workspace |
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
  system, options, review, confirm, installation, result) plus the management area
  (units, snapshots, logs, management); `widgets/confirm.py` is the modal confirmation;
  every style lives in `theme/app.tcss`. `keymap.py` is the one key table: each screen
  declares a context, and `keymap.resolve()` feeds the Textual bindings, the one-line
  hint bar and the `?` overlay, so the three cannot disagree (config `keys` overrides
  it). Esc only steps back, `q` is the only quit, and installing needs the confirmation
  page (`screens/confirm.py`) with "back" selected first.
- **Appearance**: the palette is the terminal's own (`ansi_color=True` and `ansi_default`
  in the stylesheet), so only the mode is resolved: `--theme`, then `theme` in the JSON
  config, then `KOS_THEME=dark|light`, then the background index of `COLORFGBG`
  (`0-6,8` dark, `7,9-15` light), otherwise dark. `theme.py` holds that; `KosApp` keeps
  it as `theme_mode`/`dark` and every screen takes its secondary text from
  `app.secondary_style` — `dim` on dark (the terminal dims its own foreground) and ANSI 8
  on light (a readable grey rather than a foreground faded towards white). Terminals that
  export no `COLORFGBG` (Konsole does not) fall back to dark; pass `--theme` there.
  Status colours, the modal's own surface and the focused row keep their styling.
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

### sudo, on demand

The install children get no tty, so `core/askpass.py` gives each run a private `0700`
directory (under `XDG_RUNTIME_DIR`, `/tmp` as fallback) holding a `sudo` shim and an
`askpass.sh` helper; the session merges `PATH` (the directory first) and `SUDO_ASKPASS` into
every step's env. The shim adds the `-A` sudo otherwise ignores. The helper is the only thing
that ever asks: it creates `pending.<token>`, polls every 100 ms for `answer.<token>` (hard
timeout 180 s), prints that file's contents once, and removes both. `Askpass.pending()` is
what the UI watches, `answer()` writes a `0600` file, and `cancel()` writes an empty answer
plus a `denied` marker so this and every later request fail immediately instead of sudo
asking three times. The flush of the whole password story: no password is written until a
request exists, and the answer is deleted as soon as sudo reads it.

`KosApp` polls `pending()` every 150 ms on the event loop and pushes `PasswordDialog` once
per request (never stacked; a request that arrives while a dialog is open is asked right
after it closes). So nothing is asked at startup and nothing is asked at all when `sudo -n
true` already works: a full install asks once for the build packages and once for the KWin
system plugins after the build, the way running `kosctl` by hand does. The request is the
only trigger, never the plan starting: dependencies that are already present produce no
early prompt (exactly one prompt, after the build), and a still-valid sudo timestamp
produces none at all. Denying cancels the run; the step fails and the result screen says
the password was not provided.
`--plain`/`--yes` have no event loop to answer requests mid-run, so they keep the up-front
`getpass` (with a tty) or exit 2 before starting (without one), and the password is written
before the run instead.

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

- `PYTHONPATH=$PWD/vendor python3 -m unittest discover -s tests` → 171 tests, offline
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
- No subcommands by design: the interface is flags (`--check`, `--plain`, `--yes`, `--source`, …); product operations stay in `kosctl` and are not wrapped again.
- No release artefact, self-update or CI; `pyproject.toml` exists and declares the console
  script only.
- `kosctl deps` and the `kos-state.py` verbs are missing upstream, so the dependency probe
  and the management screens are empty against `main`.
- `paths.build_root` is still not passed to the backend (`KOS_BUILD_DIR` unverified).
