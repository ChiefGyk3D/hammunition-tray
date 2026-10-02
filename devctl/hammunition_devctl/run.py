# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one place the helper starts a process, so a test can replace it.

``shell`` is never involved: an argv is a tuple of words, and the verbs that
build one (``services``, ``radio``) take every word from a fixed table or an
allow-list row, never from the caller's argv. A test installs a fake keyed by
the argv with :func:`set_runner`, so no test ever runs the real ``systemctl``,
``nmcli`` or ``bluetoothctl``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

__all__ = ["Result", "Runner", "run", "set_runner"]

TIMEOUT_S = 20


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str]], Result]


def _real(argv: Sequence[str]) -> Result:
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    try:
        done = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            timeout=TIMEOUT_S,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return Result(127, "", f"{argv[0]}: command not found")
    except subprocess.TimeoutExpired:
        return Result(124, "", f"{argv[0]}: no answer in {TIMEOUT_S} s")
    except OSError as exc:
        return Result(126, "", f"{argv[0]}: {exc}")
    return Result(done.returncode, done.stdout, done.stderr)


_runner: Runner = _real


def set_runner(runner: Runner | None) -> None:
    """Install a replacement (a test's fake), or ``None`` for the real one."""
    global _runner
    _runner = runner or _real


def run(argv: Sequence[str]) -> Result:
    return _runner(tuple(argv))
