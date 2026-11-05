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
        self.assertEqual(danger, {"review.install", "run.abort", "snapshot.rollback",
                                  "menu.item.uninstall"})

    def test_no_default_key_is_a_terminal_conflict(self) -> None:
        forbidden = {"ctrl+m", "ctrl+i", "ctrl+j", "ctrl+h", "ctrl+s", "ctrl+q",
                     "ctrl+z", "ctrl+d", "ctrl+a", "ctrl+b"}
        for action in keymap.ACTIONS:
            for key in action.keys + action.aliases:
                self.assertNotIn(key, forbidden, action.id)
                self.assertFalse(key.startswith("alt+"), action.id)

    def test_display_names_are_short_and_ascii_safe(self) -> None:
        self.assertEqual(keymap.display_key("enter"), "⏎")
        self.assertEqual(keymap.display_key("escape"), "esc")
        self.assertEqual(keymap.display_key("enter", ascii_only=True), "Enter")
        self.assertEqual(keymap.display_key("↑/↓", ascii_only=True), "up/down")
        self.assertEqual(keymap.display_key("1–6", ascii_only=True), "1-6")

    def test_overrides_replace_keys_and_drop_aliases(self) -> None:
        keymap.apply_overrides({"wizard.back": "b", "unit.toggle": "x"})
        rows = {row.action.id: row for row in keymap.resolve({"wizard.checks"})}
        self.assertEqual(rows["wizard.back"].keys, ("b",))
        units = {row.action.id: row for row in keymap.resolve({"list.units"})}
        self.assertEqual(units["unit.toggle"].keys, ("x",))
        self.assertEqual(units["unit.toggle"].aliases, ())

    def test_unknown_or_malformed_overrides_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            keymap.apply_overrides({"wizard.nope": "x"})
        with self.assertRaises(ValueError):
            keymap.apply_overrides({"confirm.pick": "9"})   # needs two keys

    def test_the_config_accepts_a_keys_section(self) -> None:
        from installer.__main__ import CONFIG_KEYS

        self.assertIn("keys", CONFIG_KEYS)
