"""
Parses and edits key bindings in Hyprland's Lua config (hyprland.lua),
used by Hyprland 0.56+ when configProvider is "lua" (confirmed via
`hyprctl systeminfo` -- `configProvider: lua`). The older INI-style
hyprland.conf is a dead stub on this Hyprland version ("no longer
parsed correctly", per its own header comment); hyprland.lua is the
real source of truth, so that's what this module targets.

A bind is only treated as EDITABLE if its whole `hl.bind(MODS,
DISPATCHER, OPTIONS)` call sits on one physical line with no leading
indentation and nothing else on that line. That rules out, deliberately:
  - binds generated inside a `for`/`while` loop (indented -- the
    literal call text represents many binds parametrically via a loop
    variable, not one concrete bind)
  - binds whose dispatcher is an inline `function() ... end` callback
    (the call's parentheses don't close on the same line)
  - binds whose arguments happen to wrap onto a second line for
    formatting
Those are still parsed and shown for browsing/search, but keybey refuses
to edit or delete them -- a safe, generic rewrite of arbitrary Lua
would need a real Lua parser, not line surgery.

Every write (update_bind, delete_bind, add_bind) copies hyprland.lua to
a timestamped backup under ~/.local/state/keybey/backups/ first.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

HYPR_LUA = Path.home() / ".config" / "hypr" / "hyprland.lua"
BACKUP_DIR = Path.home() / ".local" / "state" / "keybey" / "backups"

LOCAL_STR_RE = re.compile(r'^local\s+([A-Za-z_]\w*)\s*=\s*"([^"]*)"\s*$')
BIND_START_RE = re.compile(r"^hl\.bind\(")
DESCRIPTION_RE = re.compile(r'description\s*=\s*"([^"]*)"')


@dataclass
class Bind:
    line_no: int  # 1-indexed start line
    end_line_no: int  # 1-indexed end line (== line_no when editable)
    mods: str  # raw Lua expression, e.g. 'mainMod .. " + Q"'
    dispatcher: str  # raw Lua expression, e.g. 'hl.dsp.window.close()'
    options: str  # raw Lua expression, e.g. '{ description = "..." }', or ""
    editable: bool
    raw: str  # exact source text for this bind's line(s), unmodified

    def description(self) -> str:
        # For multi-line binds `options` is never reliably extracted (it
        # may be on a different physical line than the parts we do parse),
        # so fall back to searching the whole raw source text.
        m = DESCRIPTION_RE.search(self.options) or DESCRIPTION_RE.search(self.raw)
        return m.group(1) if m else ""

    def resolved_mods(self, variables: dict[str, str]) -> str:
        return _resolve_concat(self.mods, variables)


def _resolve_concat(expr: str, variables: dict[str, str]) -> str:
    parts = _split_top_level(expr, "..")
    out = []
    for p in parts:
        p = p.strip()
        if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
            out.append(p[1:-1])
        elif p in variables:
            out.append(variables[p])
        else:
            out.append(p)
    return "".join(out)


def _split_top_level(s: str, sep: str) -> list[str]:
    """Split `s` on `sep` at paren/brace/bracket/quote depth 0."""
    parts = []
    depth = 0
    in_str = None
    i = 0
    start = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"'":
            in_str = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and s.startswith(sep, i):
            parts.append(s[start:i])
            i += len(sep)
            start = i
            continue
        i += 1
    parts.append(s[start:])
    return parts


def _find_matching_paren(s: str, open_idx: int) -> int | None:
    """Given the index of an opening '(' in `s`, return the index of its
    matching ')', or None if the call isn't closed within this string."""
    depth = 0
    in_str = None
    i = open_idx
    n = len(s)
    while i < n:
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"'":
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _consume_multiline(lines: list[str], start_idx: int) -> tuple[int, str]:
    """Best-effort: find where a multi-line hl.bind(...) statement ends by
    tracking paren depth across lines, for display purposes only -- these
    binds are never edited or deleted."""
    depth = 0
    started = False
    in_str = None
    collected = []
    i = start_idx
    n = len(lines)
    while i < n:
        line = lines[i]
        collected.append(line)
        j = 0
        m = len(line)
        while j < m:
            c = line[j]
            if in_str:
                if c == "\\":
                    j += 2
                    continue
                if c == in_str:
                    in_str = None
            elif c == "-" and line[j:j + 2] == "--":
                break  # rest of the line is a comment; stop scanning it
            elif c in "\"'":
                in_str = c
            elif c == "(":
                depth += 1
                started = True
            elif c == ")":
                depth -= 1
                if started and depth == 0:
                    return i + 1, "\n".join(collected)
            j += 1
        i += 1
    return n, "\n".join(collected)


def load(path: Path | None = None) -> tuple[list[Bind], dict[str, str]]:
    """Parse all binds and top-level string locals from `path` (default:
    the live HYPR_LUA, resolved dynamically -- never bind it as a stale
    default argument)."""
    path = HYPR_LUA if path is None else path
    lines = path.read_text().splitlines()

    variables: dict[str, str] = {}
    for line in lines:
        m = LOCAL_STR_RE.match(line.strip())
        if m:
            variables[m.group(1)] = m.group(2)

    binds: list[Bind] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("--") or not BIND_START_RE.match(stripped):
            i += 1
            continue
        indented = line[:1] in (" ", "\t")
        call_start = line.index("hl.bind(") + len("hl.bind")
        close_idx = _find_matching_paren(line, call_start)
        if close_idx is None:
            end_line_no, raw = _consume_multiline(lines, i)
            # The mods argument is always self-contained on this first line
            # even when the dispatcher/options span further lines (a
            # function body, or args wrapped for formatting) -- extract it
            # for search/display, even though the bind as a whole isn't
            # safely editable.
            first_line_args = _split_top_level(line[call_start + 1:], ",")
            mods = first_line_args[0].strip() if first_line_args else ""
            binds.append(Bind(
                line_no=i + 1, end_line_no=end_line_no,
                mods=mods, dispatcher="", options="",
                editable=False, raw=raw,
            ))
            i = end_line_no
            continue
        after = line[close_idx + 1:].strip()
        args = [a.strip() for a in _split_top_level(line[call_start + 1:close_idx], ",")]
        simple = (not indented) and (after == "" or after.startswith("--"))
        if simple and len(args) >= 2:
            binds.append(Bind(
                line_no=i + 1, end_line_no=i + 1,
                mods=args[0], dispatcher=args[1], options=args[2] if len(args) > 2 else "",
                editable=True, raw=line,
            ))
        else:
            binds.append(Bind(
                line_no=i + 1, end_line_no=i + 1,
                mods=args[0] if args else "", dispatcher=args[1] if len(args) > 1 else "",
                options=args[2] if len(args) > 2 else "",
                editable=False, raw=line,
            ))
        i += 1
    return binds, variables


def backup(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{path.name}.{stamp}"
    shutil.copy2(path, dest)
    return dest


def format_bind_line(mods: str, dispatcher: str, options: str) -> str:
    parts = [mods, dispatcher]
    if options:
        parts.append(options)
    return f"hl.bind({', '.join(parts)})"


def update_bind(old: Bind, mods: str, dispatcher: str, options: str) -> None:
    if not old.editable:
        raise ValueError("this bind spans multiple lines or is loop-generated; edit hyprland.lua directly")
    backup(HYPR_LUA)
    lines = HYPR_LUA.read_text().splitlines(keepends=True)
    idx = old.line_no - 1
    original = lines[idx]
    indent = original[: len(original) - len(original.lstrip())]
    newline = "\n" if original.endswith("\n") else ""
    lines[idx] = f"{indent}{format_bind_line(mods, dispatcher, options)}{newline}"
    HYPR_LUA.write_text("".join(lines))


def delete_bind(target: Bind) -> None:
    if not target.editable:
        raise ValueError("this bind spans multiple lines or is loop-generated; edit hyprland.lua directly")
    backup(HYPR_LUA)
    lines = HYPR_LUA.read_text().splitlines(keepends=True)
    idx = target.line_no - 1
    del lines[idx]
    HYPR_LUA.write_text("".join(lines))


def add_bind(mods: str, dispatcher: str, options: str) -> None:
    backup(HYPR_LUA)
    text = HYPR_LUA.read_text()
    sep = "" if not text or text.endswith("\n") else "\n"
    text += sep + format_bind_line(mods, dispatcher, options) + "\n"
    HYPR_LUA.write_text(text)


def reload_hyprland() -> tuple[bool, str]:
    try:
        result = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)
