# keybey

A fuzzy-searchable browser and editor for keybinds across multiple
tools, in the terminal. Currently supports:

- **Hyprland** (0.56+'s Lua config, `hyprland.lua` -- the older
  INI-style `hyprland.conf` is no longer parsed by this Hyprland
  version at all, so that's what `keybey` targets directly)
- **yazi** (its own vendored default keymap, plus your
  `~/.config/yazi/keymap.toml` overrides)
- **Neovim** (`~/.config/nvim/lua/config/keymaps.lua`'s `map(...)`
  calls, plus lazy.nvim plugin specs' own `keys = {...}` tables in
  `lua/plugins/*.lua`, read-only)

All three are searched together in one list, so e.g. searching `l`
shows both yazi's default `l` → `enter` binding *and* your own override
of it in the same view -- the exact ambiguity ("why doesn't `l` work")
that motivated adding a second source in the first place.

Adding a new tool is one `Source` implementation (see
`keybey/keybind.py` for the protocol, `keybey/sources_hyprland.py`
or `keybey/sources_yazi.py` for examples) added to `SOURCES` in
`app.py` -- the search/table/edit UI is entirely tool-agnostic.

## Features

- Parses every `hl.bind(...)` call out of `hyprland.lua`, every keymap
  entry (defaults + your `prepend_keymap` overrides) out of yazi's
  config, and every `map(...)` call plus plugin-spec `keys` table entry
  out of your Neovim config
- Live fuzzy search across source, context, keys, action, and
  description (Hyprland modifiers matched against resolved variable
  values, e.g. `mainMod` → `SUPER`)
- Add, edit, and delete binds from the TUI, per source -- delete works
  the same way across every source that supports editing at all (not
  just Hyprland's)
- Every write is backed up first to `~/.local/state/keybey/backups/`
  before the config file is touched
- Reloads Hyprland (`hyprctl reload`) automatically after any Hyprland
  change (yazi and Neovim need no reload -- both read their config
  fresh on every launch)

### What's editable

**Hyprland**: only single-line, top-level `hl.bind(MODS, DISPATCHER,
OPTIONS)` statements can be edited or deleted -- the majority of a
typical config. Binds are shown read-only (still searchable) when
they:

- are generated inside a `for`/`while` loop (e.g. workspace 1-9 binds
  driven by a loop variable -- the literal text represents many binds
  parametrically, not one)
- use an inline `function() ... end` callback as their dispatcher
- have arguments wrapped across multiple lines for formatting

Editing any of those safely would need a real Lua parser, not line
surgery, so `keybey` refuses rather than risk corrupting them.

**yazi**: every entry from the vendored default keymap is read-only
(it's a point-in-time snapshot of upstream, not your actual config --
"editing" one wouldn't do anything real). Entries from your own
`keymap.toml` are editable unless their `on` or `run` is a multi-key
sequence or macro chain (a TOML array rather than a plain string) --
flattening one of those to a single value on edit would silently
change what it does, so those are shown read-only too. Adding a new
yazi bind always targets the `mgr` context's `prepend_keymap` (the
main file-list keymap, and what covers the large majority of real
remaps); other contexts (`input`, `tasks`, ...) are browsable and
editable if already simple, but not currently addable from here.

**Neovim**: entries from `lua/config/keymaps.lua` are editable when
the whole call is `map("mode", "lhs", "rhs")` on one line with mode/
lhs/rhs all plain string literals -- covers the large majority of a
typical keymaps file. Shown read-only when the rhs is a function
reference (`vim.lsp.buf.definition`, an anonymous function, etc. --
not representable as a plain string without losing what it actually
does) or the mode is a table (`{ "n", "v" }` rather than a single
mode). Any trailing options table (e.g. `{ desc = "..." }`) is left
completely untouched on edit -- keybey only has fields for mode/lhs/
rhs, so silently regenerating that table would drop the description;
instead the original text is preserved byte-for-byte. Adding a new
bind never includes a description for the same reason (hand-edit the
file afterwards if you want one). Every entry from a plugin spec's own
`keys = {...}` table (`lua/plugins/*.lua`) is always read-only --
editing one safely would mean parsing and rewriting a table nested
inside an arbitrary plugin spec, a real Lua-parsing problem, not line
surgery.

## Usage

```bash
keybey                 # opens into a source picker: All sources / hyprland / yazi / nvim
kb                     # same thing -- short alias
keybey --source yazi   # skip the picker, start filtered to one source
keybey --search        # opens with the search box focused, filtered to
                        # All sources -- skips the picker entirely, handy
                        # bound to a key as a live, searchable keybind
                        # cheatsheet, e.g.
                        # hl.bind(mainMod .. " + SHIFT + slash",
                        #   hl.dsp.exec_cmd("kitty kb --search"),
                        #   { description = "keybind cheatsheet" })
```

| Key | Action |
|---|---|
| `↑` / `↓` | Move selection |
| `Enter` | Edit selected bind (or view why it can't be edited) |
| `a` | Add a new bind -- prompts for which source if more than one supports it |
| `d` | Delete selected bind |
| `s` | Switch the source filter (same picker shown at startup) |
| `r` | Reload all sources (Hyprland: `hyprctl reload`; yazi: no-op) |
| `Ctrl+R` | Refresh the list from disk |
| `/` | Focus search |
| `Esc` | Clear search, then return focus to the list |
| `?` | Show the vim-style key-notation legend (`<leader>`, `<C-x>`, `<cmd>...<CR>`, etc. -- reads your real `mapleader` from `init.lua` rather than assuming Space) |
| `q` | Quit |

Inside the add/edit form: `Enter` in any field, or `Ctrl+S`, saves.
`Esc` cancels. Field labels and expected syntax change per source --
Hyprland's three fields are raw Lua expressions (e.g. `mainMod .. "
+ Q"`, `hl.dsp.window.close()`, `{ description = "..." }`); yazi's are
a plain key, a plain run command, and a plain description (e.g. `l`,
`plugin smart-enter`, `Enter the child directory, or open the file`);
Neovim's are a plain mode, key, and command (e.g. `n`, `<leader>w`,
`<cmd>write<CR>`).

## Requirements

- Hyprland 0.56+ with the Lua config provider (`hyprctl systeminfo`
  should show `configProvider: lua`), for the Hyprland source
- yazi, for the yazi source
- Neovim, for the Neovim source (expects `lua/config/keymaps.lua` and
  `lua/plugins/*.lua`, i.e. a kickstart/lazy.nvim-style layout)
- Python 3.10+
- `python-textual`, `python-tomlkit`

```bash
pip install textual tomlkit
```

## Installation

```bash
git clone https://github.com/EPHAK/keybey.git
ln -s "$(pwd)/keybey/bin/keybey" ~/.local/bin/keybey
ln -s "$(pwd)/keybey/bin/keybey" ~/.local/bin/kb   # short alias
```

Ensure `~/.local/bin` is on your `PATH`.

## How it works

`keybey` scans `hyprland.lua` for `hl.bind(...)` call sites. A bind is
editable only if its entire call sits on one physical line with no
leading indentation; everything else is parsed for display/search but
locked against writes. Edits rewrite the matched line in place,
preserving its original indentation; deletes remove it; adds append to
the end of the file. Every one of those writes first copies the whole
file to a timestamped backup under `~/.local/state/keybey/backups/`, so a
bad edit is always one `cp` away from undone.

Modifiers are shown resolved (`mainMod` → `SUPER`, via `local NAME =
"VALUE"` declarations at the top of the file) and searched in their
resolved form, but stored and edited as whatever the underlying Lua
expression actually contains.

yazi has no on-disk file for its *default* keymap -- it's compiled
into the binary -- so `keybey` ships a vendored snapshot
(`keybey/data/yazi_default_keymap.toml`, fetched from upstream's
`shipped` branch) purely for browsing/searching those defaults; it's
never written to. Your real, editable config is
`~/.config/yazi/keymap.toml`, parsed and edited with `tomlkit` so
writes preserve formatting rather than reformatting the whole file.
Same backup-before-write guarantee as Hyprland.

Neovim's config isn't one file -- `lua/config/keymaps.lua` is scanned
line by line for `map("mode", "lhs", "rhs")` calls (the `map` alias for
`vim.keymap.set` this user's config already uses), backed up and edited
the same way as Hyprland's single-line binds; `lua/plugins/*.lua` is
scanned separately (brace-depth-aware, to correctly split entries like
`{ "s", mode = { "n", "x", "o" }, desc = "..." }` where a naive regex
would stop at the nested table's closing brace) purely for search --
never written to. mode/lhs/rhs are escaped and unescaped through Lua
string-literal quoting on write/read, so a value containing a literal
`"` (e.g. `echo "probe"`) round-trips correctly instead of producing
broken Lua.

All three sources implement the same `Source` protocol
(`keybey/keybind.py`); `app.py`'s table, search, and edit UI only ever
see the generic `Keybind` type it defines, never a source's own native
format.

## License

[MIT](LICENSE)
