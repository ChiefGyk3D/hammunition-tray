# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading the three data files the helper takes its allow-lists from.

The helper never takes a unit, a device or a path from its argv; it takes a
*name* and looks it up here. So what may be read, and by whom, is the whole of
the trust question (docs/contract.md, "The three data files").

Two rules, both enforced here and nowhere else:

- A file that is absent is an empty list, not an error.
- A file that cannot be parsed is a ``note`` and an empty list, never half
  read, and a process that is root reads the two ``/etc`` files only when
  each is a regular file owned by root that no group or other can write.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "DEVICES_FILE",
    "SERVICES_FILE",
    "load_yaml",
    "user_services_file",
]

DEVICES_FILE = Path("/etc/hammunition/devctl-devices.yaml")
SERVICES_FILE = Path("/etc/hammunition/devctl-services.yaml")


def user_services_file(environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """``$XDG_CONFIG_HOME/hammunition/devctl-services.yaml``, else under ``~/.config``."""
    env = os.environ if environ is None else environ
    base = env.get("XDG_CONFIG_HOME")
    root = Path(base) if base and os.path.isabs(base) else (home or Path.home()) / ".config"
    return root / "hammunition" / "devctl-services.yaml"


def _untrusted_for_root(path: Path) -> str | None:
    """Why root must not read ``path``, or None when it may."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"cannot be examined ({exc})"
    if not stat.S_ISREG(info.st_mode):
        return "is not a regular file"
    if info.st_uid != 0:
        return "is not owned by root"
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return "is writable by group or other"
    return None


def load_yaml(path: Path, notes: list[str]) -> dict[str, Any] | None:
    """The mapping in ``path``; ``None`` when absent, untrusted or unparseable.

    Every reason it is ``None`` for a file that exists is appended to
    ``notes``, for the caller to print on stderr.
    """
    if os.geteuid() == 0:
        reason = _untrusted_for_root(path)
        if reason is not None:
            notes.append(f"{path} {reason}; not reading it as root")
            return None
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        notes.append(f"{path} is unreadable: {exc}")
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        notes.append(f"{path} is not valid YAML: {str(exc).splitlines()[0] if str(exc) else exc}")
        return None
    if not isinstance(data, dict):
        notes.append(f"{path} does not hold a mapping")
        return None
    if data.get("version") != 1:
        notes.append(f"{path} has version {data.get('version')!r}, not 1")
        return None
    return data
