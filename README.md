# NextKDE Installer

A standalone installer for NextKDE. It owns the wizard, the system checks, the
source choice, the install plan and the logs. It does **not** build or deploy
the desktop: that stays in the product checkout's `tools/kosctl`,
`tools/install-debian13.sh` and `tools/kos-state.py`.

The installer is independent of the product repository. The product checkout is
an input (`--root` / `KOS_ROOT`, default `~/NextKde`), never inferred from the
installer's own location. `stable` and `main` fetch their own managed workspace;
only `local` installs from that checkout.

## Requirements

- Linux with KDE Plasma 6 on Wayland (the wizard checks this)
- Python 3.10+ — the runtime is the standard library plus the vendored Textual
  tree; there is nothing to `pip install`
- Git

The interactive UI is Textual, vendored under `vendor/`. Without `vendor/` the
same plan still runs, but the wizard falls back to the plain renderer.

## Quick start

From a machine that only has git and Python 3.10+:

```sh
curl -fsSL https://raw.githubusercontent.com/SKJrpg/NextKDE-Installer/main/install.sh | bash
```

The script clones this repository into `~/NextKde-Installer`, builds the
vendored UI once, and starts the wizard. `KOS_INSTALLER_DIR`,
`KOS_INSTALLER_REF` and `KOS_INSTALLER_REPO` override the three choices.

From a checkout:

```sh
python3 tools/vendor.py     # once: unpack the pinned wheels into vendor/
./install.sh
```

Useful non-interactive runs:

```sh
./install.sh --root ~/NextKde --check     # probes + the plan, changes nothing
./install.sh --root ~/NextKde --plain     # no TUI, run the plan
```

## The wizard

The flow is linear:

```
Welcome -> Checks -> Options -> Review -> Confirm -> Installation -> Result
```

| Screen | What it shows | Primary keys |
|---|---|---|
| Welcome | Product name, detected distribution/architecture/session, language | `←/→` or `h/l` language, `Tab` next |
| Checks | 9 environment probes plus build packages when a checkout is available; PASS/WARN/FAIL text, the detected value and a per-check explanation | `↑/↓` or `j/k` select, `ctrl+r` re-check, `Tab` next |
| Options | Source (`stable` / `main` / `local`), required core, optional apps, lock screen, depth wallpaper, start after install | `↑/↓` or `j/k` move, `Enter` down/activate, `Space` toggle, `ctrl+e` local path, `Tab` next |
| Review | Summary, the real plan, the full command toggle and notes | `↑/↓` or `j/k` scroll, `g/G` top/bottom, `Enter` continue, `ctrl+e` commands, `ctrl+l` log on failure |
| Confirm | The final install gate | `y` install, `n` back; everything else is inert |
| Installation | Stage list, progress and the live log | `ctrl+z` abort, `ctrl+k` help |
| Result | Success/failure, one-line next step | `q` quit, `ctrl+r` retry, `ctrl+l` log |

Global keys: `Tab` / `Shift+Tab` page forward/back through the wizard, `Esc`
goes back, `ctrl+k` opens help, and `ctrl+c` twice quits (the first press only
warns). The footer always paints the keys that are live on the current screen.

`ctrl+p` opens **Textual's own command palette** (Keys, Quit, Screenshot, Theme,
and Maximize/Minimize where a focusable widget allows it). The installer's own
commands are not injected into that palette yet; the management screens can
currently only be opened by code/tests, not by a wizard key.

### Checks, Options and Review details

- The Checks detail column follows the selected row. Its “说明 / Notes” line is
  written per check: the OS note names the detected family and install path
  (for example `Arch 系，使用 kosctl`); Plasma, KWin and Qt state the required
  version and “or newer”, while Quickshell states the required 0.3.x series.
- Every source and every optional app has its own description; the right column
  never repeats a generic “stable vs main vs local” block.
- Missing build packages are shown on Checks and repeated on Confirm; a list
  first discovered after the clone is confirmed on the installation page before
  anything runs.
- Review's notes section is titled “提示 / Notes”. On a failed preparation,
  `ctrl+r` retries, `ctrl+l` opens the log, and the page keeps its scroll keys.

## Command line

There are no subcommands by design: the installer obtains the source, chooses
the distribution path and checks the backend; everything after that is
`kosctl`'s job.

| Flag | Meaning |
|---|---|
| `--root DIR` | Product checkout (default `$KOS_ROOT` or `~/NextKde`) |
| `--check` | Probe and print the plan; change nothing |
| `--plain` | Force the plain renderer |
| `--yes` | Non-interactive: accept the plan |
| `--config FILE` | JSON options file |
| `--lang zh\|en` | UI language |
| `--source stable\|main\|local` | Source channel |
| `--theme system\|dark\|light` | Terminal appearance; dark is the default |
| `--apps [LIST]` | Also install the optional apps; `calendar,todo,weather,calculator` narrows the set |
| `--lockscreen` | Also install the lock screen theme |
| `--start` / `--no-start` | Start services after install (default on) |
| `--all` | Apps and lock screen together |
| `--no-proxy` | Do not pass proxy variables through |
| `--version` | Print the installer version |

`--config` understands `source`, `apps` (list or bool), `lockscreen`, `start`,
`proxy`, `spatial`, `theme`, `keys`, and the `components` alias for
`apps`/`lockscreen`. CLI flags win over the config, and both win over the
remembered source.

Exit codes: `0` success, `1` a step failed, `2` blocked / unsupported /
incompatible backend, `130` cancelled.

Examples:

```sh
./install.sh --source stable --apps todo --start
./install.sh --check --root ~/NextKde
./install.sh --plain --yes --source local
```

## Sources and workspaces

| Channel | Ref | What is written |
|---|---|---|
| `stable` | newest `release/X.Y` branch of the product repository | a managed clone |
| `main` | tip of the product's `main` branch | a managed clone |
| `local` | the checkout chosen on Options, else `--root` / `KOS_ROOT` | nothing: no fetch, checkout or reset |

`stable` follows the maintained `release/X.Y` branch tip, so a fix on that
branch is installable before its tag exists. When the resolved commit already
has a release tag, Review and Confirm show it beside the ref.

Managed workspaces live under
`$XDG_DATA_HOME/nextkde/sources/<repository-id>/<commit>/`. A prepared commit is
never rewritten. `--check` resolves the identity read-only; nothing is cloned.

The local checkout is detected from `--root` / `KOS_ROOT`, the current
directory, `~/Projects/NextKde` and `~/NextKde`, or typed with `ctrl+e`. The
installer never scans all of `$HOME` and never edits a local checkout.

## Settings and state

Language and source are remembered between interactive runs:

```text
~/.local/state/nextkde-installer/settings.json
```

Only `zh`/`en` and `stable`/`main`/`local` are stored. A CLI flag or the config
file overrides the remembered value; `--plain`, tests and embedders do not
write the file. Logs go to `~/.local/state/nextkde-installer/logs/`; managed
sources go to `~/.local/share/nextkde/sources/`.

Appearance is dark by default. `--theme system` follows the terminal's reported
background; `--theme light` overrides a terminal that does not report it. The
wizard has no theme menu: the flag, config `theme`, and `KOS_THEME` are the
whole interface.

## sudo

Nothing asks for a password up front. Install children run without a tty, so the
installer puts a `sudo` shim and an askpass helper on their `PATH`. When a
step's `sudo` needs a password, the helper leaves a request and blocks; the
wizard shows one inline bar above the footer (never a popup). The bar has two
rows: the reason and the `⏎ 继续 · esc 取消` hint, then the no-echo password
field. Its content starts at the same column as the log.

The answer is written to one file only this user can read, used for that `sudo`
call, and removed as soon as sudo reads it; it never reaches the log, argv or
the result screen. `Esc` denies the password: that request and every later one
fail at once, the step fails, and the result says the password was not
provided. Priming sudo first (`sudo -v`) avoids the prompt entirely for the
following minutes.

`--plain` and `--yes` have no event loop to answer a request mid-run, so they
ask once with `getpass` when stdin is a tty; without one they need a primed
`sudo -v` and exit 2 before starting anything.

## Development

```sh
python3 tools/vendor.py
PYTHONPATH=$PWD/vendor python3 -m unittest discover -s tests
```

The suite is offline: it uses temporary repositories and `file://` remotes.
Textual tests skip when `vendor/` is missing.

Layout:

```text
installer/          detection, plan, runner, source manager, backend contract
installer/ui/       Textual app, screens, widgets, keymap and stylesheet
installer/render/   plain renderer for non-TTY / --check / --plain
tests/              unit tests, including Textual Pilot tests
tools/vendor.py     builds vendor/ from the pinned wheels
docs/               current architecture, backend contract, keys and history
```

Docs map:

- `docs/CURRENT_ARCHITECTURE.md` — the source of truth for the current tree
- `docs/BACKEND_CONTRACT.md` — capability names, contract shapes and probing
- `docs/KEYMAP.md` — current keys and the change history
- `docs/MIGRATION_PLAN.md` — status and remaining work
- `docs/design.md` — the original architecture proposal (historical; it
  predates the Textual port)

## Status

- The Textual wizard is the interactive entry point; the curses UI is gone and
  `--plain` covers non-TTY and missing-Textual runs.
- The backend contract is implemented on the installer side. The product still
  does not ship `packaging/installer-contract.json` or
  `kosctl installer-info --json`, so a checkout reports a probed capability set.
- `kosctl deps` / `deps --install` and `tools/kos-state.py` are not present in
  the product's `main`. The dependency probe still reads `kosctl doctor`, and on
  Arch the installer's own `pacman -S --needed` step covers build packages;
  unit/snapshot management degrades to empty.
- Installer commands are not in Textual's palette yet, so the management area
  has no wizard key right now.
- No release artefact, self-update or CI yet; `pyproject.toml` declares the
  console script, and `paths.build_root` is defined but not passed to the
  backend (`KOS_BUILD_DIR` is unverified).
