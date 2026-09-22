import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keybey import config, yazi_config


SAMPLE_DEFAULT = '''\
[mgr]
keymap = [
	{ on = "h", run = "leave", desc = "Back to the parent directory" },
	{ on = "l", run = "enter", desc = "Enter the child directory" },
	{ on = "<Space>", run = [ "toggle", "arrow 1" ], desc = "Toggle the current selection state" },
	{ on = [ "g", "h" ], run = "cd ~", desc = "Go home" },
]

[input]
keymap = [
	{ on = "<Esc>", run = "close", desc = "Cancel input" },
]
'''

SAMPLE_USER = '''\
[[mgr.prepend_keymap]]
on   = "l"
run  = "plugin smart-enter"
desc = "Enter the child directory, or open the file"

[[mgr.prepend_keymap]]
on   = [ "g", "y" ]
run  = "plugin my-macro"
desc = "a multi-key user bind"
'''


class YaziConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.default_path = self.tmp_path / "default.toml"
        self.default_path.write_text(SAMPLE_DEFAULT)
        self.user_path = self.tmp_path / "keymap.toml"
        self.user_path.write_text(SAMPLE_USER)
        self.backup_dir = self.tmp_path / "backups"
        self._patches = [
            mock.patch.object(yazi_config, "USER_KEYMAP", self.user_path),
            mock.patch.object(config, "BACKUP_DIR", self.backup_dir),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_load_defaults_are_never_editable(self):
        binds = yazi_config.load_defaults(self.default_path)
        self.assertEqual(len(binds), 5)
        self.assertTrue(all(not b.editable for b in binds))
        h = next(b for b in binds if b.context == "mgr" and b.on == "h")
        self.assertEqual(h.run, "leave")

    def test_load_defaults_missing_file_returns_empty(self):
        self.assertEqual(yazi_config.load_defaults(self.tmp_path / "nope.toml"), [])

    def test_load_defaults_list_values_are_readable_but_not_editable(self):
        binds = yazi_config.load_defaults(self.default_path)
        space = next(b for b in binds if b.on == "<Space>")
        self.assertIn("toggle", space.run)
        self.assertFalse(space.editable)
        gh = next(b for b in binds if b.on == "g -> h")
        self.assertFalse(gh.editable)

    def test_load_user_simple_entry_is_editable(self):
        binds = yazi_config.load_user()
        simple = next(b for b in binds if b.on == "l")
        self.assertTrue(simple.editable)
        self.assertEqual(simple.run, "plugin smart-enter")
        self.assertEqual(simple.array_index, 0)

    def test_load_user_multikey_entry_is_not_editable(self):
        binds = yazi_config.load_user()
        macro = next(b for b in binds if "a multi-key user bind" == b.desc)
        self.assertFalse(macro.editable)

    def test_load_user_missing_file_returns_empty(self):
        with mock.patch.object(yazi_config, "USER_KEYMAP", self.tmp_path / "nope.toml"):
            self.assertEqual(yazi_config.load_user(), [])

    def test_add_bind_creates_file_and_section(self):
        fresh = self.tmp_path / "fresh.toml"
        with mock.patch.object(yazi_config, "USER_KEYMAP", fresh):
            yazi_config.add_bind("z", "plugin zoom", "zoom in")
            binds = yazi_config.load_user()
            new = next(b for b in binds if b.on == "z")
            self.assertEqual(new.run, "plugin zoom")
            self.assertEqual(new.desc, "zoom in")
            self.assertEqual(new.context, "mgr")

    def test_add_bind_appends_without_disturbing_existing_entries(self):
        yazi_config.add_bind("z", "plugin zoom", "zoom in")
        binds = yazi_config.load_user()
        self.assertEqual(len(binds), 3)
        still_there = next(b for b in binds if b.on == "l")
        self.assertEqual(still_there.run, "plugin smart-enter")

    def test_update_bind_changes_only_target_entry(self):
        binds = yazi_config.load_user()
        target = next(b for b in binds if b.on == "l")
        yazi_config.update_bind(target, "l", "plugin smart-enter --open_multi", "updated desc")
        binds = yazi_config.load_user()
        changed = next(b for b in binds if b.on == "l")
        self.assertEqual(changed.run, "plugin smart-enter --open_multi")
        self.assertEqual(changed.desc, "updated desc")
        untouched = next(b for b in binds if b.array_index == 1)
        self.assertEqual(untouched.desc, "a multi-key user bind")

    def test_update_bind_refuses_non_editable(self):
        binds = yazi_config.load_user()
        macro = next(b for b in binds if not b.editable)
        with self.assertRaises(ValueError):
            yazi_config.update_bind(macro, "x", "y", "z")

    def test_update_bind_backs_up_first(self):
        binds = yazi_config.load_user()
        target = next(b for b in binds if b.on == "l")
        yazi_config.update_bind(target, "l", "plugin smart-enter", "changed")
        backups = list(self.backup_dir.glob("keymap.toml.*"))
        self.assertEqual(len(backups), 1)
        self.assertIn("smart-enter", backups[0].read_text())

    def test_delete_bind_removes_only_target(self):
        binds = yazi_config.load_user()
        target = next(b for b in binds if b.on == "l")
        yazi_config.delete_bind(target)
        remaining = yazi_config.load_user()
        self.assertNotIn("l", [b.on for b in remaining])
        self.assertEqual(len(remaining), 1)

    def test_delete_bind_refuses_non_editable(self):
        binds = yazi_config.load_user()
        macro = next(b for b in binds if not b.editable)
        with self.assertRaises(ValueError):
            yazi_config.delete_bind(macro)


if __name__ == "__main__":
    unittest.main()
