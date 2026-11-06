# Migration plan and status

The independent installer is implemented on `main`; this file tracks what is
still open. The current tree is described in `CURRENT_ARCHITECTURE.md`. The
original proposal is `design.md`, kept as history.

## Done

- The installer is its own repository. It has no product source tree and no
  product Python imports; the product checkout is an input.
- Textual is vendored (`tools/vendor.py` → `vendor/`) and is the interactive
  entry point. `--plain` remains the non-TTY / missing-Textual path; the curses
  UI is gone.
- The wizard covers Welcome → Checks → Options → Review → Confirm → Installation
  → Result, with the management area, help, about and local-path dialogs.
- Source resolution: `stable` (newest `release/X.Y` branch), `main`, `local`;
  managed workspaces under `$XDG_DATA_HOME/nextkde/sources/`; a local checkout
  is read, never written. A release tag on the resolved commit is shown beside
  the ref in Review/Confirm/`--check`.
- Missing build packages are shown on Checks and Confirm; a list first found
  after the clone is confirmed on the installation page before the plan runs.
- The plan is capability-filtered from the backend contract; the installer side
  of the contract (`installer/backend/`) is complete and tested.
- Settings remember `lang` and `source`; CLI/config override them; tests and
  embedders do not write the user's file.
- The inline sudo bar answers one blocked askpass request at a time; no modal,
  no upfront password, no password in logs/argv.
- UI details were tightened: per-probe and per-option explanations, the OS
  install-path note, the 2-row sudo bar aligned with the log, the progress bar
  against the stage list, and Review's “提示” section with `j/k`/`g/G` scrolling.
- `ctrl+p` opens Textual's command palette. Installer commands are deliberately
  not injected yet.

## Current shape

`installer/` still keeps `plan.py`, `detect.py` and `runner.py` at the top
level; `core/` holds events/session/askpass, `backend/` holds the contract and
probe, and `source/` holds the Git manager. The original proposal's
`core/plan.py`, `system/detect.py` and `runner/` split is not complete, and it
is not blocking anything.

## Open work

1. **Product-side contract.** Add `packaging/installer-contract.json` and
   `kosctl installer-info --json` to the product. Until then a checkout reports
   `Backend: probe · N capabilities`.
2. **Palette integration.** Add installer commands to Textual's palette (or
   restore a key for the custom menu), so the management area is reachable
   again. The custom menu code and its tests exist; only the binding is gone.
3. **Release and self-update.** Versioned tarball with `vendor/`, SHA256,
   `current` symlink, rollback; CI that runs the offline suite and verifies the
   vendored pins.
4. **Product-side backend tools.** `kosctl deps` / `deps --install` and
   `tools/kos-state.py` are absent from the product's `main`; the dependency
   probe and the management actions are empty there.
5. **Optional layout split.** Move `plan.py`, `detect.py` and `runner.py` under
   `core/`/`system/` only if the churn buys something; the current layout is
   coherent.

## Historical milestones

The implementation stages T1–T4 (Textual shell, wizard, management area,
curses removal) and phases 3b/4/5/8 are recorded in the git history and in the
previous revisions of this file. The important outcome is the one above: the
installer is independent, Textual is the UI, and `--plain` is the fallback.
