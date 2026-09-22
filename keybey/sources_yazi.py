"""Adapts yazi_config.py to the generic Source protocol."""
from __future__ import annotations

from . import yazi_config
from .keybind import Keybind


class YaziSource:
    name = "yazi"
    field_labels = ("Key (e.g. l, g h)", "Run (e.g. plugin smart-enter)", "Description")

    def load(self) -> list[Keybind]:
        binds = yazi_config.load_defaults() + yazi_config.load_user()
        return [self._to_keybind(b) for b in binds]

    def _to_keybind(self, b: yazi_config.YaziBind) -> Keybind:
        return Keybind(
            source=self.name,
            context=b.context,
            keys=b.on,
            action=b.run,
            description=b.desc,
            editable=b.editable,
            raw=b.raw,
            native=b,
        )

    def can_add(self) -> bool:
        return True

    def edit_values(self, kb: Keybind) -> tuple[str, str, str]:
        native: yazi_config.YaziBind = kb.native
        return native.on, native.run, native.desc

    def add(self, field1: str, field2: str, field3: str) -> None:
        yazi_config.add_bind(field1, field2, field3)

    def update(self, kb: Keybind, field1: str, field2: str, field3: str) -> None:
        yazi_config.update_bind(kb.native, field1, field2, field3)

    def delete(self, kb: Keybind) -> None:
        yazi_config.delete_bind(kb.native)

    def reload(self) -> tuple[bool, str]:
        return True, ""
