"""Adapts nvim_config.py to the generic Source protocol."""
from __future__ import annotations

from . import nvim_config
from .keybind import Keybind


class NvimSource:
    name = "nvim"
    field_labels = ("Mode (e.g. n, i, v)", "Key (LHS)", "Command (RHS)")

    def load(self) -> list[Keybind]:
        binds = nvim_config.load_editable() + nvim_config.load_readonly_plugin_keys()
        return [self._to_keybind(b) for b in binds]

    def _to_keybind(self, b: nvim_config.NvimBind) -> Keybind:
        return Keybind(
            source=self.name,
            context=b.file,
            keys=f"[{b.mode}] {b.lhs}",
            action=b.rhs,
            description=b.desc,
            editable=b.editable,
            raw=b.raw,
            native=b,
        )

    def can_add(self) -> bool:
        return True

    def edit_values(self, kb: Keybind) -> tuple[str, str, str]:
        native: nvim_config.NvimBind = kb.native
        return native.mode, native.lhs, native.rhs

    def add(self, field1: str, field2: str, field3: str) -> None:
        nvim_config.add_bind(field1, field2, field3)

    def update(self, kb: Keybind, field1: str, field2: str, field3: str) -> None:
        nvim_config.update_bind(kb.native, field1, field2, field3)

    def delete(self, kb: Keybind) -> None:
        nvim_config.delete_bind(kb.native)

    def reload(self) -> tuple[bool, str]:
        return True, ""
