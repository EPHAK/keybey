import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keybey import config


SAMPLE_LUA = '''\
local mainMod = "SUPER"
local terminal = "kitty"

hl.bind(mainMod .. " + Q", hl.dsp.window.close(), { description = "close window" })
hl.bind(mainMod .. " + Return", hl.dsp.exec_cmd(terminal), { description = "open terminal" })

for i = 1, 9 do
\thl.bind(mainMod .. " + " .. i, hl.dsp.focus({ workspace = i }), { description = "go to " .. i })
end

hl.bind(mainMod .. " + H", function()
\tlocal w = hl.get_active_window()
\t-- a comment with an apostrophe: it's fine, shouldn't break parsing
\tif w == nil then return end
\thl.dispatch(hl.dsp.window.move({ workspace = "special:min" }))
end, { description = "minimize" })

hl.bind(mainMod .. " + SHIFT + H", function()
\tlocal allWins = hl.get_windows()
end, { description = "restore" })

hl.bind(mainMod .. " + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }),
\t{ description = "move to scratchpad" })

hl.bind("Print", hl.dsp.exec_cmd("grim -g \\"$(slurp)\\""), { description = "screenshot" })
'''


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.conf = self.tmp_path / "hyprland.lua"
        self.conf.write_text(SAMPLE_LUA)

    def test_simple_top_level_binds_are_editable(self):
        binds, variables = config.load(self.conf)
        self.assertEqual(variables, {"mainMod": "SUPER", "terminal": "kitty"})
        simple = [b for b in binds if b.mods == 'mainMod .. " + Q"']
        self.assertEqual(len(simple), 1)
        b = simple[0]
        self.assertTrue(b.editable)
        self.assertEqual(b.dispatcher, "hl.dsp.window.close()")
        self.assertEqual(b.description(), "close window")
        self.assertEqual(b.resolved_mods(variables), "SUPER + Q")

    def test_loop_generated_bind_is_not_editable(self):
        binds, _ = config.load(self.conf)
        loop_binds = [b for b in binds if ' .. i, hl.dsp.focus' in b.raw]
        self.assertEqual(len(loop_binds), 1)
        self.assertFalse(loop_binds[0].editable)

    def test_function_binds_are_parsed_separately_and_not_editable(self):
        """Regression: a comment containing an apostrophe (e.g. "it's")
        inside a multi-line function body was previously misread as opening
        a string literal, breaking paren-depth tracking and silently
        merging two separate binds -- and everything after them -- into
        one giant, wrongly-spanning entry."""
        binds, _ = config.load(self.conf)
        h_binds = [b for b in binds if "+ H" in b.mods and "SHIFT" not in b.mods]
        shift_h_binds = [b for b in binds if "SHIFT + H" in b.mods]
        self.assertEqual(len(h_binds), 1)
        self.assertEqual(len(shift_h_binds), 1)
        self.assertFalse(h_binds[0].editable)
        self.assertFalse(shift_h_binds[0].editable)
        self.assertNotEqual(h_binds[0].line_no, shift_h_binds[0].line_no)

        # everything after the function binds must still be found
        screenshot = [b for b in binds if b.description() == "screenshot"]
        self.assertEqual(len(screenshot), 1)

    def test_wrapped_args_bind_is_not_editable(self):
        binds, _ = config.load(self.conf)
        scratchpad = [b for b in binds if b.description() == "move to scratchpad"]
        self.assertEqual(len(scratchpad), 1)
        self.assertFalse(scratchpad[0].editable)

    def test_total_bind_count_matches_source_occurrences(self):
        binds, _ = config.load(self.conf)
        occurrences = SAMPLE_LUA.count("hl.bind(")
        self.assertEqual(len(binds), occurrences)

    def test_update_bind_preserves_rest_of_file_and_backs_up(self):
        with mock.patch.object(config, "HYPR_LUA", self.conf), \
             mock.patch.object(config, "BACKUP_DIR", self.tmp_path / "backups"):
            binds, _ = config.load()
            target = next(b for b in binds if b.mods == 'mainMod .. " + Q"')
            config.update_bind(target, target.mods, "hl.dsp.exec_cmd(terminal)", '{ description = "open term instead" }')
            new_binds, _ = config.load()
            changed = next(b for b in new_binds if b.mods == 'mainMod .. " + Q"')
            self.assertEqual(changed.dispatcher, "hl.dsp.exec_cmd(terminal)")
            self.assertEqual(changed.description(), "open term instead")
            # unrelated binds untouched
            unrelated = next(b for b in new_binds if b.mods == 'mainMod .. " + Return"')
            self.assertEqual(unrelated.dispatcher, "hl.dsp.exec_cmd(terminal)")
            backups = list((self.tmp_path / "backups").glob("hyprland.lua.*"))
            self.assertEqual(len(backups), 1)
            self.assertIn("close window", backups[0].read_text())

    def test_update_bind_refuses_non_editable(self):
        with mock.patch.object(config, "HYPR_LUA", self.conf), \
             mock.patch.object(config, "BACKUP_DIR", self.tmp_path / "backups"):
            binds, _ = config.load()
            loop_bind = next(b for b in binds if ' .. i, hl.dsp.focus' in b.raw)
            with self.assertRaises(ValueError):
                config.update_bind(loop_bind, loop_bind.mods, "whatever", "")

    def test_delete_bind_removes_only_target_line(self):
        with mock.patch.object(config, "HYPR_LUA", self.conf), \
             mock.patch.object(config, "BACKUP_DIR", self.tmp_path / "backups"):
            binds, _ = config.load()
            target = next(b for b in binds if b.mods == 'mainMod .. " + Q"')
            config.delete_bind(target)
            remaining, _ = config.load()
            self.assertNotIn('mainMod .. " + Q"', [b.mods for b in remaining])
            still_there = next(b for b in remaining if b.mods == 'mainMod .. " + Return"')
            self.assertEqual(still_there.dispatcher, "hl.dsp.exec_cmd(terminal)")

    def test_add_bind_appends_to_end_of_file(self):
        with mock.patch.object(config, "HYPR_LUA", self.conf), \
             mock.patch.object(config, "BACKUP_DIR", self.tmp_path / "backups"):
            config.add_bind('mainMod .. " + Z"', "hl.dsp.exec_cmd(terminal)", '{ description = "new" }')
            binds, _ = config.load()
            new_bind = next(b for b in binds if b.mods == 'mainMod .. " + Z"')
            self.assertTrue(new_bind.editable)
            self.assertEqual(new_bind.description(), "new")


if __name__ == "__main__":
    unittest.main()
