"""
Parses and edits Neovim keymaps. Two very different sources, matching the
"refuse rather than risk corruption" rule the other sources already follow:

- ~/.config/nvim/lua/config/keymaps.lua -- this user's dedicated general
  keymaps file, using a `local map = vim.keymap.set` alias. Only single-line
  `map("mode", "lhs", "rhs")` calls (mode/lhs/rhs all plain string literals,
  not a table or a function ref) are editable; anything else on that line
  (a trailing opts table, e.g. `{ desc = "..." }`) is preserved byte-for-byte
  on edit, never regenerated -- keybey doesn't have a field for it, so the
  safe thing is to leave it alone rather than silently drop it.
- lua/plugins/*.lua -- lazy.nvim plugin specs can bind keys via their own
  `keys = { {...}, ... }` table. These are ALWAYS read-only here: editing
  one safely would mean parsing and rewriting a table nested inside an
  arbitrary plugin spec, which is a real Lua-parsing problem, not line
  surgery. They're still parsed for search/browse, best-effort -- a few
  unusual entries failing to parse only means they're missing from search
  results, never a corruption risk, since this path is never written to.

Every write (update_bind, delete_bind, add_bind) copies keymaps.lua to a
timestamped backup under ~/.local/state/keybey/backups/ first, same as
every other source.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import config

NVIM_KEYMAPS_FILE = Path.home() / ".config" / "nvim" / "lua" / "config" / "keymaps.lua"
NVIM_PLUGINS_DIR = Path.home() / ".config" / "nvim" / "lua" / "plugins"
NVIM_INIT_FILE = Path.home() / ".config" / "nvim" / "init.lua"

LEADER_RE = re.compile(r'vim\.g\.mapleader\s*=\s*"((?:[^"\\]|\\.)*)"')


def get_leader() -> str | None:
    """Read the real `vim.g.mapleader` value from init.lua, for display in
    the notation help screen -- rather than hardcoding "Space", since
    leader is user-configurable and this should stay true if it's ever
    changed."""
    if not NVIM_INIT_FILE.exists():
        return None
    m = LEADER_RE.search(NVIM_INIT_FILE.read_text())
    if not m:
        return None
    return m.group(1)

# map("mode", "lhs", "rhs" [, {opts}])  -- opts, if present, is captured
# whole (group 4) and never touched on edit.
MAP_CALL_RE = re.compile(
    r'^map\(\s*"([^"]*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*(,\s*(.*))?\)\s*$'
)
DESC_RE = re.compile(r'desc\s*=\s*"([^"]*)"')


@dataclass
class NvimBind:
    file: str  # display path, e.g. "config/keymaps.lua" or "plugins/telescope.lua"
    line_no: int
    mode: str
    lhs: str
    rhs: str
    desc: str
    editable: bool
    raw: str
    opts_suffix: str = ""  # e.g. ', { desc = "..." }' -- preserved verbatim


def load_editable(path: Path | None = None) -> list[NvimBind]:
    path = NVIM_KEYMAPS_FILE if path is None else path
    if not path.exists():
        return []
    binds: list[NvimBind] = []
    for i, line in enumerate(path.read_text().splitlines()):
        stripped = line.strip()
        m = MAP_CALL_RE.match(stripped)
        if not m:
            continue
        mode, lhs, rhs, opts_group, opts_inner = m.groups()
        opts_suffix = opts_group or ""
        desc_m = DESC_RE.search(opts_suffix)
        binds.append(NvimBind(
            file="config/keymaps.lua",
            line_no=i + 1,
            mode=_lua_unescape(mode),
            lhs=_lua_unescape(lhs),
            rhs=_lua_unescape(rhs),
            desc=desc_m.group(1) if desc_m else "",
            editable=True,
            raw=stripped,
            opts_suffix=opts_suffix,
        ))
    return binds


def _extract_keys_block(text: str, start_idx: int) -> tuple[str, int]:
    """Given the index right after `keys = {`, return (block_text, end_idx)
    by tracking brace depth."""
    depth = 1
    i = start_idx
    n = len(text)
    while i < n and depth > 0:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return text[start_idx:i - 1], i


def _split_top_level_entries(block: str) -> list[str]:
    """Split a `{ {...}, {...}, ... }` array's inner content into each
    top-level `{...}` entry, respecting brace nesting (e.g. a `mode = {
    "n", "x" }` sub-table inside an entry must not be mistaken for the
    entry's own closing brace)."""
    entries = []
    depth = 0
    start = None
    for i, c in enumerate(block):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                entries.append(block[start:i + 1])
                start = None
    return entries


def load_readonly_plugin_keys(plugins_dir: Path | None = None) -> list[NvimBind]:
    plugins_dir = NVIM_PLUGINS_DIR if plugins_dir is None else plugins_dir
    if not plugins_dir.exists():
        return []
    binds: list[NvimBind] = []
    for lua_file in sorted(plugins_dir.glob("*.lua")):
        text = lua_file.read_text()
        for km in re.finditer(r"keys\s*=\s*\{", text):
            block, _ = _extract_keys_block(text, km.end())
            line_no = text[: km.start()].count("\n") + 1
            for entry in _split_top_level_entries(block):
                lhs_m = re.match(r'\{\s*"((?:[^"\\]|\\.)*)"', entry)
                if not lhs_m:
                    continue
                desc_m = DESC_RE.search(entry)
                mode_m = re.search(r'mode\s*=\s*"([^"]*)"', entry)
                binds.append(NvimBind(
                    file=f"plugins/{lua_file.name}",
                    line_no=line_no,
                    mode=mode_m.group(1) if mode_m else "n",
                    lhs=lhs_m.group(1),
                    rhs="(plugin spec keys table)",
                    desc=desc_m.group(1) if desc_m else "",
                    editable=False,
                    raw=entry.strip(),
                ))
    return binds


def _lua_escape(s: str) -> str:
    """Escape backslashes and double quotes for embedding in a Lua
    double-quoted string literal. Without this, an rhs/lhs containing a
    literal `"` (e.g. `<cmd>echo "probe"<CR>`) would terminate the string
    early and produce syntactically broken Lua."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _lua_unescape(s: str) -> str:
    """Inverse of _lua_escape -- MAP_CALL_RE's `(?:[^"\\]|\\.)*` captures
    the raw escaped text (e.g. `\\"`) verbatim; this turns it back into the
    real string value."""
    return re.sub(r'\\(["\\])', r"\1", s)


def add_bind(mode: str, lhs: str, rhs: str) -> None:
    NVIM_KEYMAPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if NVIM_KEYMAPS_FILE.exists():
        config.backup(NVIM_KEYMAPS_FILE)
    text = NVIM_KEYMAPS_FILE.read_text() if NVIM_KEYMAPS_FILE.exists() else ""
    sep = "" if not text or text.endswith("\n") else "\n"
    mode, lhs, rhs = _lua_escape(mode), _lua_escape(lhs), _lua_escape(rhs)
    text += f'{sep}map("{mode}", "{lhs}", "{rhs}")\n'
    NVIM_KEYMAPS_FILE.write_text(text)


def update_bind(target: NvimBind, mode: str, lhs: str, rhs: str) -> None:
    if not target.editable:
        raise ValueError("this bind is defined in a plugin spec (lua/plugins/*.lua); edit it directly")
    config.backup(NVIM_KEYMAPS_FILE)
    lines = NVIM_KEYMAPS_FILE.read_text().splitlines(keepends=True)
    idx = target.line_no - 1
    original = lines[idx]
    indent = original[: len(original) - len(original.lstrip())]
    newline = "\n" if original.endswith("\n") else ""
    mode, lhs, rhs = _lua_escape(mode), _lua_escape(lhs), _lua_escape(rhs)
    lines[idx] = f'{indent}map("{mode}", "{lhs}", "{rhs}"{target.opts_suffix}){newline}'
    NVIM_KEYMAPS_FILE.write_text("".join(lines))


def delete_bind(target: NvimBind) -> None:
    if not target.editable:
        raise ValueError("this bind is defined in a plugin spec (lua/plugins/*.lua); edit it directly")
    config.backup(NVIM_KEYMAPS_FILE)
    lines = NVIM_KEYMAPS_FILE.read_text().splitlines(keepends=True)
    del lines[target.line_no - 1]
    NVIM_KEYMAPS_FILE.write_text("".join(lines))
