"""
Fuzzy-searchable browser and editor for keybinds across multiple tools --
currently Hyprland (hyprland.lua), yazi (keymap.toml + its own vendored
default keymap), and Neovim (keymaps.lua + plugin-spec `keys` tables).
Each tool is a Source (see keybind.py); this module only ever deals in
the generic Keybind type, never a source's native format.

Adding a new tool means writing one Source implementation (see
sources_hyprland.py / sources_yazi.py / sources_nvim.py for the shape)
and adding it to SOURCES below -- nothing else in this file needs to
know it exists.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, ListItem, ListView

from .keybind import Keybind, Source
from .sources_hyprland import HyprlandSource
from .sources_nvim import NvimSource
from .sources_yazi import YaziSource

SOURCES: list[Source] = [HyprlandSource(), YaziSource(), NvimSource()]

ALL_SOURCES = "All sources"
COLUMNS = ("Source", "Context", "Keys", "Action", "Description", "Editable")

STATE_DIR = Path.home() / ".local" / "state" / "keybey"
THEME_FILE = STATE_DIR / "theme"


def _load_saved_theme() -> str | None:
    try:
        return THEME_FILE.read_text().strip() or None
    except FileNotFoundError:
        return None


def _save_theme(name: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    THEME_FILE.write_text(name)


def _matches(kb: Keybind, query: str) -> bool:
    if not query:
        return True
    q = query.lower()
    haystack = " ".join([kb.source, kb.context, kb.keys, kb.action, kb.description]).lower()
    return q in haystack


def _source_by_name(name: str) -> Source:
    return next(s for s in SOURCES if s.name == name)


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message)
            yield Label("[y] confirm   [n/esc] cancel")

    def on_key(self, event) -> None:
        if event.key == "y":
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class MessageModal(ModalScreen[None]):
    BINDINGS = [Binding("escape", "ok", "OK"), Binding("enter", "ok", "OK")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.message)
            yield Label("[enter/esc] OK")

    def action_ok(self) -> None:
        self.dismiss(None)


class PickModal(ModalScreen[str | None]):
    """Generic single-choice list picker -- used both for the startup/
    switchable source filter and for choosing which source to add a new
    bind to."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, options: list[str]) -> None:
        super().__init__()
        self.title_text = title
        self.options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text)
            yield ListView(*[ListItem(Label(n)) for n in self.options])
            yield Label("[enter] choose   [esc] cancel")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        self.dismiss(self.options[index] if index is not None else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BindEditModal(ModalScreen[tuple[str, str, str] | None]):
    """Form to add or edit a bind: three raw fields, labeled per-source."""

    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "save", "Save")]

    def __init__(self, title: str, labels: tuple[str, str, str],
                 values: tuple[str, str, str] = ("", "", "")) -> None:
        super().__init__()
        self.title_text = title
        self.labels = labels
        self.initial = values

    def compose(self) -> ComposeResult:
        f1, f2, f3 = self.initial
        l1, l2, l3 = self.labels
        with Vertical(id="dialog"):
            yield Label(self.title_text)
            yield Label(l1)
            yield Input(value=f1, id="field1")
            yield Label(l2)
            yield Input(value=f2, id="field2")
            yield Label(l3)
            yield Input(value=f3, id="field3")
            yield Label("[enter/ctrl+s] save   [esc] cancel")

    def on_mount(self) -> None:
        self.query_one("#field1", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        f1 = self.query_one("#field1", Input).value.strip()
        f2 = self.query_one("#field2", Input).value.strip()
        f3 = self.query_one("#field3", Input).value.strip()
        if not f1 or not f2:
            self.app.bell()
            return
        self.dismiss((f1, f2, f3))


class KeybeyApp(App):
    CSS = """
    #dialog {
        width: 78;
        padding: 1 2;
        border: solid $accent;
        background: $panel;
    }
    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("a", "add_bind", "Add"),
        Binding("d", "delete_bind", "Delete"),
        Binding("r", "reload", "Reload"),
        Binding("s", "pick_source", "Source"),
        Binding("ctrl+r", "refresh_binds", "Refresh list"),
        Binding("slash", "focus_search", "Search", key_display="/"),
        Binding("escape", "clear_search", "Clear search", show=False),
        Binding("question_mark", "show_notation_help", "Notation", key_display="?"),
    ]

    def __init__(self, start_in_search: bool = False, initial_source: str | None = None) -> None:
        super().__init__()
        self.keybinds: list[Keybind] = []
        self.filtered: list[Keybind] = []
        self.start_in_search = start_in_search
        self.initial_source = initial_source
        self.source_filter: str = initial_source or ALL_SOURCES

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search binds... ('/' to focus, esc to clear)", id="search")
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def watch_theme(self, old_theme: str, new_theme: str) -> None:
        _save_theme(new_theme)

    def on_mount(self) -> None:
        saved_theme = _load_saved_theme()
        if saved_theme and saved_theme in self.available_themes:
            self.theme = saved_theme
        table = self.query_one(DataTable)
        for col in COLUMNS:
            table.add_column(col, key=col)
        self._startup()

    @work
    async def _startup(self) -> None:
        table = self.query_one(DataTable)
        if self.start_in_search or self.initial_source is not None:
            # --search is for the fast cheatsheet keybind -- skip the picker
            # and go straight to (optionally pre-filtered) results.
            self.refresh_binds()
            if self.start_in_search:
                self.query_one("#search", Input).focus()
            else:
                table.focus()
        else:
            chosen = await self.push_screen_wait(
                PickModal("View which source?", [ALL_SOURCES] + [s.name for s in SOURCES])
            )
            self.source_filter = chosen or ALL_SOURCES
            self.refresh_binds()
            table.focus()

    def _update_subtitle(self) -> None:
        self.sub_title = f"source: {self.source_filter}"

    @work
    async def action_pick_source(self) -> None:
        chosen = await self.push_screen_wait(
            PickModal("View which source?", [ALL_SOURCES] + [s.name for s in SOURCES])
        )
        if chosen is None:
            return
        self.source_filter = chosen
        self._apply_filter()

    def refresh_binds(self) -> None:
        self.keybinds = [kb for s in SOURCES for kb in s.load()]
        self._apply_filter()

    def action_refresh_binds(self) -> None:
        self.refresh_binds()

    def _apply_filter(self) -> None:
        self._update_subtitle()
        query = self.query_one("#search", Input).value
        rows = self.keybinds
        if self.source_filter != ALL_SOURCES:
            rows = [kb for kb in rows if kb.source == self.source_filter]
        rows = [kb for kb in rows if _matches(kb, query)]
        self.filtered = rows
        table = self.query_one(DataTable)
        table.clear()
        for kb in rows:
            table.add_row(kb.source, kb.context, kb.keys, kb.action, kb.description,
                           "yes" if kb.editable else "no")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self._apply_filter()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        search = self.query_one("#search", Input)
        if self.focused is search and search.value:
            search.value = ""
            self._apply_filter()
        else:
            self.query_one(DataTable).focus()

    def _selected_bind(self) -> Keybind | None:
        table = self.query_one(DataTable)
        if table.cursor_row is None or not self.filtered:
            return None
        if 0 <= table.cursor_row < len(self.filtered):
            return self.filtered[table.cursor_row]
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.edit_selected()

    async def _reload_and_notify(self, source: Source, force_message: bool = False) -> None:
        ok, output = await asyncio.to_thread(source.reload)
        if not ok:
            await self.push_screen_wait(MessageModal(f"{source.name} reload failed:\n{output}"))
        elif force_message:
            self.notify(f"{source.name} reloaded")

    @work
    async def edit_selected(self) -> None:
        kb = self._selected_bind()
        if kb is None:
            return
        if not kb.editable:
            await self.push_screen_wait(MessageModal(
                "This bind can't be safely edited here (it spans multiple lines, is "
                "generated in a loop, is a built-in default, or uses a multi-key/macro "
                f"value) -- edit its source config directly.\n\n{kb.raw}"
            ))
            return
        source = _source_by_name(kb.source)
        values = source.edit_values(kb)
        result = await self.push_screen_wait(
            BindEditModal("Edit bind", source.field_labels, values)
        )
        if result is None:
            return
        f1, f2, f3 = result
        await asyncio.to_thread(source.update, kb, f1, f2, f3)
        self.refresh_binds()
        await self._reload_and_notify(source)

    @work
    async def action_add_bind(self) -> None:
        addable = [s for s in SOURCES if s.can_add()]
        if not addable:
            return
        if len(addable) == 1:
            source = addable[0]
        else:
            chosen = await self.push_screen_wait(PickModal("Add bind to which source?", [s.name for s in addable]))
            if chosen is None:
                return
            source = _source_by_name(chosen)
        result = await self.push_screen_wait(BindEditModal("Add bind", source.field_labels))
        if result is None:
            return
        f1, f2, f3 = result
        await asyncio.to_thread(source.add, f1, f2, f3)
        self.refresh_binds()
        await self._reload_and_notify(source)

    @work
    async def action_delete_bind(self) -> None:
        kb = self._selected_bind()
        if kb is None:
            return
        if not kb.editable:
            await self.push_screen_wait(MessageModal(
                "This bind can't be safely deleted here (it spans multiple lines, is "
                "generated in a loop, is a built-in default, or uses a multi-key/macro "
                f"value) -- edit its source config directly.\n\n{kb.raw}"
            ))
            return
        confirmed = await self.push_screen_wait(
            ConfirmModal(f"Delete [{kb.source}] {kb.keys} -> {kb.action} ?")
        )
        if not confirmed:
            return
        source = _source_by_name(kb.source)
        await asyncio.to_thread(source.delete, kb)
        self.refresh_binds()
        await self._reload_and_notify(source)

    @work
    async def action_reload(self) -> None:
        for source in SOURCES:
            await self._reload_and_notify(source, force_message=True)

    @work
    async def action_show_notation_help(self) -> None:
        from . import nvim_config
        leader = nvim_config.get_leader()
        if leader is None:
            leader_line = "(not set / not found in init.lua)"
        elif leader == " ":
            leader_line = "Space"
        else:
            leader_line = f'"{leader}"'
        text = "\n".join([
            "Vim-style key notation -- used throughout Hyprland, yazi, and Neovim binds:",
            "",
            f"  <leader>        this config's leader key -- currently {leader_line}",
            "                  so <leader>w means: press leader, then w",
            "  <C-x>           Ctrl + x",
            "  <S-x>           Shift + x",
            "  <A-x> / <M-x>   Alt + x",
            "  <CR>            Enter / Return",
            "  <Esc>           Escape",
            "  <Space>         literal spacebar",
            "  <cmd>foo<CR>    runs the command \":foo\" for you (colon + Enter included)",
            "",
            "Anything wrapped in <...> is ONE key/command, however many characters long.",
        ])
        await self.push_screen_wait(MessageModal(text))


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Fuzzy-searchable keybind browser and editor (Hyprland, yazi, Neovim)")
    parser.add_argument("-s", "--search", action="store_true",
                         help="start with the search box focused, e.g. for a cheatsheet keybind")
    parser.add_argument("--source", choices=[s.name for s in SOURCES],
                         help="skip the startup source picker and go straight to this source "
                              "(press 's' inside keybey to switch later)")
    args = parser.parse_args()
    KeybeyApp(start_in_search=args.search, initial_source=args.source).run()


if __name__ == "__main__":
    main()
