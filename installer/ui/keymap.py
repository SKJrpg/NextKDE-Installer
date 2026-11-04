"""One key table: bindings, footer words and the help overlay all read it.

A screen declares a context (``CONTEXT``); a focused widget may add one
(``context`` on the row). ``resolve()`` turns that into ordered rows, so a hint
that is offered is a key that really works, in the current language.
"""

from __future__ import annotations

from dataclasses import dataclass

# -- contexts ---------------------------------------------------------
WIZARD = frozenset({
    "wizard.welcome", "wizard.checks", "wizard.options", "wizard.review",
    "wizard.confirm", "wizard.run", "wizard.result",
})
LISTS = frozenset({"list.units", "list.snapshots", "list.logs"})
MENUS = frozenset({"menu"}) | LISTS | {"log.view"}
ALL = WIZARD | MENUS

WELCOME, CHECKS, OPTIONS = "wizard.welcome", "wizard.checks", "wizard.options"
REVIEW, CONFIRM = "wizard.review", "wizard.confirm"
RUN, RESULT = "wizard.run", "wizard.result"
MENU = "menu"


# Key names as the footer shows them; a terminal without UTF-8 gets words.
_KEY_NAMES = {
    "enter": "⏎", "escape": "esc", "space": "space", "tab": "Tab",
    "shift+tab": "Shift+Tab", "left": "←", "right": "→", "up": "↑",
    "down": "↓", "pageup": "PgUp", "pagedown": "PgDn",
    "question_mark": "?",
}
_ASCII = {"⏎": "Enter", "←": "left", "→": "right", "↑": "up", "↓": "down",
          "–": "-"}


def display_key(key: str, ascii_only: bool = False) -> str:
    """How a key (or a multi-key display like "↑/↓") reads in the footer."""
    text = _KEY_NAMES.get(key, key)
    if ascii_only:
        for glyph, word in _ASCII.items():
            text = text.replace(glyph, word)
    return text


@dataclass(frozen=True)
class Action:
    """One user-visible command; ``keys[0]`` is the key the footer shows."""

    id: str                       # "wizard.next"; the binding action is id_underscored
    keys: tuple[str, ...]
    label: str                    # strings key; "" = bound but not listed
    contexts: frozenset[str]
    priority: int = 50            # lower survives first when the footer is short
    hidden: bool = False          # bound and in the help overlay, not in the footer
    danger: bool = False          # only reachable through a confirmation
    aliases: tuple[str, ...] = ()  # extra keys, bound with no footer text
    display: str | None = None     # key name for a multi-key row ("↑/↓", "1/2")
    bind: tuple[str, ...] | None = None  # Textual action per key; default id_underscored
    binding_priority: bool = False  # beats a scroll container's own arrow key


@dataclass(frozen=True)
class Row:
    action: Action
    keys: tuple[str, ...]
    aliases: tuple[str, ...]
    targets: tuple[str, ...]


# Footer order is table order: primary, secondary, then quit and help.
ACTIONS: tuple[Action, ...] = (
    # Table order is footer order; each screen takes the rows it declares.
    Action("option.pick", ("up", "down"), "key_select", frozenset({"option.radio"}),
           10, display="↑/↓", bind=()),
    Action("option.toggle", ("space",), "key_toggle", frozenset({"option.check"}), 10),
    Action("option.move", ("up", "down"), "key_move", frozenset({"option.check"}), 10,
           display="↑/↓", bind=("option_move(-1)", "option_move(1)"),
           binding_priority=True),   # the list's scroll binding would win otherwise
    Action("check.move", ("up", "down"), "key_select", frozenset({CHECKS}), 10,
           display="↑/↓", bind=("checks_move(-1)", "checks_move(1)")),
    Action("review.continue", ("enter",), "key_continue", frozenset({REVIEW}), 10),
    Action("review.details", ("t",), "key_details", frozenset({REVIEW}), 10),
    Action("review.retry", ("r",), "key_retry", frozenset({REVIEW}), 30),
    Action("result.retry", ("r",), "key_retry", frozenset({RESULT}), 10),
    Action("log.open", ("l",), "key_log", frozenset({REVIEW, RESULT}), 30),
    Action("confirm.pick", ("1", "2"), "key_select", frozenset({CONFIRM}), 10,
           display="1/2", bind=("confirm_pick(1)", "confirm_pick(2)")),
    Action("menu.goto", ("1", "2", "3", "4", "5", "6"), "menu_goto",
           frozenset({MENU}), 10, display="1–6", bind=()),
    Action("menu.move", ("up", "down"), "key_select", frozenset({MENU}) | LISTS, 10,
           display="↑/↓", bind=()),
    Action("unit.toggle", ("enter",), "key_toggle", frozenset({"list.units"}), 10,
           aliases=("space",)),
    Action("snapshot.rollback", ("enter",), "key_rollback",
           frozenset({"list.snapshots"}), 10, danger=True),
    Action("snapshot.create", ("c",), "key_create", frozenset({"list.snapshots"}), 30),
    Action("logs.open", ("enter",), "key_open", frozenset({"list.logs"}), 10),
    Action("log.scroll", ("up", "down"), "key_scroll", frozenset({"log.view"}), 10,
           display="↑/↓", aliases=("pageup", "pagedown"), bind=()),
    Action("menu.item.units", ("1",), "", frozenset({MENU}), 30, hidden=True),
    Action("menu.item.snapshots", ("2",), "", frozenset({MENU}), 30, hidden=True),
    Action("menu.item.doctor", ("3",), "", frozenset({MENU}), 30, hidden=True),
    Action("menu.item.logs", ("4",), "", frozenset({MENU}), 30, hidden=True),
    Action("menu.item.uninstall", ("5",), "", frozenset({MENU}), 30, hidden=True,
           danger=True),
    Action("menu.item.back", ("6",), "", frozenset({MENU}), 30, hidden=True),
    Action("wizard.next", ("enter",), "key_next", frozenset({WELCOME, CHECKS, OPTIONS}), 10),
    Action("review.install", ("enter",), "key_confirm", frozenset({CONFIRM}), 10,
           danger=True),
    Action("check.refresh", ("r",), "key_refresh", frozenset({CHECKS}), 40),
    Action("welcome.language", ("left", "right"), "key_language",
           frozenset({WELCOME}), 20, display="←/→"),
    Action("menu.act", ("enter",), "key_open", frozenset({MENU}), 20),
    Action("wizard.back", ("escape",), "key_back",
           frozenset({CHECKS, OPTIONS, REVIEW, CONFIRM}) | MENUS, 20),
    Action("app.manage", ("m",), "key_manage", frozenset({WELCOME, RESULT}), 30),
    Action("app.quit", ("q",), "key_quit",
           frozenset({WELCOME, CHECKS, OPTIONS, REVIEW}), 70),
    Action("result.exit", ("q",), "key_exit", frozenset({RESULT}), 70),
    Action("run.abort", ("ctrl+c",), "key_abort", frozenset({RUN, MENU}) | LISTS, 5,
           danger=True),
    Action("focus.next", ("tab",), "key_focus_next", ALL, 80, hidden=True,
           display="Tab", bind=("focus_next",)),
    Action("focus.prev", ("shift+tab",), "key_focus_prev", ALL, 80, hidden=True,
           display="Shift+Tab", bind=("focus_prev",)),
    Action("help.open", ("question_mark",), "key_help", ALL, 90, display="?"),
)

_BY_ID = {action.id: action for action in ACTIONS}

# Action id -> the keys the user chose for it (config "keys").
_OVERRIDES: dict[str, tuple[str, ...]] = {}


def apply_overrides(mapping: dict[str, object] | None) -> None:
    """Replace default keys from the config; unknown ids are an error."""
    _OVERRIDES.clear()
    for action_id, value in (mapping or {}).items():
        action = _BY_ID.get(action_id)
        if action is None:
            raise ValueError(f"unknown key action: {action_id}")
        if isinstance(value, (list, tuple)):
            keys = tuple(str(key).strip() for key in value if str(key).strip())
        else:
            keys = tuple(part.strip() for part in str(value).split(",") if part.strip())
        if action.bind and len(keys) != len(action.bind):
            raise ValueError(f"{action_id} needs {len(action.bind)} keys, got {len(keys)}")
        _OVERRIDES[action_id] = keys


def _effective(action: Action, overrides) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """(keys, aliases, Textual action per key) after config overrides."""
    chosen = overrides.get(action.id) if overrides is not None else _OVERRIDES.get(action.id)
    if chosen is None:
        keys, aliases = action.keys, action.aliases
    else:
        keys, aliases = chosen, ()     # a rebound action loses its extra keys
    if action.bind is not None:
        targets = action.bind
    else:
        targets = (action.id.replace(".", "_"),) * (len(keys) + len(aliases))
    return keys, aliases, targets


def resolve(contexts: set[str] | frozenset[str], overrides=None,
            budget: int | None = None, measure=None) -> list[Row]:
    """The rows for these contexts, in footer order.

    Raises ValueError when two actions claim the same key: the table is static,
    so that is a bug in the table, not something to paper over at runtime.
    """
    rows: list[Row] = []
    claimed: dict[str, str] = {}
    for action in ACTIONS:
        if not action.contexts & contexts:
            continue
        keys, aliases, targets = _effective(action, overrides)
        if not keys:
            continue
        if targets:                 # hint-only rows (bind=()) claim nothing
            for key in keys + aliases:
                if key in claimed:
                    raise ValueError(
                        f"{key} is claimed by {claimed[key]} and {action.id}")
                claimed[key] = action.id
        rows.append(Row(action, keys, aliases, targets))
    if budget is not None and measure is not None:
        rows = fit(rows, budget, measure)
    return rows


def fit(rows: list[Row], budget: int, measure) -> list[Row]:
    """Drop the least important rows until the footer fits the width."""
    kept = list(rows)
    while any(not row.action.hidden for row in kept):
        width = sum(measure(row) for row in kept if not row.action.hidden)
        if width <= budget:
            break
        lowest = max((row for row in kept if not row.action.hidden),
                     key=lambda row: row.action.priority)
        kept.remove(lowest)
    return kept


def row_for(contexts, action_id: str) -> Action | None:
    """The action, if it applies here; used by tests over the table."""
    for action in ACTIONS:
        if action.id == action_id and action.contexts & contexts:
            return action
    return None
