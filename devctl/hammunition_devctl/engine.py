# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""Whether this process may import the Hammunition engine.  D-056.

A leaf of the package: ``devctl`` (the verbs) and ``devices`` (the fallback
that builds the device list from the engine's catalog) both ask the same
question, and neither may import the other to do it.
"""

from __future__ import annotations

import os
import sys

from hammunition_devctl.polkit import (
    WritabilityRisk,
    describe_refusal,
    writable_including_symlink_target,
)

__all__ = ["engine_importable_as_root"]


def _engine_dir() -> str | None:
    """Where the engine's ``hammunition`` package is on this interpreter's path,
    found without importing it, or None when there is none."""
    import importlib.util

    try:
        spec = importlib.util.find_spec("hammunition")
    except (ImportError, ValueError):
        return None
    locations = list(spec.submodule_search_locations or []) if spec else []
    return locations[0] if locations else None


def engine_importable_as_root() -> bool:
    """Whether this process may import the engine at all.

    Importing runs the engine's code with this process's privileges, so as root
    the tree it lives in gets the same D-056 check the helper's own package
    gets: refused when *any* local account can write it, a warning when one
    specific non-root account owns it (the documented install, a venv under
    ``$HOME``). Unprivileged, there is nothing to protect and it is always
    allowed.
    """
    if os.geteuid() != 0:
        return True
    where = _engine_dir()
    if where is None:
        return True  # nothing to import; the import itself will say so
    finding = writable_including_symlink_target(where)
    if finding is None:
        return True
    if finding.risk is WritabilityRisk.GROUP_OR_OTHER_WRITABLE:
        print(
            f"note: not importing the Hammunition engine as root: {describe_refusal([finding])}",
            file=sys.stderr,
        )
        return False
    print(
        f"warning: the Hammunition engine at {where} is owned by a non-root account "
        f"({finding.path}), and this process is importing it as root.",
        file=sys.stderr,
    )
    return True
