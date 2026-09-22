"""
Parses and edits yazi's keybinds: the vendored copy of yazi's own default
keymap (data/yazi_default_keymap.toml -- yazi compiles its defaults into
the binary, there's no such file on a user's disk to read at runtime, so a
snapshot is bundled here instead; see fetch note below) plus the user's own
override file (~/.config/yazi/keymap.toml), which uses TOML array-of-tables
per context, e.g.:

    [[mgr.prepend_keymap]]
    on   = "l"
    run  = "plugin smart-enter"
    desc = "Enter the child directory, or open the file"

Default entries are always read-only (browsable/searchable only -- they're
a point-in-time snapshot of upstream, not this user's actual config, so
"editing" one wouldn't do anything real). User-keymap entries are editable
UNLESS their `on` or `run` is a TOML array rather than a plain string (a
multi-key sequence or macro chain) -- flattening one of those to a single
string on edit would silently change its meaning, so those are shown
read-only too, the same "refuse rather than risk corruption" rule
config.py applies to Hyprland's loop/function binds.

Only the "mgr" context is supported for adding new binds (v1) -- it's
yazi's main file-list keymap and covers the overwhelming majority of
real remaps (this is also the context the smart-enter plugin's own
documented setup uses). Vendored snapshot fetched from:
https://raw.githubusercontent.com/sxyazi/yazi/shipped/yazi-config/preset/keymap-default.toml
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from . import config

DEFAULT_KEYMAP = Path(__file__).parent / "data" / "yazi_default_keymap.toml"
USER_KEYMAP = Path.home() / ".config" / "yazi" / "keymap.toml"
ADD_CONTEXT = "mgr"


@dataclass
class YaziBind:
    context: str
    on: str
    run: str
    desc: str
    editable: bool
    raw: str
    array_index: int | None = None


def _display(value) -> str:
    if isinstance(value, list):
        return " -> ".join(str(v) for v in value)
    return str(value) if value is not None else ""


def _raw(context: str, entry: dict) -> str:
    parts = [f'on = "{entry.get("on", "")}"', f'run = {entry.get("run", "")!r}']
    if entry.get("desc"):
        parts.append(f'desc = "{entry["desc"]}"')
    return f"[{context}] " + ", ".join(parts)


def load_defaults(path: Path | None = None) -> list[YaziBind]:
    path = DEFAULT_KEYMAP if path is None else path
    if not path.exists():
        return []
    with path.open("rb") as f:
        doc = tomllib.load(f)
    binds: list[YaziBind] = []
    for context, section in doc.items():
        if not isinstance(section, dict):
            continue
        for entry in section.get("keymap", []):
            binds.append(YaziBind(
                context=context,
                on=_display(entry.get("on")),
                run=_display(entry.get("run")),
                desc=entry.get("desc", ""),
                editable=False,
                raw=_raw(context, entry),
            ))
    return binds


def load_user(path: Path | None = None) -> list[YaziBind]:
    path = USER_KEYMAP if path is None else path
    if not path.exists():
        return []
    with path.open("rb") as f:
        doc = tomllib.load(f)
    binds: list[YaziBind] = []
    for context, section in doc.items():
        if not isinstance(section, dict):
            continue
        for i, entry in enumerate(section.get("prepend_keymap", [])):
            simple = not isinstance(entry.get("on"), list) and not isinstance(entry.get("run"), list)
            binds.append(YaziBind(
                context=context,
                on=_display(entry.get("on")),
                run=_display(entry.get("run")),
                desc=entry.get("desc", ""),
                editable=simple,
                raw=_raw(context, entry),
                array_index=i,
            ))
    return binds


def _load_doc(path: Path) -> tomlkit.TOMLDocument:
    if path.exists():
        return tomlkit.parse(path.read_text())
    return tomlkit.document()


def _ensure_prepend_array(doc: tomlkit.TOMLDocument, context: str) -> tomlkit.items.AoT:
    if context not in doc:
        doc[context] = tomlkit.table()
    table = doc[context]
    if "prepend_keymap" not in table:
        table["prepend_keymap"] = tomlkit.aot()
    return table["prepend_keymap"]


def add_bind(on: str, run: str, desc: str) -> None:
    USER_KEYMAP.parent.mkdir(parents=True, exist_ok=True)
    if USER_KEYMAP.exists():
        config.backup(USER_KEYMAP)
    doc = _load_doc(USER_KEYMAP)
    arr = _ensure_prepend_array(doc, ADD_CONTEXT)
    entry = tomlkit.table()
    entry["on"] = on
    entry["run"] = run
    if desc:
        entry["desc"] = desc
    arr.append(entry)
    USER_KEYMAP.write_text(tomlkit.dumps(doc))


def update_bind(target: YaziBind, on: str, run: str, desc: str) -> None:
    if not target.editable or target.array_index is None:
        raise ValueError("this bind is a default, or has a multi-key/macro value; edit keymap.toml directly")
    config.backup(USER_KEYMAP)
    doc = _load_doc(USER_KEYMAP)
    entry = doc[target.context]["prepend_keymap"][target.array_index]
    entry["on"] = on
    entry["run"] = run
    if desc:
        entry["desc"] = desc
    elif "desc" in entry:
        del entry["desc"]
    USER_KEYMAP.write_text(tomlkit.dumps(doc))


def delete_bind(target: YaziBind) -> None:
    if not target.editable or target.array_index is None:
        raise ValueError("this bind is a default, or has a multi-key/macro value; edit keymap.toml directly")
    config.backup(USER_KEYMAP)
    doc = _load_doc(USER_KEYMAP)
    del doc[target.context]["prepend_keymap"][target.array_index]
    USER_KEYMAP.write_text(tomlkit.dumps(doc))
