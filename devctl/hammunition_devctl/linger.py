# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""Opt-in unattended operation: linger for the station operator.  D-073 §5a.

``station set --unattended`` keeps the operator's user services running with
nobody logged in — a remote HF station, a Pi at a served agency. It routes
``loginctl enable-linger`` through the D-056 helper (``hammunition-devctl
linger on``), which acts only on the calling account and records what it did in
``/etc/hammunition/linger.yaml`` so the reversal knows whether linger was ours
to turn off.

Pure here; the helper reads the current state and runs the command. The one
root write is the record, through the D-058 atomic writer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from hammunition_devctl.datafiles import read_text_as_root
from hammunition_devctl.rootfiles import atomic_write

__all__ = [
    "LINGER_RECORD",
    "LingerPlan",
    "LingerRecord",
    "disable_command",
    "enable_command",
    "plan_linger",
    "read_record",
    "write_record",
]

LINGER_RECORD = Path("/etc/hammunition/linger.yaml")

LOGINCTL = "/usr/bin/loginctl"
"""By absolute path: this command runs as root, and nothing found through a
PATH is ever started with root's authority."""


@dataclass(frozen=True)
class LingerRecord:
    """What Hammunition did to linger, so the reversal knows what is its to undo."""

    uid: int
    enabled_by_us: bool
    """True when Hammunition turned linger on. Linger that was already on is not
    ours and is never turned off (D-073 §5a)."""


@dataclass(frozen=True)
class LingerPlan:
    """What ``linger on|off`` will do, decided from the current state."""

    command: tuple[str, ...] | None
    """The ``loginctl`` command to run, or None when there is nothing to do."""
    record: LingerRecord | None
    """The record to write, or None to leave/remove it."""
    remove_record: bool
    note: str


def enable_command(username: str) -> tuple[str, ...]:
    return (LOGINCTL, "enable-linger", username)


def disable_command(username: str) -> tuple[str, ...]:
    return (LOGINCTL, "disable-linger", username)


def plan_linger(
    *,
    on: bool,
    uid: int,
    username: str,
    already_on: bool,
    existing: LingerRecord | None,
) -> LingerPlan:
    """Decide what ``linger on`` or ``linger off`` should do.

    ``already_on`` is logind's current linger state for the account;
    ``existing`` is our record of whether we turned it on.
    """
    ours_already = existing is not None and existing.uid == uid and existing.enabled_by_us
    if on:
        if already_on:
            # Already lingering. If Hammunition set it (our record, this uid),
            # keep that — re-running --unattended must not flip it to not-ours,
            # or --no-unattended would then refuse to turn it off (review I3).
            return LingerPlan(
                command=None,
                record=LingerRecord(uid=uid, enabled_by_us=ours_already),
                remove_record=False,
                note=(
                    "linger is already on and was turned on by Hammunition"
                    if ours_already
                    else "linger is already on for this account; left as it was (not ours to undo)"
                ),
            )
        return LingerPlan(
            command=enable_command(username),
            record=LingerRecord(uid=uid, enabled_by_us=True),
            remove_record=False,
            note="linger enabled: user services will keep running after you log out",
        )
    # off: disable only the linger this very uid's record says Hammunition set.
    if ours_already:
        return LingerPlan(
            command=disable_command(username),
            record=None,
            remove_record=True,
            note="linger disabled: it was turned on by Hammunition",
        )
    return LingerPlan(
        command=None,
        record=None,
        remove_record=False,
        note="linger left on: Hammunition did not turn it on for this account, not ours to undo",
    )


def read_record(path: Path | None = None, notes: list[str] | None = None) -> LingerRecord | None:
    """The record, or None when absent -- or unusable, which is said in ``notes``.

    A record that cannot be read must never stop a reading verb from printing
    its one JSON document, so every way it can be wrong is "absent, with a
    note". Under root it is read only when it is the root-owned file the
    helper wrote (the same rule as the data files).
    """
    path = path or LINGER_RECORD
    sink = notes if notes is not None else []
    if os.geteuid() == 0:
        text = read_text_as_root(path, sink)
        if text is None:
            return None
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError) as exc:
            sink.append(f"{path} is unreadable: {exc}")
            return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        sink.append(f"{path} is not valid YAML")
        return None
    if not isinstance(data, dict) or "uid" not in data:
        return None
    try:
        return LingerRecord(uid=int(data["uid"]), enabled_by_us=bool(data.get("enabled_by_us", False)))
    except (TypeError, ValueError):
        sink.append(f"{path} has a uid that is not a number")
        return None


def write_record(record: LingerRecord, path: Path | None = None) -> None:
    path = path or LINGER_RECORD
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    body = (
        "# Written by Hammunition (D-073 §5a). Whether linger for the station\n"
        "# operator was turned on by Hammunition, so the reversal knows.\n"
        + yaml.safe_dump({"uid": record.uid, "enabled_by_us": record.enabled_by_us})
    )
    atomic_write(path, body, mode=0o644)
