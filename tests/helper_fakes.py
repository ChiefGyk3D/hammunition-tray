"""Stand-ins the helper's tests share: a runner keyed by argv, and data files.

Nothing here starts a process. A command the fake was not told about is a
failing assertion, so a verb that quietly runs something extra is a red test.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from hammunition_devctl.run import Result


class FakeRunner:
    """Answers from a dict keyed by the argv tuple, and records every argv."""

    def __init__(self, answers: dict[tuple[str, ...], Result | list[Result]] | None = None) -> None:
        self.answers: dict[tuple[str, ...], Result | list[Result]] = dict(answers or {})
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> Result:
        key = tuple(argv)
        self.calls.append(key)
        if key not in self.answers:
            raise AssertionError(f"unexpected command {list(key)!r}")
        answer = self.answers[key]
        if isinstance(answer, list):
            # successive answers, the last one repeating: before and after a change
            return answer.pop(0) if len(answer) > 1 else answer[0]
        return answer


def show(unit: str, *, load="loaded", active="active", enabled="enabled", user=False):
    """The argv and answer of the `systemctl show` read for ``unit``."""
    argv = (
        "systemctl",
        *(("--user",) if user else ()),
        "show",
        "--no-pager",
        "--property=LoadState,ActiveState,UnitFileState",
        unit,
    )
    body = f"LoadState={load}\nActiveState={active}\nUnitFileState={enabled}\n"
    if load == "not-found":
        body = "LoadState=not-found\nActiveState=inactive\nUnitFileState=\n"
    return argv, Result(0, body)


def write_services(path: Path, scope: str, rows: list[tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["version: 1", "services:"]
    for name, unit, description in rows:
        lines += [
            f"  - name: {name}",
            f"    unit: {unit}",
            f"    scope: {scope}",
            f"    description: {description}",
        ]
    path.write_text("\n".join(lines) + "\n")
