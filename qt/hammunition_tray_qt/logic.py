# Hammunition Devices - tray for desktops other than Plasma
# Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later
"""Everything the tray decides, with no Qt in it.

This is the Plasma applet's main.qml restated as pure functions over an
immutable state, so it can be tested without a display. The tray is a second
client of the same helper; nothing about consent, privilege or what counts
as an error may differ between the two, and where a rule here looks odd the
matching comment in main.qml says why.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

# The wrapper `hammunition hardware apply` installs. The polkit action
# authorises this exact path, so it is a constant rather than something
# discovered: a path we went looking for would be a second value crossing
# the privilege boundary.
HELPER = "/usr/local/libexec/hammunition-devctl"
# By absolute path, like the helper: a pkexec found through PATH (say
# ~/.local/bin/pkexec) could fake the password dialog. Debian 13 and
# Ubuntu 24.04 both install it here.
PKEXEC = "/usr/bin/pkexec"
POLL_MS = 5000

ICON_AWAKE = "hammunition-tray-qt-awake"
ICON_PARKED = "hammunition-tray-qt-parked"
ICON_MISSING = "dialog-warning"

TITLE = "Hammunition Devices"
FOOTER = "Off stays off across reboots until you turn it back on."

# The helper's own shapes (hammunition/hardware/power.py): a catalog name,
# and a USB bus address such as 1-4 or 3-1.2.4. Anything else is refused
# before it reaches pkexec, bounded in length so a pathological string never
# gets as far as an argv. A PCI address is not accepted here because the
# helper refuses every method but usb_deauthorize today; widen both together.
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_ADDRESS = re.compile(r"[0-9]{1,3}-[0-9]{1,3}(\.[0-9]{1,3}){0,7}")
_VERBS = ("park", "wake")


class StateError(ValueError):
    """The helper's output is not the JSON array it always prints."""


@dataclass(frozen=True)
class Device:
    name: str
    address: str
    summary: str
    parked: bool
    kept: bool
    attached: bool

    @property
    def label(self) -> str:
        return self.summary or self.name


@dataclass(frozen=True)
class ProcResult:
    """What a finished process told us. ``started`` is false when the
    program could not be run at all, which QProcess reports instead of an
    exit code."""

    started: bool
    crashed: bool = False
    code: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class TrayState:
    # None until the first poll returns, so "no devices" and "not polled yet"
    # are distinguishable.
    devices: tuple[Device, ...] | None = None
    helper_missing: bool = False
    # The poll's own error, replaced by every poll.
    last_error: str = ""
    # The last park or wake's error. Kept apart because every action is
    # followed at once by a poll, and a good poll clears last_error: in
    # main.qml, which has one lastError, an action's error vanishes within
    # a moment of appearing. Cleared when the next action starts.
    action_error: str = ""
    acting: bool = False
    kept_notice_sent: bool = False


@dataclass(frozen=True)
class MenuEntry:
    kind: str  # info | toggle | forget | error | footer | separator | quit
    text: str = ""
    enabled: bool = False
    checked: bool | None = None
    verb: str | None = None
    device: Device | None = None


def parse_state(stdout: str) -> tuple[Device, ...]:
    try:
        rows = json.loads(stdout)
    except ValueError as exc:
        raise StateError(str(exc)) from exc
    if not isinstance(rows, list):
        raise StateError("not a JSON array")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise StateError("a row is not an object")
        name, address = row.get("name"), row.get("address")
        if not isinstance(name, str) or not isinstance(address, str):
            raise StateError("a row has no name or address")
        summary = row.get("summary")
        out.append(
            Device(
                name=name,
                address=address,
                summary=summary if isinstance(summary, str) else "",
                parked=bool(row.get("parked")),
                kept=bool(row.get("kept")),
                # main.qml tests `attached !== false`.
                attached=row.get("attached") is not False,
            )
        )
    return tuple(out)


def target(device: Device) -> str:
    """NAME@ADDRESS, always. Two receivers of one class share a catalog name
    and differ only by address, and the helper refuses a bare name then."""
    if not _NAME.fullmatch(device.name):
        raise ValueError(f"refusing device name {device.name!r}: not a catalog name")
    if not _ADDRESS.fullmatch(device.address):
        raise ValueError(f"refusing address {device.address!r}: not a USB bus address")
    return f"{device.name}@{device.address}"


def action_argv(verb: str, device: Device) -> tuple[str, list[str]]:
    if verb not in _VERBS:
        raise ValueError(f"refusing verb {verb!r}")
    return PKEXEC, [HELPER, verb, target(device)]


def poll_argv() -> tuple[str, list[str]]:
    # No pkexec: reading sysfs needs no privilege, only writing does.
    return HELPER, ["state"]


def _attached_parked(state: TrayState) -> int:
    return sum(1 for d in state.devices or () if d.attached and d.parked)


def apply_poll(state: TrayState, result: ProcResult) -> tuple[TrayState, str | None]:
    """The new state after a poll, and the kept-off notice text if this is
    the one poll per run that sends it."""
    # 127 from a direct run is "the binary is not there" (or the wrapper's
    # exec target is not). Unambiguous because the poll never goes through
    # pkexec, which overloads 127.
    if not result.started or (not result.crashed and result.code == 127):
        return replace(state, helper_missing=True, devices=None), None
    state = replace(state, helper_missing=False)
    if result.crashed or result.code != 0:
        err = result.stderr.strip() or "Could not read device state"
        return replace(state, last_error=err), None
    try:
        devices = parse_state(result.stdout.strip())
    except StateError:
        return replace(state, last_error="Could not parse the device list"), None
    state = replace(state, devices=devices, last_error="")
    # Checked once, on the first good poll after start (login), not on every
    # tick: a device kept later was switched off by an operator who watched.
    if state.kept_notice_sent:
        return state, None
    state = replace(state, kept_notice_sent=True)
    names = [d.label for d in devices if d.attached and d.parked and d.kept]
    return state, (", ".join(names) if names else None)


# The authentication agent each desktop usually runs, named only where
# `apt-cache policy` found the package (2026-09-28, Debian 13 and Ubuntu
# 24.04). xfce-polkit exists in neither; policykit-1-gnome only in Ubuntu
# 24.04, so Xfce is also offered mate-polkit, which both carry.
_AGENTS = {
    "LXQT": "lxqt-policykit",
    "XFCE": "policykit-1-gnome (Ubuntu) or mate-polkit",
    "LXDE": "lxpolkit",
    "MATE": "mate-polkit",
}
_ANY_AGENT = "lxpolkit or mate-polkit"


def no_agent_message(desktop: str) -> str:
    """One line for pkexec's "No authentication agent found". ``desktop``
    is XDG_CURRENT_DESKTOP, a colon-separated list."""
    package = _ANY_AGENT
    for name in desktop.split(":"):
        if name.strip().upper() in _AGENTS:
            package = _AGENTS[name.strip().upper()]
            break
    return (
        "No polkit authentication agent is running, so no password prompt "
        f"could appear. Install one ({package}) and log in again."
    )


def begin_action(state: TrayState) -> TrayState:
    return replace(state, acting=True, last_error="", action_error="")


def apply_action(state: TrayState, result: ProcResult, desktop: str = "") -> TrayState:
    """A park or wake finished. pkexec exits 126 when the prompt is dismissed
    and 127 when authorisation is refused; nothing was written in either
    case, so neither is an error.

    One deliberate departure from the applet: 127 whose stderr says no
    authentication agent was found is reported, naming the desktop's usual
    agent. Plasma always runs an agent, so the applet never meets this; a
    minimal Xfce or LXQt session may not, and there every click would do
    nothing and say nothing. It grants no privilege, it only says why
    nothing happened.

    Two smaller differences, both a consequence of running without a
    shell: a pkexec that cannot be started is an error here (the applet's
    shell exit 127 was silent), and a helper that exists but is not
    executable reads as not installed in the poll (the applet showed the
    shell's 126 stderr)."""
    state = replace(state, acting=False)
    if not result.started:
        return replace(state, action_error="Could not run pkexec; is it installed?")
    if result.crashed:
        return replace(state, action_error="Action failed (pkexec stopped unexpectedly)")
    if result.code == 127 and "no authentication agent" in result.stderr.lower():
        return replace(state, action_error=no_agent_message(desktop))
    if result.code not in (0, 126, 127):
        err = result.stderr.strip() or f"Action failed (exit {result.code})"
        return replace(state, action_error=err)
    return state


def icon_name(state: TrayState) -> str:
    if state.helper_missing:
        return ICON_MISSING
    return ICON_PARKED if _attached_parked(state) > 0 else ICON_AWAKE


def tooltip(state: TrayState) -> str:
    if state.helper_missing:
        sub = "Hammunition's device helper is not installed"
    elif state.devices is None:
        sub = "Reading device state…"
    elif not state.devices:
        sub = "No parkable device is attached"
    else:
        n = _attached_parked(state)
        sub = f"{n} device parked" if n == 1 else f"{n} devices parked"
    return f"{TITLE}\n{sub}"


def _device_entry(d: Device, acting: bool) -> MenuEntry:
    where = f"{d.label} ({d.address})"
    if not d.attached:
        # "wake" on an absent device clears its kept flag, which is what
        # drops it off the list.
        return MenuEntry(
            kind="forget",
            text=f"Forget {where} — kept off, not attached",
            enabled=not acting,
            verb="wake",
            device=d,
        )
    # The text follows `kept` first, as FullRepresentation.qml does; the
    # checkmark alone follows `parked`. A kept device that something woke
    # outside the helper is awake now and will be parked again at the next
    # plug-in or boot: D-056 shows intent and reality, never reconciles them.
    status = "kept off" if d.kept else ("parked" if d.parked else "awake")
    return MenuEntry(
        kind="toggle",
        text=f"{where} — {status}",
        enabled=not acting,
        # Checked means awake, like the applet's switch, and it is always
        # the state the helper reported: a dismissed prompt moves nothing.
        checked=not d.parked,
        verb="wake" if d.parked else "park",
        device=d,
    )


def menu_model(state: TrayState) -> list[MenuEntry]:
    entries: list[MenuEntry] = []
    if state.helper_missing:
        entries += [
            MenuEntry("info", "Device control is not installed"),
            MenuEntry(
                "info",
                "Run `hammunition hardware apply` to install the helper "
                "and the polkit action that authorises it.",
            ),
        ]
    elif state.devices is None:
        entries.append(MenuEntry("info", "Reading device state…"))
    elif not state.devices:
        entries += [
            MenuEntry("info", "No parkable device is attached"),
            MenuEntry(
                "info",
                "A device is parkable when its catalog entry carries a "
                "power_control block and it is plugged in now.",
            ),
        ]
    else:
        entries += [_device_entry(d, state.acting) for d in state.devices]
    for error in (state.last_error, state.action_error):
        if error:
            entries.append(MenuEntry("error", error))
    if not state.helper_missing:
        entries += [MenuEntry("separator"), MenuEntry("footer", FOOTER)]
    entries += [MenuEntry("separator"), MenuEntry("quit", "Quit", enabled=True)]
    return entries
