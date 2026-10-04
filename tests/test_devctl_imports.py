# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every module of the helper imports on its own, in a fresh interpreter.

The helper's modules once imported each other in a ring (bus -> devices ->
power -> bus, and devices -> devctl -> devices), which works only for the
import order the console script happens to use. CodeQL's
``py/unsafe-cyclic-import`` describes exactly that: another entry point, a
test, or a reordered import line turns it into an ``ImportError`` in a program
that runs as root. Each module is imported first, alone, in a new process, so
the order-dependence cannot come back.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parent.parent / "devctl"
PKG_DIR = PKG_ROOT / "hammunition_devctl"
# __main__ runs the CLI on import, so it is checked by the graph test only.
MODULES = sorted(p.stem for p in PKG_DIR.glob("*.py") if p.stem not in {"__init__", "__main__"})


def test_the_module_list_is_not_empty() -> None:
    assert "devctl" in MODULES and "power" in MODULES and "bus" in MODULES


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", f"import hammunition_devctl.{module}"],
        env={"PYTHONPATH": str(PKG_ROOT), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def _imported_siblings(module: str) -> set[str]:
    """The sibling modules ``module`` imports at any depth, read from source."""
    import ast

    tree = ast.parse((PKG_DIR / f"{module}.py").read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "hammunition_devctl":
                found.update(a.name for a in node.names if a.name in MODULES)
            elif node.module.startswith("hammunition_devctl."):
                found.add(node.module.split(".")[1])
    return found & set(MODULES)


def test_the_module_graph_has_no_cycle() -> None:
    """Counts every import statement, including those under TYPE_CHECKING and
    inside functions: a cycle hidden at call time is still a cycle."""
    graph = {m: _imported_siblings(m) for m in MODULES}
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        if state.get(node) == 1:
            raise AssertionError("import cycle: " + " -> ".join([*path, node]))
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in sorted(graph[node]):
            visit(nxt, [*path, node])
        state[node] = 2

    for m in MODULES:
        visit(m, [])
