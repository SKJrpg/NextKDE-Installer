# Current architecture

What this repository is on `main`. This file is written from the code: every
claim below is something the tree does. `docs/design.md` is the original
proposal and is historical; when the two disagree, this file and the code win.

## 1. What the installer is

A standalone Python program that installs NextKDE. It owns the wizard, the
system checks, the source choice, the plan and the logs. It does **not** build
or deploy the desktop: that stays in the product checkout's `tools/kosctl`,
`tools/install-debian13.sh` and `tools/kos-state.py`.

The product checkout is an input (`--root`, `KOS_ROOT`, default `~/NextKde`),
never inferred from the installer's own location. A local install may instead
use the checkout chosen on Options (`Options.local_path`), detected from
`--root` / `KOS_ROOT`, the current directory, `~/Projects/NextKde` and
`~/NextKde`, or typed with `ctrl+e`.

## 2. Layout

```
install.sh              Python >= 3.10 check, then `python3 -m installer`
tools/vendor.py         unpacks the pinned wheels (Textual, rich, deps) into vendor/
installer/
  __init__.py           VERSION
  __main__.py           argparse, config file, plan, entry-point choice, exit codes
  paths.py              Paths: installer_root, source_root, build_root, state_root,
                        log_dir, settings_file, sources_root
  detect.py             /etc/os-release parsing, family map, 9 probes + packages
  plan.py               Options -> [Step]; source/components/start ordering; argv only
  runner.py             StepRunner: argv, process group, streamed output, cancel
  manage.py             reads the ledger/snapshots/logs/deps through the product's tools
  settings.py           remembered language/source (XDG state, not install state)
  strings.py            zh/en pairs, locale choice, CJK font probe
  backend/
    models.py           capability names, BackendInfo, BackendIncompatible, require()
    contract.py         packaging/installer-contract.json, then kosctl installer-info
    probe.py            capabilities evidenced by the checkout's files and usage
  source/               Git Source Manager (section 5)
  core/
    events.py           Event: one classified line or state change from a worker
    session.py          InstallSession: runs the plan, reports events, cancels
    askpass.py          sudo shim + askpass helper: one answer per blocked sudo call
  ui/
    app.py              KosApp: wizard state, workers, palette, settings, cancel/quit
    keymap.py           the one key table; footers and help resolve from it
    theme.py            resolve_mode: --theme / KOS_THEME -> dark|light; dark default
    theme/app.tcss      the stylesheet: chrome, sidebar, lists, dialogs, sudo bar
    screens/            welcome, system, options, review, confirm, installation,
                        result, and the management area
    widgets/            footer, help, confirm, about, local path, sudo bar
  render/
    plain.py            the same plan without a TTY; NO_COLOR aware
tests/                  offline unit tests (tests/, tests/core/, tests/ui/)
vendor/                 pinned Textual 8.2.8 + rich and its dependencies
docs/                   current architecture, backend contract, keys, history
```

`installer/ui/` is the only module that owns terminal state; everything it
shows comes from `detect`, `plan`, `manage` and `runner`.

## 3. Startup and flow

```
install.sh
  └─ python3 -m installer [flags]
       ├─ Paths.resolve(--root)
       ├─ settings.load()                  # remembered language/source
       ├─ detect(root=source_root)         # probes, including `kosctl doctor`
       ├─ backend contract read/probe      # contract.read(root) or probe.detect(root)
       ├─ Options from CLI + JSON config
       ├─ build_plan(..., backend=info)    # capability-filtered argv, nothing run
       └─ Textual UI (TTY and vendor/ has textual) | plain (no TTY, --plain, --yes,
          or textual missing — it says so on stderr)
             └─ on confirm: workflow.begin() -> stream the clone -> finish()
                -> re-detect backend from the workspace
                -> build_plan(..., prepared=..., backend=...)
```

`--check` is read-only. It resolves the source identity (a network read),
prints the plan, then one backend line: `Backend: probe · N capabilities` or
`Backend: contract v1`. It returns 0 when nothing is blocked, 2 when a probe
fails or the backend cannot honour the selection; the plain executor returns
the failing step's status, 130 when cancelled.

## 4. Detection and checks

`detect()` parses `/etc/os-release`, maps the distribution to a family
(`debian`, `ubuntu`, `arch`, `fedora`, `opensuse`, `nixos` or none) and a method
(`wrapper`, `kosctl`, `report`, `nixos` or `unknown`). Its probes are:

| Probe | What it reads | Status rule |
|---|---|---|
| `probe_os` | `/etc/os-release` | PASS when an ID exists |
| `probe_arch` | `platform.machine()` | PASS for `x86_64` / `aarch64`, otherwise WARN |
| `probe_manager` | `apt-get`, `pacman`, `dnf`, `zypper` on `PATH` | PASS when one exists |
| `probe_plasma` | `plasmashell --version` | PASS at 6.x or newer |
| `probe_graphics` | `XDG_SESSION_TYPE` / `WAYLAND_DISPLAY` | PASS in a Wayland session |
| `probe_kwin` | `kwin_wayland --version` | PASS at 6.6 or newer |
| `probe_quickshell` | `qs` / `quickshell` version | PASS for 0.3.x; WARN otherwise |
| `probe_qt` | `qmake6` / `qtpaths6` / `pkg-config Qt6Core` | PASS at 6.6 or newer; WARN otherwise |
| `probe_disk` | `shutil.disk_usage($HOME)` | PASS at 6 GiB free |
| `probe_packages` | `kosctl doctor` on `--root` or the newest prepared workspace | WARN with the missing package list; PASS when none are missing. Kept for Confirm/plan; not listed on Checks. |

`System.blocked` is true when any probe is FAIL. The Checks screen shows
PASS/WARN/FAIL as words and glyphs, never colour alone. Its detail column has
`检查内容 / 状态 / 检测结果 / 说明`; the “说明” line is generated per probe:
`probe_os` uses the detected family's note (`Arch 系，使用 kosctl`,
`Debian 系，使用 install-debian13.sh`, …), while the version probes state only
the required version.

## 5. Options, settings and source preparation

`Options` is the single wizard state object: `source`, `apps`, `app_set`,
`lockscreen`, `spatial`, `start`, `proxy`, `local_path`. The available sources
are `main` and `local`; `stable` is in `resolver.DISABLED_SOURCES` while its
release branch has a known bug. The Options row is disabled with a
“temporarily unavailable” suffix, `--source stable` is rejected, and a
remembered `stable` falls back to `DEFAULT_SOURCE` (`main`).

Settings are separate from installation state: `settings.load()` reads
`<state_root>/settings.json` and accepts only `lang` in `zh|en` and `source` in
`stable|main|local`. The real CLI passes `remember=True` to `KosApp`, so
changing the language or source updates that file; `--plain`, tests and
embedders pass `remember=False`. CLI flags and the JSON config override the
remembered values.

`installer/source/` resolves a mode to exactly one commit and one immutable
workspace:

| Mode | Meaning | Git writes |
|---|---|---|
| stable | **temporarily sealed** (`DISABLED_SOURCES`); the code still resolves the newest `release/X.Y` branch when re-enabled | clone only |
| development | the `main` branch of that repository | clone only |
| local | the checkout chosen on Options, else `--root`, as it is | none: no fetch, checkout, reset or remote edit |

- The ref is resolved with `git ls-remote` **before** anything is cloned; the
  commit is the identity. `stable` lists `refs/heads/release/*` and takes the
  highest `X.Y`, so a fix on the maintained release branch installs before its
  tag exists; no GitHub API is involved.
- Managed workspaces: `<XDG_DATA_HOME>/nextkde/sources/<repository-id>/<commit>/`,
  cloned `--depth 1` into `<commit>.tmp`, HEAD verified, `source.json` written,
  then renamed into place. A prepared commit is never rewritten.
- Reuse requires the directory's HEAD and the manifest's repository to match;
  otherwise the error says to remove it.
- `manager.inspect_local(path)` is the one local validation: top of a work tree,
  `tools/kosctl` present, at least one commit; it reads branch, commit, origin
  and dirty state and writes nothing. `manager.detect_local()` tries the
  candidates above through it; `$HOME` itself is never scanned.
- `workflow.begin()` returns a `Preparation`: already prepared for local or a
  reused workspace, otherwise one streamable clone step. `finish()` verifies,
  records and renames. `plan.build_plan(..., prepared=...)` runs every step
  inside that workspace and emits no `kosctl update`; `--check` resolves the
  identity read-only.
- Version display: when a release `vX.Y.Z` tag points at the resolved commit,
  Review, Confirm and `--check` show it beside the ref (`release/0.1
  (v0.1.1)`). The install target remains the branch, so a later fix on the
  branch installs before its next tag.
- Package state: `detect()` runs `kosctl doctor` on `--root` when it is a
  product checkout, otherwise on the newest prepared workspace under
  `sources_root`, and keeps the missing `miss pkg:` names. Confirm shows the
  list; Checks does not. After a clone, `deps_report(prepared.path)` runs again;
  a list the user has not seen returns to Review, so the next Confirm shows it
  before the plan starts.
- Stable caveat (for when the channel is re-enabled): the `release/X.Y`
  branch's `kosctl install` does not install build dependencies. The installer
  adds a separate `kosctl deps --install` step when the backend declares it, or
  drives `pacman -S --needed` on Arch; users installing from `stable` must
  still verify the build packages themselves.

## 6. The plan

`plan.build_plan()` returns `Step(key, title, argv, env, note, input)` objects.
Nothing else executes commands. Today's steps:

| Family | Steps |
|---|---|
| debian | `install-debian13.sh --dir <root> --spatial … [--repo <origin>] [--local]`, then apps/lockscreen, then `start` |
| nixos | `kosctl nix install`, then `start` |
| arch / ubuntu / fedora | `kosctl update <ref>` only when nothing was prepared; `kosctl deps --install` first when the probe found missing packages and the backend declares it, else on Arch an installer-owned `pacman -S --needed` with the missing list; then `kosctl install`, `kosctl install apps [--only …]`, `kosctl install lockscreen`, `kosctl start` inside the prepared workspace |
| opensuse / unknown | nothing; the UI reports only |

`KOS_BUILD_SPATIAL=ON|OFF` and the proxy/session variables are placed in each
step's env. A step's `input` is written once to the child's stdin: the user
already confirmed the package list in the UI, so this answers the package
manager's one prompt without `--noconfirm`. `paths.build_root` is defined but
deliberately not exported yet: the backend's handling of `KOS_BUILD_DIR` /
`KOS_APPS_BUILD_DIR` is unverified.

## 7. Textual UI

### 7.1 Chrome and screens

`KosApp` owns `opts`, the prepared source, the steps, the detected system, the
backend and the run state. Every wizard screen is a `WizardScreen`: Header,
the fixed step sidebar, the body in `#main`, then the inline sudo bar and the
footer. The management area is a `ChromeScreen` without the sidebar.

Screens: Welcome, Checks, Options, Review, Confirm, Installation, Result, plus
the management area (Management, Units, Snapshots, Logs, LogViewer) and the
modal Help, About, ConfirmDialog and LocalPathDialog.

### 7.2 Keys, footer and help

`keymap.py` is the one key table. Each screen declares a context; the focused
widget may add its own. `keymap.resolve()` feeds the Textual bindings, the
one-line footer and the `ctrl+k` overlay, so the three cannot disagree. Config
`keys` can override an action.

- `Tab` / `Shift+Tab` page the wizard; `Esc` is the back alias.
- `j/k`, `h/l` and `g/G` are Vim aliases on existing actions.
- `ctrl+c` twice quits (first press warns); `ctrl+z` aborts a run; `ctrl+k`
  opens help.
- Confirm is a two-key page: `y` installs, `n` goes back; Enter, Tab, arrows,
  digits and Vim keys are inert.

### 7.3 Command palette

`KosApp.ENABLE_COMMAND_PALETTE = True`, so `ctrl+p` opens Textual's own
`CommandPalette` (Keys, Quit, Screenshot, Theme; Maximize/Minimize when a
focusable widget allows). The installer's own commands are deliberately **not**
injected yet. The old `widgets/commands.py` menu is retained but unreachable
from `ctrl+p`; management tests open their screens directly. Until installer
commands are added to the palette, the management area has no wizard key.

### 7.4 Checks and Options detail

At 110 columns and wider, Checks and Options put a detail column beside their
list; below that the detail stacks under the list (and is hidden on a short
Options page so the form keeps its rows). The Checks detail follows the
selected probe; the Options detail follows the focused row. Every selectable
Options row is mapped in `DETAILS`, so sources, apps, core and advanced rows
each have their own string instead of a shared paragraph.

### 7.5 Sudo bar

The bar sits above the footer and is never a modal. It has two rows: the reason
(`安装软件包和构建环境需要 root`) with the `⏎ 继续 · esc 取消` hint, then the
no-echo input row. Its content starts at the same column as the main content
(the log's left edge on wizard pages); the hint is hidden below 80 columns so
the reason stays on one line. `Esc` denies; `Enter` submits; one request is
shown at a time. The package list confirmed on Confirm is written to the
package step's `input`, so pacman's one prompt is answered without a second
question.

### 7.6 Confirm, Installation, Review and Result

- Confirm: the source/path summary, the missing build packages and the Y/N
  prompt. The summary is scrollable; the prompt stays visible. A package list
  discovered after the clone returns to Review so the next Confirm shows it.
- Installation: stage list (done/current/waiting/failed/skipped), a progress bar
  directly under the stages, one blank row before the log, and the live wrapping
  log. `ctrl+z` aborts immediately; there is no log-pause key.
- Review: summary, the real plan, `ctrl+e` to expand commands, and a “提示”
  section. The page is scrollable with `↑/↓`, `j/k` and `g/G`. On a failed
  preparation it swaps to `ctrl+r` retry / `ctrl+l` log.
- Result: the success body repeats the `kosctl install` close-out — log out and
  back in (or reboot), `kosctl start` to apply now when the start step did not
  run, and the next-login note for KWin effects/takeover. `q` quits, `ctrl+r`
  retries when the run did not succeed, `ctrl+l` opens the log.

## 8. Process execution and sudo

`StepRunner` runs an argv list with `start_new_session=True`, streams
stdout+stderr through a selector, classifies lines, and writes them to the run
log. `cancel()` signals the process group with SIGTERM and escalates to SIGKILL
after five seconds; `close()` always waits. No `shell=True` anywhere.

The install children get no tty, so `core/askpass.py` gives each run a private
`0700` directory (under `XDG_RUNTIME_DIR`, `/tmp` as fallback) holding a `sudo`
shim and an `askpass.sh` helper; the session merges `PATH` (the directory first)
and `SUDO_ASKPASS` into every step's env. The shim adds `-A`; the helper creates
`pending.<token>`, polls for `answer.<token>`, prints that file once, and
removes both. The UI polls `pending()` every 150 ms and shows the bar on the
screen that is already running (Installation or the management list); a request
that arrives while the bar is up waits for the next one. A modal on top hides
the bar, so the request waits until it closes.

Nothing is asked at startup and nothing is asked when `sudo -n true` already
works. A full install asks once for the build packages and once for the KWin
system plugins after the build, like running `kosctl` by hand. Denying cancels
the run; the step fails and the result screen says the password was not
provided. `--plain` / `--yes` ask once with `getpass` when stdin is a tty;
without one they need a primed `sudo -v` and exit 2 before starting.

## 9. Backend contract

The capability each call needs is declared in `installer/backend/models.py`; a
backend that does not declare it never receives the step
(`docs/BACKEND_CONTRACT.md`). `contract.read()` prefers the static
`packaging/installer-contract.json`, then `kosctl installer-info --json` when
the usage text advertises it. Falling back to `probe.detect()` derives only
what the checkout evidences. An incompatible `installer_api` stops before
Review (and again before the install if preparation finds a different
checkout). The product side is still pending. Against upstream `main` the
management screens therefore degrade to empty. The dependency probe still
works: it reads `kosctl doctor`, and on Arch the installer can install the
missing packages itself when the backend has no `deps` verb.

## 10. Plain mode

`render/plain.py` is the non-TTY path (`--check`, `--yes`, `--plain`, or no
Textual). It uses the same `strings`, `plan`, `detect` and exit codes, keeps the
same headings and explicit PASS/WARN/FAIL labels, and honours `NO_COLOR`. The
plain executor owns source preparation and the run; it writes the password to
the askpass answer before the run instead of asking mid-run.

## 11. Tests, state and known gaps

Test command:

```sh
PYTHONPATH=$PWD/vendor python3 -m unittest discover -s tests
```

The suite is offline: temporary repositories, `file://` remotes, no network.
Textual tests skip when `vendor/` is missing. Settings and logs are isolated
with a throwaway `XDG_STATE_HOME` in the tests.

Verified on real machines:

- Host: `./install.sh --root <checkout> --check` and `… --plain --check` print
  `KOS Installer — CachyOS (x86_64)`, exit 0, and clone nothing.
- VM `arch-clean` (fresh Arch + Plasma 6.8/Wayland): the installer cloned and
  the TUI rendered; `kosctl deps` reported 10 missing packages; `kos-state.py
  list --json` returned an empty ledger; a dirty tree was refused.
- VM `arch-kde` (Arch/Plasma 6.8.2 Wayland): the TUI resolved stable to
  `release/0.1` (`v0.1.1`, `2ca59a1f`), showed seven missing build packages on
  Confirm, installed them after the inline sudo prompt, then
  `kosctl install` and `kosctl start` both succeeded; `kosctl version` reported
  `0.1.1`.

Known gaps:

- The backend contract is implemented on the installer side only: the product
  ships neither `packaging/installer-contract.json` nor
  `kosctl installer-info`, so `--check` reports `Backend: probe · N
  capabilities`.
- `stable` is temporarily sealed off because of a release-branch bug: the
  Options row is disabled, `--source stable` is rejected, and a remembered
  value falls back to `main`.
- Installer commands are not in Textual's palette yet; the management area has
  no wizard key until they are.
- `kosctl deps` / `deps --install` and `tools/kos-state.py` are missing
  upstream. The dependency probe still reads `kosctl doctor`, and on Arch the
  installer's own `pacman -S --needed` step covers the build packages; the
  management unit/snapshot actions are empty against `main`.
- No release artefact, self-update or CI. `paths.build_root` is defined but not
  passed to the backend (`KOS_BUILD_DIR` unverified).
