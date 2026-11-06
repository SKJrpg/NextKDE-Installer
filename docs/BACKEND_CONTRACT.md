# Backend contract

How the installer decides what the prepared product checkout can do, and how it
refuses what it cannot. Implements design §7; the installer half is done, the
product-side declaration is still pending (see `MIGRATION_PLAN.md`).

## Capability names

| Capability | Meaning | Step / UI |
|---|---|---|
| `system.doctor` | `kosctl doctor` reports dependencies | dependency probe, manager |
| `system.deps` | `kosctl deps` / `kosctl deps --install` | `deps` step |
| `install.core` | `kosctl install` builds and deploys the desktop | `core` step |
| `install.apps` | `kosctl install apps [--only …]` | app rows, `apps` step |
| `install.lockscreen` | `kosctl install lockscreen` | lock-screen row, `lockscreen` step |
| `install.debian` | `tools/install-debian13.sh` exists | Debian wrapper step |
| `install.debian.local` | that wrapper accepts `--local` | `--local` argument |
| `activation.start` | `kosctl start` | start row, `start` step |
| `management.uninstall` | `kosctl uninstall` | management area |
| `management.snapshots` | `tools/kos-state.py` snapshots | management area |
| `source.update` | `kosctl update <ref>` | `source` step |
| `platform.nix` | `kosctl nix install` | NixOS step |

`installer/backend/models.py` is the only list of names. Strings it does not
know are kept in `BackendInfo.capabilities` but are never acted on
(`BackendInfo.usable` / `has()`); that is how an older installer meets a newer
product without guessing.

## Declared shape: `packaging/installer-contract.json`

```json
{
  "schema_version": 1,
  "product": {"id": "nextkde", "name": "NextKDE"},
  "installer_api": {"minimum": 1, "maximum": 1},
  "capabilities": ["system.doctor", "system.deps", "install.core", "install.apps"],
  "components": ["calendar", "todo", "weather", "calculator"]
}
```

The product version is read from the checkout's `VERSION` file. In the product
repository this file does not exist yet.

## Declared shape: `kosctl installer-info --json`

```json
{
  "product": "nextkde",
  "installer_api": 1,
  "product_version": "0.1.0",
  "capabilities": ["system.doctor", "install.core"],
  "components": ["calendar", "todo"]
}
```

`contract.read()` prefers the static file, then runs the subcommand — but only
when the script's usage text advertises `installer-info`, so an older `kosctl`
is never executed into its side effects. Either source yields
`BackendInfo(source="contract")`.

## Fallback: probing the checkout

When neither declaration exists, `probe.detect()` derives capabilities only from
files the checkout contains:

- `tools/kosctl` present and executable → capabilities named by the verbs in its
  usage text (`doctor`, `install`, `install apps`, `install lockscreen`,
  `start`, `uninstall`, `update`, `nix`).
- `tools/kos-state.py` present → `management.snapshots`.
- `tools/install-debian13.sh` present → `install.debian`; its usage mentioning
  `--local` → `install.debian.local`.
- `VERSION` → the product version.
- `apps/<name>/` directories → `components`.

The usage text is read from the file, never printed by running the script: a
probe must not write into the product checkout. Anything not evidenced is
absent, so a probe result is narrower than the truth, never wider.

## Compatibility rule

This installer speaks `installer_api = 1`. A declared range that does not
contain 1, or a `schema_version` other than 1, raises `BackendIncompatible`
(a `ValueError`). A malformed contract file is not an incompatibility: it falls
through to the probe. That split is deliberate: broken data is degradable,
a version mismatch is not.

`require(info, capability)` raises the same error naming the product version and
the missing capability. `plan.build_plan(..., backend=info)` drops any step whose
capability the backend lacks; the Options screen disables the matching row and
prints the reason; `unsupported()` reports the choice to the CLI/Review, so a
selection is never silently ignored. Detection happens once from `--root`, then
again from the prepared workspace; an incompatible backend stops before Review
(and before the install if preparation finds a different one).
