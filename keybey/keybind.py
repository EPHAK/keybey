"""
Generic keybind representation and the Source protocol every tool-specific
backend (hyprland.py, yazi.py, ...) implements. This is the seam that lets
the app/search/table UI in app.py stay completely tool-agnostic: it only
ever sees Keybind and Source, never a source's own native types.

Each Source's `field_labels` names what its raw edit fields actually mean
(Hyprland: mods/dispatcher/options; yazi: key/run/description) so a single
generic 3-field edit form can serve every source without hardcoding any of
them into the UI layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Keybind:
    source: str       # which Source produced this, e.g. "hyprland", "yazi"
    context: str       # sub-scope within the source, e.g. "mgr", "input" (yazi); "" for hyprland
    keys: str          # display string of the trigger, e.g. "SUPER + Q" or "l"
    action: str        # display string of what it does
    description: str
    editable: bool
    raw: str           # exact source text, for display when not editable
    native: Any = None  # source-specific handle, opaque outside that Source


class Source(Protocol):
    name: str
    field_labels: tuple[str, str, str]

    def load(self) -> list[Keybind]:
        """Parse and return every keybind this source knows about, editable
        or not -- read-only entries are still shown for browsing/search."""
        ...

    def can_add(self) -> bool:
        """Whether this source currently supports adding a new bind at all
        (independent of any individual bind's editable flag)."""
        ...

    def edit_values(self, kb: Keybind) -> tuple[str, str, str]:
        """The three raw field values to prefill an edit form with."""
        ...

    def add(self, field1: str, field2: str, field3: str) -> None:
        ...

    def update(self, kb: Keybind, field1: str, field2: str, field3: str) -> None:
        ...

    def delete(self, kb: Keybind) -> None:
        ...

    def reload(self) -> tuple[bool, str]:
        """Apply the change live if this source's tool needs telling (e.g.
        `hyprctl reload`). Return (ok, message); message is shown on failure.
        Sources with nothing to do here (yazi reads its config fresh on
        every launch) just return (True, "")."""
        ...
