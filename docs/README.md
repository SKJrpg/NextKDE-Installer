# Documentation

Start with the repository [README](../README.md) for installing and running the
wizard. These files go deeper:

| File | Use it for | Status |
|---|---|---|
| [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md) | How the tree works today: entry points, detection, source manager, plan, UI, sudo, state, gaps | Current; source of truth |
| [BACKEND_CONTRACT.md](BACKEND_CONTRACT.md) | Capability names, `installer-contract.json`, `kosctl installer-info`, probe fallback, compatibility | Current |
| [KEYMAP.md](KEYMAP.md) | Every screen's keys, footer text, help rules and the history of key decisions | Current through §10; §11 onward is history |
| [MIGRATION_PLAN.md](MIGRATION_PLAN.md) | What is done and what is still open | Current |
| [design.md](design.md) | The original independent-installer proposal and its rationale | Historical; predates the Textual port |

The current docs are written from the code. If a historical file disagrees with
the tree, `CURRENT_ARCHITECTURE.md` and the code win.
