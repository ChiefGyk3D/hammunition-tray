# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""Radio switches: WWAN, Wi-Fi and Bluetooth.  docs/contract.md.

Fixed argv per radio, nothing assembled from input. These are the calling
user's own switches: polkit lets an active local session flip them, so none of
this runs as root. rfkill is never written.
"""

from __future__ import annotations

from typing import Any

from hammunition_devctl.run import run

__all__ = ["NAMES", "SWITCH", "read_radios", "switch"]

NAMES = ("wwan", "wifi", "bluetooth")

SWITCH: dict[str, tuple[str, ...]] = {
    "wwan": ("nmcli", "radio", "wwan"),
    "wifi": ("nmcli", "radio", "wifi"),
    "bluetooth": ("bluetoothctl", "power"),
}
"""The command each radio's switch is; ``on`` or ``off`` is appended. This
table is the whole set of commands the ``radio`` verbs can run."""

_NMCLI_RADIO = ("nmcli", "-t", "-f", "WIFI,WWAN", "radio")
_NMCLI_DEVICES = ("nmcli", "-t", "-f", "TYPE,DEVICE", "device", "status")
_BLUETOOTH_SHOW = ("bluetoothctl", "show")

_NM_TYPES = {"wwan": ("gsm", "cdma"), "wifi": ("wifi",)}
_TOOL_MISSING = 127


def _row(name: str, method: str, present: bool, enabled: bool, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "present": present,
        "enabled": enabled and present,
        "method": method,
        "detail": detail,
    }


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def _nmcli_rows() -> list[dict[str, Any]]:
    radio = run(_NMCLI_RADIO)
    if radio.returncode == _TOOL_MISSING:
        return [_row(n, "nmcli", False, False, "nmcli is not installed") for n in ("wwan", "wifi")]
    if not radio.ok:
        why = _first_line(radio.stderr) or f"exit {radio.returncode}"
        return [_row(n, "nmcli", False, False, f"nmcli could not read radio state: {why}") for n in ("wwan", "wifi")]
    fields = radio.stdout.strip().split(":")
    wifi_on = fields[0] == "enabled" if fields else False
    wwan_on = fields[1] == "enabled" if len(fields) > 1 else False
    devices: dict[str, list[str]] = {}
    listing = run(_NMCLI_DEVICES)
    if listing.ok:
        for line in listing.stdout.splitlines():
            kind, _, device = line.partition(":")
            devices.setdefault(kind, []).append(device)
    rows = []
    for name, on in (("wwan", wwan_on), ("wifi", wifi_on)):
        names = [d for kind in _NM_TYPES[name] for d in devices.get(kind, [])]
        detail = ", ".join(names) if names else "no such device"
        rows.append(_row(name, "nmcli", bool(names), on, detail))
    return rows


def _bluetooth_row() -> dict[str, Any]:
    shown = run(_BLUETOOTH_SHOW)
    if shown.returncode == _TOOL_MISSING:
        return _row("bluetooth", "bluetoothctl", False, False, "bluetoothctl is not installed")
    text = shown.stdout
    if not shown.ok or "Controller" not in text:
        why = _first_line(shown.stdout) or _first_line(shown.stderr) or f"exit {shown.returncode}"
        return _row("bluetooth", "bluetoothctl", False, False, f"no bluetooth controller: {why}")
    on = any(line.strip() == "Powered: yes" for line in text.splitlines())
    blocked = any(line.strip() == "Blocked: yes" for line in text.splitlines())
    return _row("bluetooth", "bluetoothctl", True, on, "blocked by rfkill" if blocked else "")


def read_radios() -> dict[str, Any]:
    """The ``radios`` document: three rows, wwan, wifi, bluetooth, in that order."""
    by_name = {row["name"]: row for row in _nmcli_rows()}
    by_name["bluetooth"] = _bluetooth_row()
    return {"kind": "radios", "version": 1, "radios": [by_name[n] for n in NAMES]}


def switch(state: str, name: str) -> tuple[int, list[str]]:
    """Turn ``name`` ``on`` or ``off``. Returns ``(exit_code, problems)``.

    Exit 2 for a radio whose tool is absent, 1 for a change that failed or did
    not read back, 0 for one that did.
    """
    wanted = state == "on"
    current = {row["name"]: row for row in read_radios()["radios"]}[name]
    if not current["present"]:
        return 2, [f"the {name} radio is not available: {current['detail']}"]
    result = run((*SWITCH[name], state))
    if not result.ok:
        return 1, [f"{' '.join(SWITCH[name])} {state} failed: {_first_line(result.stderr) or f'exit {result.returncode}'}"]
    after = {row["name"]: row for row in read_radios()["radios"]}[name]
    if after["enabled"] != wanted:
        return 1, [f"{name} was asked to turn {state} and reads {'on' if after['enabled'] else 'off'} afterwards"]
    return 0, []
