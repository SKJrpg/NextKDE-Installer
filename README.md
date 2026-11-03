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
`--source stable|main|local`, `--theme system|dark|light`, `--apps [LIST]`,
`--lockscreen`, `--all`, `--start`, `--no-proxy`, `--lang zh|en`.

`--theme` picks how the wizard draws secondary text: `dark` dims the terminal's own
foreground, `light` uses its ANSI 8 grey. `system` (the default) detects the terminal:
the flag (`theme` in the JSON config) wins, then `KOS_THEME=dark|light`, then the
background index in `COLORFGBG`; a terminal that reports neither is treated as dark, so
pass the flag there. The palette itself is always the terminal's own.

### Command line

There are no subcommands, and that is deliberate: the installer's job is to obtain the
product source, choose the distro path and check the backend — everything after that is
`kosctl`'s. Flags are the whole interface:

| Invocation | What runs |
|---|---|
| `./install.sh` | the Textual wizard |
| `./install.sh --check` | probes + the plan, read-only, exit 2 when blocked or unsupported |
| `./install.sh --plain --yes` | the same plan without a UI, for scripts and CI |
| `./install.sh --source stable --apps todo --start` | pre-selects the wizard, or seeds `--plain` |
| `./install.sh --theme light` | the wizard for a light terminal that does not report its background |

Exit codes: `0` success, `1` a step failed, `2` blocked / unsupported / incompatible backend,
`130` cancelled.

For the product itself use `kosctl` directly: `kosctl install`, `kosctl install apps --only`,
`kosctl start`, `kosctl uninstall`, `kosctl doctor`, `kosctl update`, `kosctl on|off`,
`kosctl snapshot`, `kosctl rollback`. The installer never re-implements them and does not
wrap them in a second command tree.

## sudo

Nothing asks for a password up front. The install children run without a tty, so a
`sudo` shim and an askpass helper are put on their `PATH`: when a step's `sudo` needs
a password, the helper leaves a request and blocks, and the wizard shows one dialog
for it. A full install therefore asks twice, like running `kosctl` by hand — once for
the build packages, once for the KWin system plugins after the build. Nothing else
prompts: a run whose dependencies are all present asks exactly once, after the build,
and a `sudo` timestamp that is still valid (`sudo -n` passing, or a password typed a
minute ago) means zero prompts. The plan starting is never a reason to ask.

The answer is written to one file only this user can read, is used for that `sudo`
call, and is removed as soon as sudo has it; it never reaches the log, argv or the
result screen. Cancelling the dialog denies the password: that request and every
later one fail at once (no three-attempt retry), the step fails, and the run ends
with "sudo password was not provided". Priming sudo first (`sudo -v`) avoids the
prompt entirely for the following minutes.

`--plain` and `--yes` have no event loop to answer a request mid-run, so they ask
once with `getpass` when stdin is a tty; without one they need a primed `sudo -v`
and exit 2 before starting anything.

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
