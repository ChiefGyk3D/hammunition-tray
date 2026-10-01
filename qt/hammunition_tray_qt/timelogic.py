# Hammunition Devices - tray for desktops other than Plasma
# Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Time section's rules (Hammunition D-058), with no Qt in it.

The engine's helper answers ``hammunition-devctl time state`` with one JSON
object, without privilege, and sets the mode only through ``pkexec
hammunition-devctl time mode MODE``. Every sentence and every rule here is
restated, word for word, in the Plasma applet's ``timelogic.js``;
tests/test_time_parity.py runs both over the same helper outputs and fails on
any difference, so the two front ends cannot drift apart.

The engine's own wording of the same facts is ``hammunition time``. The tray
words them itself, shorter, and points there for the long form.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

# The engine's four modes, in its order (hammunition.gpstime.mode.MODES). The
# only strings that may follow ``time mode`` to the privileged helper.
MODES: tuple[str, ...] = ("auto", "prefer-gps", "ntp-only", "gps-only")

# The engine release that added ``time state``. An older helper refuses the
# verb with argparse's exit 2.
ENGINE_FLOOR = "0.18.0"

MODE_LABELS = {
    "auto": "Automatic (the default)",
    "prefer-gps": "Prefer the GPS",
    "ntp-only": "Network only",
    "gps-only": "GPS only",
}

UNSUPPORTED = f"Update Hammunition to {ENGINE_FLOOR} or later to see and set the time source here."
READING = "Reading time state…"
NO_NTPSEC = "GPS time unavailable: ntpsec is not this machine's time daemon"
PARKED = "GPS time off: the receiver is parked"
NO_RECEIVER = "No GPS receiver is attached, so gps-only has nothing to follow"
# Deliberately not "run hammunition hardware apply": on a machine without
# gpsd, apply declines the grants, so `grants` stays false however often it
# is run. `hammunition time` has the whole story.
NO_GRANTS = "ntpd cannot read the GPS's time yet; `hammunition time` says what it needs"
DHCP = (
    "ntpd was started on a DHCP-supplied configuration, so the mode may not "
    "apply; `hammunition time` says how to change that"
)
NO_RTC = "No hardware clock: the time is lost at power-off with no network or GPS"
READ_ERROR = "Could not read the time state"
PARSE_ERROR = "Could not parse the time state"


class TimeStateError(ValueError):
    """The helper's output is not the JSON object it always prints."""


@dataclass(frozen=True)
class TimeState:
    """``hammunition-devctl time state``, as the engine's ``JSON_KEYS``.

    ``daemon`` is None both where the time daemon is not ntpsec and where
    ntpsec was removed but its conffile left behind; either way nothing can
    take time from a GPS."""

    mode: str
    mode_set: bool = False
    daemon: str | None = None
    gps: str = "absent"
    following: str = "unknown"
    offset_ms: float | None = None
    last_sync: str | None = None
    last_source: str | None = None
    holdover_seconds: int | None = None
    rtc: bool = True
    grants: bool = False
    dhcp_config: bool = False
    problems: tuple[str, ...] = ()


def _opt_str(row: dict[str, object], key: str) -> str | None:
    value = row.get(key)
    return value if isinstance(value, str) else None


def _opt_num(row: dict[str, object], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_time_state(stdout: str) -> TimeState:
    try:
        row = json.loads(stdout)
    except ValueError as exc:
        raise TimeStateError(str(exc)) from exc
    if not isinstance(row, dict) or not isinstance(row.get("mode"), str):
        raise TimeStateError("not a time state object")
    problems = row.get("problems")
    holdover = _opt_num(row, "holdover_seconds")
    return TimeState(
        mode=row["mode"],
        mode_set=row.get("mode_set") is True,
        daemon=_opt_str(row, "daemon"),
        gps=_opt_str(row, "gps") or "absent",
        following=_opt_str(row, "following") or "unknown",
        offset_ms=_opt_num(row, "offset_ms"),
        last_sync=_opt_str(row, "last_sync"),
        last_source=_opt_str(row, "last_source"),
        holdover_seconds=None if holdover is None else int(holdover),
        # Absent means "not reported", which is not "no RTC": only an
        # explicit false earns the note.
        rtc=row.get("rtc") is not False,
        grants=row.get("grants") is True,
        dhcp_config=row.get("dhcp_config") is True,
        problems=tuple(p for p in problems if isinstance(p, str))
        if isinstance(problems, list)
        else (),
    )


@dataclass(frozen=True)
class PollOutcome:
    """What one ``time state`` poll means. ``keep`` is true when the last good
    state should stay on screen (a failed read, as the device list does)."""

    state: TimeState | None = None
    unsupported: bool = False
    error: str = ""
    keep: bool = False


def poll_outcome(started: bool, crashed: bool, code: int, stdout: str, stderr: str) -> PollOutcome:
    # Not there at all: the device poll says so in its own words, and the
    # section is hidden with it.
    if not started or (not crashed and code == 127):
        return PollOutcome()
    # An engine older than D-058: argparse refuses the verb, exit 2. Said
    # once, as the section's one line, never as an error on every poll. The
    # new helper's `time state` never exits 2 when run without root, so this
    # is unambiguous; and the poll keeps running, so updating the engine
    # brings the section in without a new login.
    if not crashed and code == 2:
        return PollOutcome(unsupported=True)
    if crashed or code != 0:
        return PollOutcome(error=stderr.strip() or READ_ERROR, keep=True)
    try:
        return PollOutcome(state=parse_time_state(stdout.strip()))
    except TimeStateError:
        return PollOutcome(error=PARSE_ERROR, keep=True)


def time_poll_argv(helper: str) -> tuple[str, list[str]]:
    # No pkexec: ntpq answers any local user, and so does the helper's read.
    return helper, ["time", "state"]


def time_mode_argv(pkexec: str, helper: str, mode: str) -> tuple[str, list[str]]:
    if mode not in MODES:
        raise ValueError(f"refusing time mode {mode!r}")
    return pkexec, [helper, "time", "mode", mode]


def greyed(t: TimeState | None) -> bool:
    """The GPS cannot feed the clock: no ntpsec, or the receiver is parked
    while the mode would use it."""
    if t is None:
        return False
    return t.daemon != "ntpsec" or (t.gps == "parked" and t.mode != "ntp-only")


def can_choose(t: TimeState | None, unsupported: bool) -> bool:
    # `time mode` refuses by name where ntpsec is not the daemon.
    return not unsupported and t is not None and t.daemon == "ntpsec"


def mode_label(mode: str) -> str:
    return MODE_LABELS.get(mode, mode)


def duration(seconds: int) -> str:
    """The engine's format_duration, so both say the same span."""
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def signed_ms(ms: float) -> str:
    """``+1.2``. Rounded half away from zero by hand, because Python's format
    rounds a tie to even and JavaScript's toFixed does not, and ntpq prints
    exact ties such as 0.250."""
    tenths = math.floor(abs(ms) * 10 + 0.5)
    sign = "-" if ms < 0 and tenths != 0 else "+"
    return f"{sign}{tenths // 10}.{tenths % 10}"


def _follows(what: str, ms: float | None) -> str:
    if ms is None:
        return f"The clock follows {what}"
    return f"The clock follows {what} (offset {signed_ms(ms)} ms)"


_HHMM = re.compile(r"T(\d\d:\d\d)")


def headline(t: TimeState | None, unsupported: bool) -> str:
    if unsupported:
        return UNSUPPORTED
    if t is None:
        return READING
    if t.daemon != "ntpsec":
        return NO_NTPSEC
    if t.following == "gps":
        return _follows("the GPS", t.offset_ms)
    if t.following == "network":
        return _follows("the network", t.offset_ms)
    if t.following == "none":
        found = _HHMM.search(t.last_sync or "")
        if found:
            # The helper prints UTC (isoformat with +00:00); said as UTC, as
            # `hammunition time` does, rather than guessed into local time.
            return (
                f"Holdover since {found.group(1)} UTC "
                f"({duration(t.holdover_seconds or 0)}): nothing is setting the clock"
            )
        return "Nothing is setting the clock, and ntpd has not synchronised since it started"
    return "Time source unknown"


def notes(t: TimeState | None) -> list[str]:
    if t is None:
        return []
    if t.daemon != "ntpsec":
        return list(t.problems)
    out = []
    if t.gps == "parked" and t.mode != "ntp-only":
        out.append(PARKED)
    elif t.gps == "absent" and t.mode == "gps-only":
        out.append(NO_RECEIVER)
    if t.gps == "awake" and t.mode != "ntp-only" and not t.grants:
        out.append(NO_GRANTS)
    if t.dhcp_config:
        out.append(DHCP)
    out += list(t.problems)
    return out


def rtc_note(t: TimeState | None) -> str:
    return NO_RTC if t is not None and not t.rtc else ""
