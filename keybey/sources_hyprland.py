"""
Adapts the existing, well-tested config.py (Hyprland's hyprland.lua parser
and editor) to the generic Source protocol. config.py itself is untouched --
this is purely a translation layer between config.Bind and keybind.Keybind.
"""
from __future__ import annotations

from . import config
from .keybind import Keybind


class HyprlandSource:
    name = "hyprland"
    field_labels = ("Mods (Lua)", "Dispatcher (Lua)", "Options (Lua table)")

    def __init__(self) -> None:
        self._variables: dict[str, str] = {}

    def load(self) -> list[Keybind]:
        binds, variables = config.load()
        self._variables = variables
        return [self._to_keybind(b) for b in binds]

    def _to_keybind(self, b: config.Bind) -> Keybind:
        return Keybind(
            source=self.name,
            context="",
            keys=b.resolved_mods(self._variables),
            action=b.dispatcher or "(spans multiple lines)",
            description=b.description(),
            editable=b.editable,
            raw=b.raw,
            native=b,
        )

    def can_add(self) -> bool:
        return True

    def edit_values(self, kb: Keybind) -> tuple[str, str, str]:
        native: config.Bind = kb.native
        return native.mods, native.dispatcher, native.options

    def add(self, field1: str, field2: str, field3: str) -> None:
        config.add_bind(field1, field2, field3)

    def update(self, kb: Keybind, field1: str, field2: str, field3: str) -> None:
        config.update_bind(kb.native, field1, field2, field3)

    def delete(self, kb: Keybind) -> None:
        config.delete_bind(kb.native)

    def reload(self) -> tuple[bool, str]:
        return config.reload_hyprland()
