"""XDG base-directory lookups.

Per the spec, a relative value in one of these variables is invalid and
must be ignored in favour of the default, so each lookup checks for an
absolute path before trusting the environment.
"""

from __future__ import annotations

import os
from pathlib import Path


def _base(var: str, default: str) -> Path:
    value = os.environ.get(var)
    if value:
        path = Path(value)
        if path.is_absolute():
            return path
    return Path.home() / default


def config_home() -> Path:
    return _base("XDG_CONFIG_HOME", ".config")


def data_home() -> Path:
    return _base("XDG_DATA_HOME", ".local/share")


def state_home() -> Path:
    return _base("XDG_STATE_HOME", ".local/state")
