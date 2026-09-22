import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keybey import config, nvim_config, yazi_config
from keybey import app as keybey_app
from keybey.app import KeybeyApp, MessageModal
from textual.widgets import DataTable, Input


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
end, { description = "minimize" })
'''

SAMPLE_YAZI_USER = '''\
[[mgr.prepend_keymap]]
on   = "l"
run  = "plugin smart-enter"
desc = "Enter the child directory, or open the file"
'''


class AppTest(unittest.IsolatedAsyncioTestCase):
    """These tests focus on the Hyprland source, since it's the one with the
    richest existing coverage (see test_config.py) -- yazi is patched to an
    empty/absent config so it never contributes rows here, keeping row
    counts and indices predictable. Yazi-specific app wiring (source picker,
    field labels) is covered separately below."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.conf = self.tmp_path / "hyprland.lua"
        self.conf.write_text(SAMPLE_LUA)
        self.backup_dir = self.tmp_path / "backups"
        state_dir = self.tmp_path / "state"
        self._patches = [
            mock.patch.object(config, "HYPR_LUA", self.conf),
            mock.patch.object(config, "BACKUP_DIR", self.backup_dir),
            mock.patch.object(keybey_app, "STATE_DIR", state_dir),
            mock.patch.object(keybey_app, "THEME_FILE", state_dir / "theme"),
            mock.patch.object(yazi_config, "DEFAULT_KEYMAP", self.tmp_path / "no_yazi_defaults.toml"),
            mock.patch.object(yazi_config, "USER_KEYMAP", self.tmp_path / "no_yazi_user.toml"),
            mock.patch.object(nvim_config, "NVIM_KEYMAPS_FILE", self.tmp_path / "no_nvim_keymaps.lua"),
            mock.patch.object(nvim_config, "NVIM_PLUGINS_DIR", self.tmp_path / "no_nvim_plugins"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_default_focus_is_table_not_search(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            self.assertIs(app.focused, table)

    async def test_start_in_search_focuses_search_box(self):
        """Regression: --search (used by the cheatsheet keybind) must land
        focus on the search box, not the table, so typing works immediately."""
        app = KeybeyApp(start_in_search=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            search = app.query_one("#search", Input)
            self.assertIs(app.focused, search)

    async def test_search_matches_resolved_mods_and_description(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            search = app.query_one("#search", Input)
            search.focus()
            await pilot.pause()
            await pilot.press(*"close window")
            await pilot.pause()
            self.assertEqual(len(app.filtered), 1)
            self.assertEqual(app.filtered[0].keys, "SUPER + Q")

    async def test_load_reads_from_patched_hypr_lua(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            # 2 simple + 1 loop-generated + 1 function-based = 4
            self.assertEqual(len(app.keybinds), 4)
            editable = [kb for kb in app.keybinds if kb.editable]
            self.assertEqual(len(editable), 2)

    async def test_edit_writes_only_to_patched_config(self):
        real_config_sentinel = self.tmp_path / "definitely_not_touched.lua"
        real_config_sentinel.write_text("-- should never change\n")
        before = real_config_sentinel.read_text()

        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            await pilot.press("enter")
            await pilot.pause(0.2)
            field2 = app.screen.query_one("#field2", Input)
            field2.focus()
            field2.value = ""
            await pilot.pause()
            await pilot.press(*"hl.dsp.exec_cmd(terminal)")
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)

        after = real_config_sentinel.read_text()
        self.assertEqual(before, after, "unrelated sentinel file must never be touched")
        binds, _ = config.load(self.conf)
        changed = next(b for b in binds if b.mods == 'mainMod .. " + Q"')
        self.assertEqual(changed.dispatcher, "hl.dsp.exec_cmd(terminal)")

    async def test_editing_non_editable_bind_shows_message_and_refuses(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            loop_row = next(i for i, kb in enumerate(app.filtered) if not kb.editable)
            table.cursor_coordinate = (loop_row, 0)
            await pilot.press("enter")
            await pilot.pause(0.2)
            top = app.screen_stack[-1]
            self.assertIsInstance(top, MessageModal)
            self.assertIn("can't be safely edited", top.message)

        # file must be byte-identical -- nothing was written
        self.assertEqual(self.conf.read_text(), SAMPLE_LUA)

    async def test_add_then_delete_round_trip(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            before_count = len(app.keybinds)
            await pilot.press("a")
            await pilot.pause(0.2)
            # only one addable source (yazi is patched to empty/absent, but
            # can_add() is still True for it) -- so a source-pick step may
            # appear; select hyprland if so.
            top = app.screen_stack[-1]
            if hasattr(top, "options"):
                await pilot.press("enter")
                await pilot.pause(0.2)
            fields = [
                ("#field1", 'mainMod .. " + Z"'),
                ("#field2", "hl.dsp.exec_cmd(terminal)"),
                ("#field3", '{ description = "new bind" }'),
            ]
            for field_id, text in fields:
                inp = app.screen.query_one(field_id, Input)
                inp.focus()
                inp.value = ""
                await pilot.pause()
                await pilot.press(*text)
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
            self.assertEqual(len(app.keybinds), before_count + 1)

            table = app.query_one(DataTable)
            table.focus()
            new_row = next(i for i, kb in enumerate(app.filtered) if kb.description == "new bind")
            table.cursor_coordinate = (new_row, 0)
            await pilot.press("d")
            await pilot.pause(0.2)
            await pilot.press("y")
            await pilot.pause(0.3)
            self.assertEqual(len(app.keybinds), before_count)

    async def test_deleting_non_editable_bind_refuses(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            loop_row = next(i for i, kb in enumerate(app.filtered) if not kb.editable)
            table.cursor_coordinate = (loop_row, 0)
            await pilot.press("d")
            await pilot.pause(0.2)
            top = app.screen_stack[-1]
            self.assertIsInstance(top, MessageModal)

        self.assertEqual(self.conf.read_text(), SAMPLE_LUA)

    async def test_escape_clears_search_then_returns_focus_to_table(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.press(*"close")
            await pilot.pause()
            search = app.query_one("#search", Input)
            self.assertEqual(search.value, "close")

            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(search.value, "")
            self.assertIs(app.focused, search)

            await pilot.press("escape")
            await pilot.pause()
            self.assertIs(app.focused, app.query_one(DataTable))

    async def test_every_write_creates_a_backup(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            await pilot.press("enter")
            await pilot.pause(0.2)
            field2 = app.screen.query_one("#field2", Input)
            field2.focus()
            field2.value = ""
            await pilot.pause()
            await pilot.press(*"hl.dsp.exec_cmd(terminal)")
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
        self.assertTrue(self.backup_dir.exists())
        backups = list(self.backup_dir.glob("hyprland.lua.*"))
        self.assertEqual(len(backups), 1)
        self.assertIn("close window", backups[0].read_text())

    async def test_reload_failure_shows_message_modal(self):
        with mock.patch.object(config, "reload_hyprland", return_value=(False, "simulated hyprctl failure")):
            app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(DataTable)
                table.focus()
                await pilot.press("r")
                await pilot.pause(0.3)
                top = app.screen_stack[-1]
                self.assertIsInstance(top, MessageModal)
                self.assertIn("simulated hyprctl failure", top.message)

    async def test_theme_persists_across_restart(self):
        app1 = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app1.run_test() as pilot:
            await pilot.pause()
            chosen = "nord" if "nord" in app1.available_themes else list(app1.available_themes)[2]
            app1.theme = chosen
            await pilot.pause()

        app2 = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app2.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(app2.theme, chosen)


class AppSourcePickerTest(unittest.IsolatedAsyncioTestCase):
    """The startup source picker: shown by default, skippable via
    --search or initial_source, and switchable later via 's'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.conf = self.tmp_path / "hyprland.lua"
        self.conf.write_text(SAMPLE_LUA)
        self.yazi_user = self.tmp_path / "keymap.toml"
        self.yazi_user.write_text(SAMPLE_YAZI_USER)
        state_dir = self.tmp_path / "state"
        self._patches = [
            mock.patch.object(config, "HYPR_LUA", self.conf),
            mock.patch.object(config, "BACKUP_DIR", self.tmp_path / "backups"),
            mock.patch.object(keybey_app, "STATE_DIR", state_dir),
            mock.patch.object(keybey_app, "THEME_FILE", state_dir / "theme"),
            mock.patch.object(yazi_config, "DEFAULT_KEYMAP", self.tmp_path / "no_yazi_defaults.toml"),
            mock.patch.object(yazi_config, "USER_KEYMAP", self.yazi_user),
            mock.patch.object(nvim_config, "NVIM_KEYMAPS_FILE", self.tmp_path / "no_nvim_keymaps.lua"),
            mock.patch.object(nvim_config, "NVIM_PLUGINS_DIR", self.tmp_path / "no_nvim_plugins"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_picker_shown_on_normal_launch_with_all_and_each_source(self):
        app = KeybeyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            top = app.screen_stack[-1]
            self.assertIsInstance(top, keybey_app.PickModal)
            self.assertEqual(top.options, [keybey_app.ALL_SOURCES, "hyprland", "yazi", "nvim"])
            # nothing loaded yet -- the picker blocks refresh_binds()
            self.assertEqual(app.keybinds, [])

    async def test_choosing_a_source_filters_to_only_that_source(self):
        app = KeybeyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.screen.query_one("ListView")
            list_view.index = 2  # "yazi", per the options order above
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertEqual(app.source_filter, "yazi")
            self.assertTrue(app.keybinds)  # hyprland contributed too, but...
            self.assertTrue(all(kb.source == "yazi" for kb in app.filtered))

    async def test_choosing_all_sources_shows_both(self):
        app = KeybeyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.screen.query_one("ListView")
            list_view.index = 0  # "All sources"
            await pilot.press("enter")
            await pilot.pause(0.2)
            sources_present = {kb.source for kb in app.filtered}
            self.assertEqual(sources_present, {"hyprland", "yazi"})

    async def test_escaping_picker_falls_back_to_all_sources(self):
        app = KeybeyApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(0.2)
            self.assertEqual(app.source_filter, keybey_app.ALL_SOURCES)

    async def test_search_flag_skips_picker_entirely(self):
        app = KeybeyApp(start_in_search=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertNotIsInstance(app.screen_stack[-1], keybey_app.PickModal)
            self.assertTrue(app.keybinds)

    async def test_initial_source_flag_skips_picker_and_pre_filters(self):
        app = KeybeyApp(initial_source="hyprland")
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertNotIsInstance(app.screen_stack[-1], keybey_app.PickModal)
            self.assertTrue(all(kb.source == "hyprland" for kb in app.filtered))

    async def test_s_key_reopens_picker_and_switches_source(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertTrue({kb.source for kb in app.filtered} >= {"hyprland"})
            await pilot.press("s")
            await pilot.pause(0.2)
            list_view = app.screen.query_one("ListView")
            list_view.index = 2  # "yazi"
            await pilot.press("enter")
            await pilot.pause(0.2)
            self.assertEqual(app.source_filter, "yazi")
            self.assertTrue(all(kb.source == "yazi" for kb in app.filtered))


class AppYaziSourceTest(unittest.IsolatedAsyncioTestCase):
    """Yazi-specific wiring: field labels, source-pick modal, and editing a
    yazi bind end to end -- with Hyprland patched to an empty config so it
    never contributes rows here."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.hypr_conf = self.tmp_path / "hyprland.lua"
        self.hypr_conf.write_text("")
        self.yazi_user = self.tmp_path / "keymap.toml"
        self.yazi_user.write_text(SAMPLE_YAZI_USER)
        self.backup_dir = self.tmp_path / "backups"
        state_dir = self.tmp_path / "state"
        self._patches = [
            mock.patch.object(config, "HYPR_LUA", self.hypr_conf),
            mock.patch.object(config, "BACKUP_DIR", self.backup_dir),
            mock.patch.object(keybey_app, "STATE_DIR", state_dir),
            mock.patch.object(keybey_app, "THEME_FILE", state_dir / "theme"),
            mock.patch.object(yazi_config, "DEFAULT_KEYMAP", self.tmp_path / "no_yazi_defaults.toml"),
            mock.patch.object(yazi_config, "USER_KEYMAP", self.yazi_user),
            mock.patch.object(nvim_config, "NVIM_KEYMAPS_FILE", self.tmp_path / "no_nvim_keymaps.lua"),
            mock.patch.object(nvim_config, "NVIM_PLUGINS_DIR", self.tmp_path / "no_nvim_plugins"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_yazi_bind_is_loaded_and_editable(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(len(app.keybinds), 1)
            kb = app.keybinds[0]
            self.assertEqual(kb.source, "yazi")
            self.assertEqual(kb.keys, "l")
            self.assertTrue(kb.editable)

    async def test_editing_yazi_bind_writes_only_keymap_toml(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            await pilot.press("enter")
            await pilot.pause(0.2)
            field3 = app.screen.query_one("#field3", Input)
            field3.focus()
            field3.value = ""
            await pilot.pause()
            await pilot.press(*"updated description")
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
        self.assertEqual(self.hypr_conf.read_text(), "")
        binds = yazi_config.load_user()
        self.assertEqual(binds[0].desc, "updated description")

    async def test_reload_is_a_noop_for_yazi_no_failure_modal(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            await pilot.press("r")
            await pilot.pause(0.3)
            self.assertEqual(len(app.screen_stack), 1)  # no MessageModal pushed


class AppNvimSourceTest(unittest.IsolatedAsyncioTestCase):
    """Neovim-specific wiring: editing a keymaps.lua bind end to end, plus
    the plugin-spec keys table showing up read-only -- with Hyprland and
    yazi patched to empty so neither contributes rows here."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.hypr_conf = self.tmp_path / "hyprland.lua"
        self.hypr_conf.write_text("")
        self.nvim_keymaps = self.tmp_path / "keymaps.lua"
        self.nvim_keymaps.write_text(
            'map("i", "jk", "<Esc>", { desc = "Exit insert mode" })\n'
        )
        self.nvim_plugins = self.tmp_path / "plugins"
        self.nvim_plugins.mkdir()
        (self.nvim_plugins / "ui.lua").write_text(
            'return {\n'
            '  "nvim-tree/nvim-tree.lua",\n'
            '  keys = {\n'
            '    { "<leader>e", "<cmd>NvimTreeToggle<CR>", desc = "Toggle file explorer" },\n'
            '  },\n'
            '}\n'
        )
        self.backup_dir = self.tmp_path / "backups"
        state_dir = self.tmp_path / "state"
        self._patches = [
            mock.patch.object(config, "HYPR_LUA", self.hypr_conf),
            mock.patch.object(config, "BACKUP_DIR", self.backup_dir),
            mock.patch.object(keybey_app, "STATE_DIR", state_dir),
            mock.patch.object(keybey_app, "THEME_FILE", state_dir / "theme"),
            mock.patch.object(yazi_config, "DEFAULT_KEYMAP", self.tmp_path / "no_yazi_defaults.toml"),
            mock.patch.object(yazi_config, "USER_KEYMAP", self.tmp_path / "no_yazi_user.toml"),
            mock.patch.object(nvim_config, "NVIM_KEYMAPS_FILE", self.nvim_keymaps),
            mock.patch.object(nvim_config, "NVIM_PLUGINS_DIR", self.nvim_plugins),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_editable_and_readonly_binds_both_load(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(len(app.keybinds), 2)
            editable = next(kb for kb in app.keybinds if kb.editable)
            readonly = next(kb for kb in app.keybinds if not kb.editable)
            self.assertEqual(editable.source, "nvim")
            self.assertIn("jk", editable.keys)
            self.assertEqual(readonly.context, "plugins/ui.lua")
            self.assertIn("<leader>e", readonly.keys)

    async def test_editing_nvim_bind_preserves_opts_and_writes_only_keymaps_lua(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            editable_row = next(i for i, kb in enumerate(app.filtered) if kb.editable)
            table.cursor_coordinate = (editable_row, 0)
            await pilot.press("enter")
            await pilot.pause(0.2)
            field2 = app.screen.query_one("#field2", Input)
            field2.focus()
            field2.value = ""
            await pilot.pause()
            await pilot.press(*"jj")
            await pilot.press("ctrl+s")
            await pilot.pause(0.3)
        self.assertEqual(self.hypr_conf.read_text(), "")
        text = self.nvim_keymaps.read_text()
        self.assertIn('"jj"', text)
        self.assertIn('desc = "Exit insert mode"', text, "original opts must be preserved untouched")

    async def test_deleting_readonly_plugin_spec_bind_refuses(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            readonly_row = next(i for i, kb in enumerate(app.filtered) if not kb.editable)
            table.cursor_coordinate = (readonly_row, 0)
            await pilot.press("d")
            await pilot.pause(0.2)
            top = app.screen_stack[-1]
            self.assertIsInstance(top, MessageModal)
        self.assertIn("<leader>e", self.nvim_plugins.joinpath("ui.lua").read_text())

    async def test_deleting_editable_bind_removes_only_that_line(self):
        app = KeybeyApp(initial_source=keybey_app.ALL_SOURCES)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one(DataTable)
            table.focus()
            editable_row = next(i for i, kb in enumerate(app.filtered) if kb.editable)
            table.cursor_coordinate = (editable_row, 0)
            await pilot.press("d")
            await pilot.pause(0.2)
            await pilot.press("y")
            await pilot.pause(0.3)
        self.assertEqual(self.nvim_keymaps.read_text().strip(), "")


if __name__ == "__main__":
    unittest.main()
