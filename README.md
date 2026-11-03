# NextKDE Installer

Standalone installer for NextKDE. It owns the wizard, the system checks, the
source choice and the install plan; it does not own building or deploying the
desktop — `tools/kosctl` in the product checkout does that.

## Requirements

- Linux with KDE Plasma 6 on Wayland (the installer checks this)
- Python 3.10+, standard library plus the vendored Textual tree — there is nothing
  to `pip install`
- Git

## Run

```sh
python3 tools/vendor.py          # once: unpacks the pinned wheels into vendor/
./install.sh --root ~/NextKde
```

The interactive UI is Textual, vendored under `vendor/` and put on `PYTHONPATH` by
`install.sh`; without it an interactive run says so and falls back to plain output.

```sh
./install.sh --root ~/NextKde --check        # report and plan only, changes nothing
./install.sh --root ~/NextKde --plain        # no interactive UI, runs the plan
```

`--root` (or `KOS_ROOT`) names the product checkout; it defaults to
`~/NextKde`. The installer never changes the product checkout on its own:
`local` keeps it as it is, `stable`/`main` only fetch when the tree is clean
and you picked that source.

Flags: `--check` report only, `--plain` no interactive UI, `--yes`, `--config FILE`,
`--source stable|main|local`, `--apps [LIST]`, `--lockscreen`, `--all`,
`--start`, `--no-proxy`, `--lang zh|en`.

## Layout

```
installer/      the installer: detection, plan, runner, source manager,
                the Textual UI (installer/ui/) and the plain renderer
tests/          python3 -m unittest discover -s tests
tools/vendor.py builds vendor/ (Textual + its dependencies, pinned)
docs/           design and architecture notes
```

## Status

The Textual wizard is the interactive entry point (stages T1–T4 of
`docs/MIGRATION_PLAN.md`); the curses UI is gone and `--plain` covers non-TTY and
missing-Textual runs. No release artefact or self-update yet. The product still
ships its own copy of the wizard until this repository is released and the old
entry point points here.
