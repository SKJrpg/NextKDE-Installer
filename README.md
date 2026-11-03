# NextKDE Installer

Standalone installer for NextKDE. It owns the wizard, the system checks, the
source choice and the install plan; it does not own building or deploying the
desktop — `tools/kosctl` in the product checkout does that.

## Requirements

- Linux with KDE Plasma 6 on Wayland (the installer checks this)
- Python 3.10+, standard library only — there is nothing to `pip install`
- Git

## Run

```sh
./install.sh --root ~/NextKde
```

`--root` (or `KOS_ROOT`) names the product checkout; it defaults to
`~/NextKde`. The installer never changes the product checkout on its own:
`local` keeps it as it is, `stable`/`main` only fetch when the tree is clean
and you picked that source.

Flags: `--check` report only, `--plain` no curses, `--yes`, `--config FILE`,
`--source stable|main|local`, `--apps [LIST]`, `--lockscreen`, `--all`,
`--start`, `--no-proxy`, `--lang zh|en`.

## Layout

```
installer/      the wizard: detection, plan, runner, unit/snapshot reader, renderers
tests/          python3 -m unittest discover -s tests
docs/design.md  architecture proposal for the split from the product repo
```

## Status

Extracted from the NextKDE repository with its history (Phase 1 of
`docs/design.md`). The product still ships its own copy of the wizard until
this repository is released and the old entry point points here.
