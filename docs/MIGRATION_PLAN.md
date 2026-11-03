# Migration plan

From the current curses installer (see `CURRENT_ARCHITECTURE.md`) to the independent,
Textual-based installer described in `design.md` and the implementation prompt.

## Decisions already taken

1. **Product repository** is `https://github.com/NextKde/NextKde.git` (the old `SuceV587`
   URL redirects there). `CANONICAL_REPO` and `design.md` name it; it does not change again.
2. **Textual is the target UI**, and its dependencies are **vendored** into the release
   (unpacked wheels under `vendor/`, `PYTHONPATH` prepended by `install.sh`). No pip, no venv,
   no PEP 668; wheels total ≈ 2.4 MB, ≈ 8–10 MB unpacked.
3. **curses is not kept as a fallback.** Textual replaces it; `plain` stays for non-TTY/CI.
   Two interactive renderers would double the tests and the layout work.
4. **Order**: finish Phase 3b (wire the source manager) first, then extract `core/`, then
   Textual. Source logic is UI-agnostic, so nothing built now is thrown away.

## Target layout and where today's files go

| Today | Target | Action |
|---|---|---|
| `installer/__main__.py` | `installer/cli.py` + `installer/__main__.py` | split argparse/subcommands from flow |
| `installer/plan.py` | `installer/core/plan.py` | move; no behaviour change |
| `installer/runner.py` | `installer/runner/process.py` (+ `events.py`, `cancellation.py`) | split; keep the argv contract |
| `installer/detect.py` | `installer/system/detect.py` | move |
| `installer/manage.py` | `installer/backend/kosctl.py` + `core/session.py` | split queries from the backend calls |
| `installer/paths.py` | `installer/config.py` (`PathManager`) | rename, same fields |
| `installer/source/*` | unchanged | already a package |
| `installer/render/curses_ui.py` | deleted | replaced by `installer/ui/` |
| `installer/render/{plain,theme,layout,widgets}.py` | `plain` keeps; the rest deleted | Textual owns layout and theme |
| `installer/strings.py` | unchanged | Textual widgets read the same pairs |
| `install.sh` | unchanged in interface | adds `vendor/` to `PYTHONPATH` |
| `tests/test_*.py` | `tests/{core,source,backend,runner,ui}/` | move; curses render tests replaced by Pilot tests |
| — | `backend/contract.py` | new: capability probe and compatibility check |
| — | `packaging/installer-contract.json` | **in the product repo** |
| — | `pyproject.toml`, `CHANGELOG.md`, `LICENSE`, CI | new |

## Phases

| Phase | Work | Acceptance |
|---|---|---|
| 3b (done, `77f816d`) | `workflow.begin()/finish()`, prepared source in the plan, Review shows identity, `--check` stays read-only | done: 146 tests; `arch-clean` prepared `development` at `d7b34a8e` with one streamed clone and reused it with zero steps |
| 4 (done, logic) | stable/development/local resolution, managed workspaces, manifest | local never written; reuse verified; 19 offline tests |
| 2 | extract `core/` (workflow, plan, session, events, errors), `system/`, `backend/` | curses UI still runs on the extracted core; no test loss |
| 5 | backend contract: static `packaging/installer-contract.json` + `kosctl installer-info --json`; adapter checks capabilities before showing options | unsupported option never shown; incompatible backend stops with a clear error |
| 6 | Textual: `ui/app.py`, 8 screens, 6 widgets, `app.tcss`; workers for git/probes/install; Pilot tests | no blocking call in the event loop; cancel reaps the process group; narrow layout works at 66×20 |
| 7 | vendor build + versioned releases + SHA256 + `current` symlink + self-update | release installs offline; update never overwrites a running version; rollback works |
| 8 | delete `render/curses_ui.py` and its tests | full suite green; `--plain` unchanged |

Textual work is estimated at 2–3 weeks for one developer, split across the phases above.

## Product-side changes required (`NextKde/NextKde`)

These exist only on a local branch today; the installer needs them upstream before the
dependency probe and the management screens work against `main`:

1. `tools/kos-state.py` — unit ledger and snapshots (`list --json`, `snapshots --json`, verbs).
2. `kosctl deps` and `kosctl deps --install` — per-package `name=ok|miss` output.
3. `install-debian13.sh --local` — keep the current checkout instead of switching.
4. `install-apps.sh --only`, `register-default-apps.py`, `verify-apps-install.sh` — app subsets.
5. `packaging/installer-contract.json` and `kosctl installer-info --json` (new work).
6. `tools/install.sh` — either keep as a shim that starts this installer, or remove it once the
   installer repo is released; decide at Phase 7.

## Risks

- **Worker/thread discipline** in the Textual port: cross-thread messages, cancellation
  ordering, and logs arriving after a screen pops. Mitigation: one message type per event,
  the runner stays the only process owner, tests around cancel.
- **Child processes on UI exit**: today only unit-tested. Mitigation: a test that kills the app
  mid-install and asserts the process group is gone.
- **Terminal compatibility** of Textual (truecolor, narrow windows). Mitigation: keep `plain`
  for CI and non-TTY; verify at 66×20 in the VM.
- **Vendored dependency drift**: pin exact versions, ship `vendor/SHA256SUMS`, verify in CI.
- **Product/backend skew**: the contract check must fail loudly rather than guessing.
