"""The key table itself: contexts, duplicates, labels, overrides.

No terminal needed: this is the registry the footer, the help overlay and the
Textual bindings all read.
"""

from __future__ import annotations

import unittest

from installer.strings import Strings
from installer.ui import keymap

CONTEXTS = sorted(keymap.WIZARD | keymap.MENUS)


class RegistryTest(unittest.TestCase):
    def tearDown(self) -> None:
        keymap.apply_overrides({})

    def test_every_context_resolves_without_duplicate_keys(self) -> None:
        for context in CONTEXTS:
            with self.subTest(context=context):
                rows = keymap.resolve({context})
                self.assertTrue(rows, context)
                claimed = [key for row in rows
                           for key in row.keys + row.aliases if row.targets]
                self.assertEqual(len(claimed), len(set(claimed)))

    def test_labels_exist_in_both_languages(self) -> None:
        for action in keymap.ACTIONS:
            if not action.label:
                continue
            for lang in ("zh", "en"):
                text = Strings(lang)(action.label)
                self.assertNotEqual(text, action.label,
                                    f"{action.id} has no {lang} label")

    def test_dangerous_actions_are_declared(self) -> None:
        danger = {action.id for action in keymap.ACTIONS if action.danger}
        # Y installs and Ctrl+Z stops a run; both are deliberate single keys.
        # Rollback and uninstall still ask first.
        self.assertEqual(danger, {"confirm.install", "run.abort",
                                  "snapshot.rollback", "menu.item.uninstall"})

    def test_no_default_key_is_a_terminal_conflict(self) -> None:
        # Ctrl+Q is XON, Ctrl+S XOFF, Ctrl+Z suspends a cooked terminal, the
        # rest are Enter/Tab/EOF or shell, tmux and Emacs aliases. Ctrl+Z is
        # abort anyway (raw mode delivers it), and the log viewer takes
        # Ctrl+U/D on purpose (half page over a read-only view).
        forbidden = {"ctrl+m", "ctrl+i", "ctrl+j", "ctrl+h", "ctrl+s", "ctrl+q",
                     "ctrl+d", "ctrl+a", "ctrl+b", "ctrl+\\"}
        for action in keymap.ACTIONS:
            for key in action.keys + action.aliases:
                if key in ("ctrl+u", "ctrl+d"):
                    self.assertEqual(action.id, "log.halfpage")
                    continue
                if key == "ctrl+z":
                    self.assertEqual(action.id, "run.abort")
                    continue
                self.assertNotIn(key, forbidden, action.id)
                self.assertFalse(key.startswith("alt+"), action.id)

    def test_ctrl_c_is_guarded_where_abort_runs(self) -> None:
        guard = next(a for a in keymap.ACTIONS if a.id == "run.guard")
        abort = next(a for a in keymap.ACTIONS if a.id == "run.abort")
        self.assertEqual(guard.keys, ("ctrl+c",))
        self.assertEqual(abort.keys, ("ctrl+z",))
        self.assertEqual(guard.contexts, abort.contexts)   # one cannot fire alone
        self.assertTrue(guard.hidden)                      # no footer hint
        self.assertFalse(abort.hidden)
        self.assertEqual(guard.label, "")
        # Hidden rows still reach the bindings: the guard must be resolvable.
        for context in abort.contexts:
            self.assertIn("run.guard",
                          {row.action.id
                           for row in keymap.resolve(frozenset({context}))})

    def test_function_keys_are_ctrl_and_letters_are_navigation(self) -> None:
        functions = ("review.details", "review.retry", "result.retry", "log.open",
                     "check.refresh", "snapshot.create", "app.manage",
                     "run.abort", "help.open", "log.halfpage",
                     "option.local_path")
        for action_id in functions:
            action = next(a for a in keymap.ACTIONS if a.id == action_id)
            for key in action.keys:
                self.assertTrue(key.startswith("ctrl+"), f"{action_id} -> {key}")

        navigation = ("check.move", "option.pick", "option.move", "option.activate",
                      "option.below", "option.toggle", "confirm.install",
                      "confirm.back", "menu.move", "menu.ends",
                      "log.scroll", "log.ends", "welcome.language",
                      "unit.toggle", "snapshot.rollback", "logs.open", "menu.act",
                      "wizard.next", "wizard.previous", "wizard.back",
                      "review.continue")
        for action_id in navigation:
            action = next(a for a in keymap.ACTIONS if a.id == action_id)
            for key in action.keys + action.aliases:
                self.assertFalse(key.startswith("ctrl+"), f"{action_id} -> {key}")

    def test_vim_aliases_cover_the_movement_rows(self) -> None:
        expected = {
            "check.move": ("j", "k"),
            "option.pick": ("j", "k"),
            "option.move": ("j", "k"),
            "menu.move": ("j", "k"),
            "menu.ends": (),        # g/G are its primary keys
            "log.ends": (),
            "welcome.language": ("h", "l"),
        }
        for action_id, aliases in expected.items():
            action = next(a for a in keymap.ACTIONS if a.id == action_id)
            self.assertEqual(action.aliases, aliases, action_id)
        self.assertEqual(next(a for a in keymap.ACTIONS
                              if a.id == "menu.ends").keys, ("g", "G"))
        self.assertEqual(next(a for a in keymap.ACTIONS
                              if a.id == "log.scroll").aliases[:2], ("j", "k"))

    def test_tab_pages_the_wizard_and_focuses_everywhere_else(self) -> None:
        pages = keymap.PAGES
        self.assertEqual(keymap.resolve({keymap.WELCOME}).__class__, list)
        next_page = next(a for a in keymap.ACTIONS if a.id == "wizard.next")
        self.assertEqual(next_page.keys, ("tab",))
        self.assertTrue(next_page.contexts < pages)
        self.assertNotIn(keymap.CONFIRM, next_page.contexts)   # Tab never installs
        previous = next(a for a in keymap.ACTIONS if a.id == "wizard.previous")
        self.assertEqual(previous.keys, ("shift+tab",))
        self.assertEqual(previous.aliases, ("escape",))
        focus_next = next(a for a in keymap.ACTIONS if a.id == "focus.next")
        self.assertEqual(focus_next.keys, ("tab",))
        self.assertFalse(focus_next.contexts & pages)          # no double binding

    def test_enter_activates_on_options_and_pages_nowhere(self) -> None:
        for context in (keymap.WELCOME, keymap.CHECKS):
            self.assertFalse(any("enter" in row.keys + row.aliases
                                 for row in keymap.resolve({context})), context)
        source = {row.action.id: row for row in
                  keymap.resolve({keymap.OPTIONS, keymap.SOURCE})}
        lower = {row.action.id: row for row in
                 keymap.resolve({keymap.OPTIONS, keymap.CHECK})}
        self.assertEqual(source["option.below"].keys, ("enter",))
        self.assertEqual(lower["option.activate"].keys, ("enter",))
        self.assertEqual(source["wizard.next"].keys, ("tab",))
        self.assertEqual(source["option.pick"].keys, ("up", "down"))
        self.assertNotIn("option.move", source)     # the blocks do not share a cursor
        self.assertEqual(lower["option.move"].keys, ("up", "down"))
        self.assertNotIn("option.pick", lower)
        confirm = keymap.resolve({keymap.CONFIRM})
        rows = {row.action.id: row for row in confirm}
        self.assertFalse(any("tab" in row.keys for row in confirm))   # inert
        self.assertEqual(rows["confirm.install"].keys, ("y",))
        self.assertEqual(rows["confirm.back"].keys, ("n",))
        self.assertEqual(rows["confirm.back"].aliases, ("N", "escape", "shift+tab"))
        self.assertNotIn("wizard.previous", rows)      # its back is confirm.back

    def test_ctrl_x_is_not_a_quit_key(self) -> None:
        # Quitting is the double Ctrl+C gesture in the app, not a table row.
        for action in keymap.ACTIONS:
            for key in action.keys + action.aliases:
                self.assertNotEqual(key, "ctrl+x", action.id)
        self.assertNotIn("app.quit",
                         {action.id for action in keymap.ACTIONS})
        self.assertNotIn("result.exit",
                         {action.id for action in keymap.ACTIONS})

    def test_help_is_a_ctrl_key_with_the_question_mark_alias(self) -> None:
        action = next(a for a in keymap.ACTIONS if a.id == "help.open")
        self.assertEqual(action.keys, ("ctrl+k",))
        self.assertEqual(action.aliases, ("question_mark",))
        self.assertEqual(action.priority, 1)      # the last hint ever dropped

    def test_display_names_are_short_and_ascii_safe(self) -> None:
        self.assertEqual(keymap.display_key("enter"), "⏎")
        self.assertEqual(keymap.display_key("escape"), "esc")
        self.assertEqual(keymap.display_key("enter", ascii_only=True), "Enter")
        self.assertEqual(keymap.display_key("↑/↓", ascii_only=True), "up/down")
        self.assertEqual(keymap.display_key("1–6", ascii_only=True), "1-6")
        self.assertEqual(keymap.display_key("ctrl+x"), "ctrl+x")
        self.assertEqual(keymap.display_key("G"), "G")

    def test_overrides_replace_keys_and_drop_aliases(self) -> None:
        keymap.apply_overrides({"wizard.previous": "b", "unit.toggle": "x"})
        rows = {row.action.id: row for row in keymap.resolve({"wizard.checks"})}
        self.assertEqual(rows["wizard.previous"].keys, ("b",))
        units = {row.action.id: row for row in keymap.resolve({"list.units"})}
        self.assertEqual(units["unit.toggle"].keys, ("x",))
        self.assertEqual(units["unit.toggle"].aliases, ())

    def test_unknown_or_malformed_overrides_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            keymap.apply_overrides({"wizard.nope": "x"})
        with self.assertRaises(ValueError):
            keymap.apply_overrides({"check.move": "9"})     # needs two keys

    def test_the_config_accepts_a_keys_section(self) -> None:
        from installer.__main__ import CONFIG_KEYS

        self.assertIn("keys", CONFIG_KEYS)
