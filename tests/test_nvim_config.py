import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keybey import config, nvim_config


SAMPLE_KEYMAPS = '''\
local map = vim.keymap.set

map("i", "jk", "<Esc>", { desc = "Exit insert mode" })
map("n", "<leader>w", "<cmd>write<CR>")
map("n", "gd", vim.lsp.buf.definition, { desc = "Goto definition" })
map({ "n", "v" }, "<leader>x", "<cmd>x<CR>", { desc = "multi-mode, not editable" })
'''

SAMPLE_PLUGIN = '''\
return {
	{
		"nvim-tree/nvim-tree.lua",
		keys = {
			{ "<leader>e", "<cmd>NvimTreeToggle<CR>", desc = "Toggle file explorer" },
		},
	},
	{
		"folke/flash.nvim",
		keys = {
			{ "s", mode = { "n", "x", "o" }, desc = "Flash jump" },
			{ "S", mode = { "n", "x", "o" }, desc = "Flash treesitter" },
		},
	},
}
'''


class NvimConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.keymaps_path = self.tmp_path / "keymaps.lua"
        self.keymaps_path.write_text(SAMPLE_KEYMAPS)
        self.plugins_dir = self.tmp_path / "plugins"
        self.plugins_dir.mkdir()
        (self.plugins_dir / "ui.lua").write_text(SAMPLE_PLUGIN)
        self.backup_dir = self.tmp_path / "backups"
        self._patches = [
            mock.patch.object(nvim_config, "NVIM_KEYMAPS_FILE", self.keymaps_path),
            mock.patch.object(config, "BACKUP_DIR", self.backup_dir),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_simple_string_calls_are_editable(self):
        binds = nvim_config.load_editable()
        simple = [b for b in binds if b.lhs == "jk"]
        self.assertEqual(len(simple), 1)
        b = simple[0]
        self.assertTrue(b.editable)
        self.assertEqual(b.mode, "i")
        self.assertEqual(b.rhs, "<Esc>")
        self.assertEqual(b.desc, "Exit insert mode")

    def test_call_without_opts_table_is_editable(self):
        binds = nvim_config.load_editable()
        b = next(b for b in binds if b.lhs == "<leader>w")
        self.assertTrue(b.editable)
        self.assertEqual(b.opts_suffix, "")

    def test_function_ref_rhs_is_not_editable(self):
        binds = nvim_config.load_editable()
        # vim.lsp.buf.definition isn't a quoted string -> MAP_CALL_RE won't
        # match at all, so it's simply absent from load_editable()'s results
        # (not silently mis-parsed as editable).
        self.assertFalse(any(b.rhs == "vim.lsp.buf.definition" for b in binds))

    def test_multimode_table_bind_is_not_matched_as_editable(self):
        binds = nvim_config.load_editable()
        self.assertFalse(any(b.lhs == "<leader>x" for b in binds))

    def test_total_editable_count(self):
        # 4 map(...) calls total; only 2 have string mode/lhs/rhs literals
        # (jk, <leader>w) -- the other two (function ref, table mode) don't
        # match MAP_CALL_RE at all.
        binds = nvim_config.load_editable()
        self.assertEqual(len(binds), 2)

    def test_missing_keymaps_file_returns_empty(self):
        with mock.patch.object(nvim_config, "NVIM_KEYMAPS_FILE", self.tmp_path / "nope.lua"):
            self.assertEqual(nvim_config.load_editable(), [])

    def test_readonly_plugin_keys_are_parsed_across_files(self):
        binds = nvim_config.load_readonly_plugin_keys(self.plugins_dir)
        self.assertEqual(len(binds), 3)
        self.assertTrue(all(not b.editable for b in binds))
        explorer = next(b for b in binds if b.lhs == "<leader>e")
        self.assertEqual(explorer.desc, "Toggle file explorer")
        self.assertEqual(explorer.file, "plugins/ui.lua")
        flash = next(b for b in binds if b.lhs == "s")
        self.assertEqual(flash.desc, "Flash jump")

    def test_missing_plugins_dir_returns_empty(self):
        self.assertEqual(nvim_config.load_readonly_plugin_keys(self.tmp_path / "nope"), [])

    def test_update_bind_preserves_opts_suffix_and_rest_of_file(self):
        binds = nvim_config.load_editable()
        target = next(b for b in binds if b.lhs == "jk")
        nvim_config.update_bind(target, "i", "jj", "<Esc>")
        binds = nvim_config.load_editable()
        changed = next(b for b in binds if b.lhs == "jj")
        self.assertEqual(changed.desc, "Exit insert mode")
        # unrelated bind untouched
        untouched = next(b for b in binds if b.lhs == "<leader>w")
        self.assertEqual(untouched.rhs, "<cmd>write<CR>")

    def test_update_bind_refuses_non_editable(self):
        from keybey.nvim_config import NvimBind
        fake = NvimBind(file="plugins/x.lua", line_no=1, mode="n", lhs="x", rhs="y", desc="", editable=False, raw="")
        with self.assertRaises(ValueError):
            nvim_config.update_bind(fake, "n", "x", "y")

    def test_update_bind_backs_up_first(self):
        binds = nvim_config.load_editable()
        target = next(b for b in binds if b.lhs == "jk")
        nvim_config.update_bind(target, "i", "jj", "<Esc>")
        backups = list(self.backup_dir.glob("keymaps.lua.*"))
        self.assertEqual(len(backups), 1)
        self.assertIn("jk", backups[0].read_text())

    def test_delete_bind_removes_only_target_line(self):
        binds = nvim_config.load_editable()
        target = next(b for b in binds if b.lhs == "jk")
        nvim_config.delete_bind(target)
        remaining = nvim_config.load_editable()
        self.assertNotIn("jk", [b.lhs for b in remaining])
        still_there = next(b for b in remaining if b.lhs == "<leader>w")
        self.assertEqual(still_there.rhs, "<cmd>write<CR>")

    def test_delete_bind_refuses_non_editable(self):
        from keybey.nvim_config import NvimBind
        fake = NvimBind(file="plugins/x.lua", line_no=1, mode="n", lhs="x", rhs="y", desc="", editable=False, raw="")
        with self.assertRaises(ValueError):
            nvim_config.delete_bind(fake)

    def test_add_bind_appends_without_opts(self):
        nvim_config.add_bind("n", "<leader>z", "<cmd>zzz<CR>")
        binds = nvim_config.load_editable()
        new = next(b for b in binds if b.lhs == "<leader>z")
        self.assertTrue(new.editable)
        self.assertEqual(new.rhs, "<cmd>zzz<CR>")
        self.assertEqual(new.opts_suffix, "")

    def test_add_bind_escapes_embedded_quotes(self):
        """Regression: an rhs containing a literal `"` (e.g. an embedded
        shell string) must not produce broken Lua -- the written line has
        to remain parseable by load_editable() itself."""
        nvim_config.add_bind("n", "ZZ", 'echo "probe"')
        text = nvim_config.NVIM_KEYMAPS_FILE.read_text()
        self.assertIn('\\"probe\\"', text)
        binds = nvim_config.load_editable()
        new = next(b for b in binds if b.lhs == "ZZ")
        self.assertEqual(new.rhs, 'echo "probe"')

    def test_update_bind_escapes_embedded_quotes(self):
        binds = nvim_config.load_editable()
        target = next(b for b in binds if b.lhs == "jk")
        nvim_config.update_bind(target, "i", "jk", 'echo "probe"')
        binds = nvim_config.load_editable()
        changed = next(b for b in binds if b.lhs == "jk")
        self.assertEqual(changed.rhs, 'echo "probe"')

    def test_add_bind_creates_file_if_missing(self):
        fresh = self.tmp_path / "fresh_keymaps.lua"
        with mock.patch.object(nvim_config, "NVIM_KEYMAPS_FILE", fresh):
            nvim_config.add_bind("n", "<leader>z", "<cmd>zzz<CR>")
            binds = nvim_config.load_editable()
            self.assertEqual(len(binds), 1)
            self.assertEqual(binds[0].lhs, "<leader>z")


if __name__ == "__main__":
    unittest.main()
