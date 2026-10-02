# Hammunition Devices - tray for desktops other than Plasma
# Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Controls panel's services and radios (helper contract v1), with no Qt.

The helper answers ``hammunition-devctl services state`` and ``radio state``
with one JSON document each, without privilege. A user-scope service and a
radio are changed by running the helper directly; a system-scope service is
changed through ``pkexec``, with the same polkit action as park and wake.
Every sentence and every rule here is restated, word for word, in the Plasma
applet's ``controlslogic.js``; tests/test_controls_parity.py runs both over
the same helper documents and fails on any difference.

Nothing here runs a command. A name that came from the helper's output is
checked against the shape the helper itself accepts before it can reach an
argv, because the Plasma applet builds a shell string from it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

# The helper contract version this tray speaks (docs/contract.md in the
# helper's branch). A document that says less than this is "update
# hammunition-tray", never an error; one that says more is read as far as
# this tray understands it. Recorded here and in controlslogic.js, and
# nowhere else; test_controls_parity holds the two equal.
CONTRACT_FLOOR = 1

HEADING = "Controls"
GROUP_DEVICES = "Devices"
GROUP_SERVICES = "Services"
GROUP_RADIOS = "Radios"
# What a group says when the installed helper has no such verb, or speaks an
# older contract. One line, not an error on every poll.
UPDATE = "update hammunition-tray"
LOGIN_LABEL = "Start at login"
READING_SERVICES = "Reading services…"
READING_RADIOS = "Reading radios…"
NO_SERVICES = "No services are listed"
NO_RADIOS = "No radios are listed"
SERVICES_READ_ERROR = "Could not read the services list"
SERVICES_PARSE_ERROR = "Could not parse the services list"
RADIOS_READ_ERROR = "Could not read the radios list"
RADIOS_PARSE_ERROR = "Could not parse the radios list"
HELPER_RUN_ERROR = "Could not run the device helper"
NOT_INSTALLED = "%s: not installed"
SERVICE_FAILED = "%s: failed"
SERVICE_STARTING = "%s: starting"
RADIO_UNAVAILABLE = "not available: %s"
RADIO_UNAVAILABLE_NO_TOOL = "not available"

# Every fixed sentence, by name, so the parity test can compare them all.
STRINGS: dict[str, str] = {
    "heading": HEADING,
    "group_devices": GROUP_DEVICES,
    "group_services": GROUP_SERVICES,
    "group_radios": GROUP_RADIOS,
    "update": UPDATE,
    "login_label": LOGIN_LABEL,
    "reading_services": READING_SERVICES,
    "reading_radios": READING_RADIOS,
    "no_services": NO_SERVICES,
    "no_radios": NO_RADIOS,
    "services_read_error": SERVICES_READ_ERROR,
    "services_parse_error": SERVICES_PARSE_ERROR,
    "radios_read_error": RADIOS_READ_ERROR,
    "radios_parse_error": RADIOS_PARSE_ERROR,
    "helper_run_error": HELPER_RUN_ERROR,
}

SERVICE_VERBS = ("start", "stop", "enable", "disable")
# The only radios the helper switches (`radio on|off wwan|wifi|bluetooth`).
RADIO_NAMES = ("wwan", "wifi", "bluetooth")
RADIO_LABELS = {
    "wwan": "Mobile broadband (WWAN)",
    "wifi": "Wi-Fi",
    "bluetooth": "Bluetooth",
}

_ACTIVE = ("active", "inactive", "failed", "activating", "unknown")
_ENABLED = ("enabled", "disabled", "static", "not-found", "unknown")
_SCOPES = ("user", "system")
# The helper's own shape for a name from its allow-list files.
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class ControlsError(ValueError):
    """The helper's output is not the document it always prints."""


@dataclass(frozen=True)
class ServiceRow:
    name: str
    unit: str
    scope: str
    description: str
    active: str
    enabled: str
    root: bool


@dataclass(frozen=True)
class ServicesDoc:
    rows: tuple[ServiceRow, ...]
    linger_state: str | None = None


@dataclass(frozen=True)
class RadioRow:
    name: str
    present: bool
    enabled: bool
    method: str
    detail: str


# -- parsing ---------------------------------------------------------------


def _text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""


def _document(stdout: str, kind: str) -> dict[str, object]:
    try:
        doc = json.loads(stdout)
    except ValueError as exc:
        raise ControlsError(str(exc)) from exc
    if not isinstance(doc, dict) or doc.get("kind") != kind:
        raise ControlsError(f"not a {kind} document")
    return doc


def _version(doc: dict[str, object]) -> int:
    v = doc.get("version")
    if isinstance(v, bool) or not isinstance(v, int):
        return 0
    return v


def parse_services(stdout: str) -> ServicesDoc:
    doc = _document(stdout, "services")
    rows = doc.get("services")
    if not isinstance(rows, list):
        raise ControlsError("no services list")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise ControlsError("a row is not an object")
        name, scope = row.get("name"), row.get("scope")
        if not isinstance(name, str) or not name or scope not in _SCOPES:
            raise ControlsError("a row has no name or a scope this tray does not know")
        active, enabled = _text(row, "active"), _text(row, "enabled")
        out.append(
            ServiceRow(
                name=name,
                unit=_text(row, "unit"),
                scope=scope,
                description=_text(row, "description"),
                # A state a newer helper might add reads as unknown, which
                # nothing offers a switch for.
                active=active if active in _ACTIVE else "unknown",
                enabled=enabled if enabled in _ENABLED else "unknown",
                root=row.get("root") is True,
            )
        )
    linger = doc.get("linger")
    state = linger.get("state") if isinstance(linger, dict) else None
    return ServicesDoc(rows=tuple(out), linger_state=state if isinstance(state, str) else None)


def parse_radios(stdout: str) -> tuple[RadioRow, ...]:
    doc = _document(stdout, "radios")
    rows = doc.get("radios")
    if not isinstance(rows, list):
        raise ControlsError("no radios list")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise ControlsError("a row is not an object")
        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise ControlsError("a row has no name")
        out.append(
            RadioRow(
                name=name,
                present=row.get("present") is True,
                enabled=row.get("enabled") is True,
                method=_text(row, "method"),
                detail=_text(row, "detail"),
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class GroupOutcome:
    """What one poll means. ``doc`` is a ServicesDoc, a tuple of RadioRow,
    or None. ``keep`` is true when the last good rows should stay on screen
    (a failed read, as the device list does)."""

    doc: ServicesDoc | tuple[RadioRow, ...] | None = None
    unsupported: bool = False
    error: str = ""
    keep: bool = False


def _argparse_refusal(stderr: str) -> bool:
    low = stderr.lower()
    return "invalid choice" in low or "usage:" in low


def poll_outcome(
    kind: str, started: bool, crashed: bool, code: int, stdout: str, stderr: str
) -> GroupOutcome:
    if kind not in ("services", "radios"):
        raise ValueError(f"no such group {kind!r}")
    read_error = SERVICES_READ_ERROR if kind == "services" else RADIOS_READ_ERROR
    parse_error = SERVICES_PARSE_ERROR if kind == "services" else RADIOS_PARSE_ERROR
    # Not there at all: the device poll says so in its own words, and the
    # groups are hidden with it.
    if not started or (not crashed and code == 127):
        return GroupOutcome()
    # A helper without this verb: argparse refuses it, exit 2, "invalid
    # choice". Said once, as the group's one line; the poll keeps asking, so
    # updating the helper brings the group in without a new login. The
    # helper's own refusals are exit 2 too (contract: "error: ..."), and
    # those are errors, not a request to update.
    if not crashed and code == 2 and _argparse_refusal(stderr):
        return GroupOutcome(unsupported=True)
    if crashed or code != 0:
        return GroupOutcome(error=stderr.strip() or read_error, keep=True)
    try:
        if kind == "services":
            doc: ServicesDoc | tuple[RadioRow, ...] = parse_services(stdout.strip())
        else:
            doc = parse_radios(stdout.strip())
        # Parsed once already, so this cannot fail.
        version = _version(json.loads(stdout.strip()))
    except ControlsError:
        # A document with no version cannot say it speaks this contract, but
        # an unreadable one is a parse error before it is anything else.
        return GroupOutcome(error=parse_error, keep=True)
    if version < CONTRACT_FLOOR:
        return GroupOutcome(unsupported=True)
    return GroupOutcome(doc=doc)


def services_poll_argv(helper: str) -> tuple[str, list[str]]:
    # No pkexec: asking systemd for a unit's state needs no privilege.
    return helper, ["services", "state"]


def radios_poll_argv(helper: str) -> tuple[str, list[str]]:
    return helper, ["radio", "state"]


# -- the rules, and the words ------------------------------------------------


def _installed(row: ServiceRow) -> bool:
    return row.enabled != "not-found"


def run_checked(row: ServiceRow) -> bool:
    return row.active in ("active", "activating")


def run_verb(row: ServiceRow) -> str:
    return "stop" if run_checked(row) else "start"


def run_enabled(row: ServiceRow, acting: bool) -> bool:
    return not acting and _installed(row) and row.active != "unknown"


def login_checked(row: ServiceRow) -> bool:
    return row.enabled == "enabled"


def login_verb(row: ServiceRow) -> str:
    return "disable" if login_checked(row) else "enable"


def login_enabled(row: ServiceRow, acting: bool) -> bool:
    # `static` units have no [Install] section: there is nothing to enable.
    return not acting and row.enabled in ("enabled", "disabled")


def service_label(row: ServiceRow) -> str:
    return row.name


def service_detail(row: ServiceRow) -> str:
    if not _installed(row):
        return NOT_INSTALLED % row.description
    if row.active == "failed":
        return SERVICE_FAILED % row.description
    if row.active == "activating":
        return SERVICE_STARTING % row.description
    return row.description


def radio_label(row: RadioRow) -> str:
    return RADIO_LABELS.get(row.name, row.name)


def radio_detail(row: RadioRow) -> str:
    if not row.present:
        return RADIO_UNAVAILABLE % row.detail if row.detail else RADIO_UNAVAILABLE_NO_TOOL
    return row.detail


def radio_verb(row: RadioRow) -> str:
    return "off" if row.enabled else "on"


def radio_enabled(row: RadioRow, acting: bool) -> bool:
    return not acting and row.present and row.name in RADIO_NAMES


# -- argv, and only the argv the helper accepts -------------------------------


def service_argv(pkexec: str, helper: str, row: ServiceRow, verb: str) -> tuple[str, list[str]]:
    """User scope runs the helper directly; system scope goes through pkexec
    by its path. The name must have the helper's own shape."""
    if verb not in SERVICE_VERBS:
        raise ValueError(f"refusing service verb {verb!r}")
    if not _NAME.fullmatch(row.name):
        raise ValueError(f"refusing service name {row.name!r}: not an allow-list name")
    if row.scope == "user":
        return helper, ["services", verb, row.name]
    if row.scope == "system":
        return pkexec, [helper, "services", verb, row.name]
    raise ValueError(f"refusing service scope {row.scope!r}")


def uses_pkexec(row: ServiceRow) -> bool:
    return row.scope == "system"


def radio_argv(helper: str, row: RadioRow, on: bool) -> tuple[str, list[str]]:
    if row.name not in RADIO_NAMES:
        raise ValueError(f"refusing radio {row.name!r}")
    return helper, ["radio", "on" if on else "off", row.name]


def direct_error(started: bool, crashed: bool, code: int, stderr: str) -> str:
    """The one line for a verb run without pkexec that did not succeed, or
    "" when it did. The helper's first non-empty stderr line is its reason;
    a pkexec verb has its own rules (logic.apply_action)."""
    if not started or crashed:
        return HELPER_RUN_ERROR
    if code == 0:
        return ""
    for line in stderr.splitlines():
        if line.strip():
            return line.strip()
    return f"Action failed (exit {code})"


# -- what the operator just asked for, until a poll says otherwise -----------

Pending = tuple[tuple[str, "str | bool"], ...]

_EXPECTED = {
    "start": ("active", "active"),
    "stop": ("active", "inactive"),
    "enable": ("enabled", "enabled"),
    "disable": ("enabled", "disabled"),
}


def service_pending(verb: str, name: str) -> tuple[str, str]:
    field, value = _EXPECTED[verb]
    return f"service:{name}:{field}", value


def radio_pending(name: str, on: bool) -> tuple[str, bool]:
    return f"radio:{name}:enabled", on


def effective_services(rows: tuple[ServiceRow, ...], pending: Pending) -> tuple[ServiceRow, ...]:
    """The rows as the operator would see them if every pending request had
    worked. The real rows are never changed."""
    want = dict(pending)
    out = []
    for row in rows:
        active = want.get(f"service:{row.name}:active")
        enabled = want.get(f"service:{row.name}:enabled")
        out.append(
            replace(
                row,
                active=active if isinstance(active, str) else row.active,
                enabled=enabled if isinstance(enabled, str) else row.enabled,
            )
        )
    return tuple(out)


def effective_radios(rows: tuple[RadioRow, ...], pending: Pending) -> tuple[RadioRow, ...]:
    want = dict(pending)
    out = []
    for row in rows:
        on = want.get(f"radio:{row.name}:enabled")
        out.append(replace(row, enabled=on if isinstance(on, bool) else row.enabled))
    return tuple(out)
