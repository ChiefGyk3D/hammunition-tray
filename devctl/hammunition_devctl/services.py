# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""Services the helper may report and control.  docs/contract.md.

The allow-list is two data files (system scope under ``/etc/hammunition``,
user scope under the caller's config directory). The caller names a service;
the unit, the scope and the ``systemctl`` argv all come from the row, never
from the command line, and nothing here runs a word that arrived as input.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hammunition_devctl import datafiles
from hammunition_devctl.run import run

__all__ = [
    "ACTIVE",
    "ENABLED",
    "VERBS",
    "LOGINCTL",
    "SYSTEMCTL",
    "Service",
    "ServiceError",
    "control",
    "load_services",
    "read_status",
    "state_document",
]

VERBS = ("start", "stop", "enable", "disable")
ACTIVE = ("active", "inactive", "failed", "activating", "unknown")
ENABLED = ("enabled", "disabled", "static", "not-found", "unknown")

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.@-]{0,127}\.(service|socket|timer|path)")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

SYSTEMCTL = "/usr/bin/systemctl"
LOGINCTL = "/usr/bin/loginctl"
"""Absolute, because the privileged ones run as root: nothing found through a
PATH is ever started with root's authority."""

_STATIC = ("static", "indirect", "generated", "transient", "alias")


class ServiceError(Exception):
    """A service verb that cannot be planned: the caller's mistake, exit 2."""


@dataclass(frozen=True)
class Service:
    name: str
    unit: str
    scope: str
    description: str

    @property
    def root(self) -> bool:
        return self.scope == "system"


def _rows(path: Path, scope: str, notes: list[str]) -> list[Service]:
    data = datafiles.load_yaml(path, notes)
    if data is None:
        return []
    raw = data.get("services")
    if raw is not None and not isinstance(raw, list):
        notes.append(f"{path}: services is not a list; treated as empty")
        return []
    found: list[Service] = []
    for row in raw or []:
        if not isinstance(row, dict):
            notes.append(f"{path}: a services row is not a mapping; dropped")
            continue
        name, unit = row.get("name"), row.get("unit")
        description = row.get("description", "")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            notes.append(f"{path}: a service has the name {name!r}; dropped")
        elif not isinstance(unit, str) or not _UNIT.fullmatch(unit):
            notes.append(f"{path}: service {name!r} has the unit {unit!r}; dropped")
        elif row.get("scope") != scope:
            notes.append(
                f"{path}: service {name!r} says scope {row.get('scope')!r}, "
                f"and this file holds {scope!r} services; dropped"
            )
        elif (
            not isinstance(description, str)
            or len(description) > 200
            or _CONTROL_CHARS.search(description)
        ):
            notes.append(f"{path}: service {name!r} has an unusable description; dropped")
        else:
            found.append(Service(name, unit, scope, description))
    return found


def load_services(notes: list[str], *, user_file: Path | None = None) -> list[Service]:
    """System rows in file order, then the caller's user rows.

    A root process never reads the user file: it is writable by the account
    that is asking, and what root controls must not be that account's to
    choose. A user row whose name a system row already has is dropped.
    """
    rows: list[Service] = []
    taken: set[str] = set()
    for row in _rows(datafiles.SERVICES_FILE, "system", notes):
        if row.name in taken:
            notes.append(f"service {row.name!r} appears twice in the system file; the first is kept")
            continue
        taken.add(row.name)
        rows.append(row)
    if os.geteuid() == 0:
        return rows
    for row in _rows(user_file or datafiles.user_services_file(), "user", notes):
        if row.name in taken:
            notes.append(
                f"user service {row.name!r} shares a name with a service already listed; dropped"
            )
            continue
        taken.add(row.name)
        rows.append(row)
    return rows


def _systemctl(service: Service, *words: str) -> tuple[str, ...]:
    return (SYSTEMCTL, *(("--user",) if service.scope == "user" else ()), *words)


def read_status(service: Service) -> tuple[str, str, str]:
    """``(load, active, enabled)`` from systemd, each folded into the contract's words."""
    result = run(
        _systemctl(
            service,
            "show",
            "--no-pager",
            "--property=LoadState,ActiveState,UnitFileState",
            service.unit,
        )
    )
    props: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value.strip()
    load = props.get("LoadState", "")
    if not result.ok or not load:
        return "unknown", "unknown", "unknown"
    if load == "not-found":
        return "not-found", "inactive", "not-found"
    active = props.get("ActiveState", "")
    state = props.get("UnitFileState", "")
    folded_active = active if active in ACTIVE else "unknown"
    if state in ("enabled", "enabled-runtime"):
        folded = "enabled"
    elif state == "disabled":
        folded = "disabled"
    elif state in _STATIC:
        folded = "static"
    else:
        folded = "unknown"
    return load, folded_active, folded


def linger_document(uid: int, record_ours: bool) -> dict[str, Any]:
    """``{"state": on|off|unknown, "ours": bool}`` for the calling account."""
    import pwd

    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError:
        return {"state": "unknown", "ours": record_ours}
    result = run((LOGINCTL, "show-user", username, "--property=Linger", "--value"))
    answer = result.stdout.strip().lower()
    if not result.ok:
        state = "unknown"
    else:
        state = "on" if answer in ("yes", "1", "true") else "off" if answer in ("no", "0", "false") else "unknown"
    return {"state": state, "ours": record_ours}


def state_document(services: list[Service], linger: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for s in services:
        _, active, enabled = read_status(s)
        rows.append(
            {
                "name": s.name,
                "unit": s.unit,
                "scope": s.scope,
                "description": s.description,
                "active": active,
                "enabled": enabled,
                "root": s.root,
            }
        )
    return {"kind": "services", "version": 1, "services": rows, "linger": linger}


def _holds(verb: str, active: str, enabled: str) -> bool:
    if verb == "start":
        return active in ("active", "activating")
    if verb == "stop":
        return active != "active" and active != "activating"
    if verb == "enable":
        return enabled == "enabled"
    return enabled != "enabled"


def control(verb: str, name: str, services: list[Service]) -> list[str]:
    """Perform ``verb`` on the service called ``name``.

    Returns the problems (empty is success). Raises :class:`ServiceError`
    for what is refused before anything runs: a name in neither file, a
    scope this process cannot act in, a unit that is not installed.
    """
    if verb not in VERBS:  # argparse already restricts this; the guard is for callers
        raise ServiceError(f"{verb!r} is not one of {', '.join(VERBS)}")
    matches = [s for s in services if s.name == name]
    if not matches:
        raise ServiceError(f"{name!r} is not a service Hammunition controls")
    service = matches[0]
    is_root = os.geteuid() == 0
    if service.scope == "system" and not is_root:
        raise ServiceError(
            f"{name!r} is a system service; changing it needs root (run it through pkexec)"
        )
    if service.scope == "user" and is_root:
        raise ServiceError(
            f"{name!r} is a user service; it is never driven from a root process"
        )
    load, _, _ = read_status(service)
    if load == "not-found":
        raise ServiceError(f"{name!r} ({service.unit}) is not installed")
    result = run(_systemctl(service, verb, service.unit))
    if not result.ok:
        return [f"systemctl {verb} {service.unit} failed: {result.stderr.strip() or f'exit {result.returncode}'}"]
    _, active, enabled = read_status(service)
    if not _holds(verb, active, enabled):
        return [
            f"systemctl {verb} {service.unit} reported success, and the unit reads "
            f"{active}/{enabled} afterwards"
        ]
    return []
