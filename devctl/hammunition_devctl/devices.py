# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""The list of devices that can be parked, and where it came from.

``/etc/hammunition/devctl-devices.yaml`` is the list (docs/contract.md). The
engine writes it from every catalogued device or class that carries a
``power_control`` block. Until that file exists the helper falls back to
importing the engine and building the same list from its catalog, and says
so (``source: "engine-import"``); with neither it finds nothing
(``source: "none"``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from hammunition_devctl import datafiles
from hammunition_devctl.power import PowerMethod, QuietVerb

__all__ = ["DeviceEntry", "Source", "UsbId", "load_devices"]

Source = Literal["file", "engine-import", "none"]

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_HEX4 = re.compile(r"[0-9a-f]{4}")
_METHODS = ("usb_deauthorize", "pci_runtime")
_QUIET = ("networkmanager_autoconnect",)


@dataclass(frozen=True)
class UsbId:
    vendor: str
    product: str | None = None
    product_string: str | None = None


@dataclass(frozen=True)
class DeviceEntry:
    """One parkable device or class, as the device file or the catalog says."""

    name: str
    summary: str
    method: PowerMethod
    quiet: tuple[QuietVerb, ...]
    usb_ids: tuple[UsbId, ...]


def _hex4(value: object) -> str | None:
    text = str(value).strip().lower() if value is not None else ""
    return text if _HEX4.fullmatch(text) else None


def _entry_from(row: object, notes: list[str]) -> DeviceEntry | None:
    if not isinstance(row, dict):
        notes.append("a devices row is not a mapping; dropped")
        return None
    name = row.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        notes.append(f"a devices row has the name {name!r}; dropped")
        return None
    method = row.get("method")
    if method not in _METHODS:
        notes.append(f"device {name!r} has method {method!r}; dropped")
        return None
    quiet_raw = row.get("quiet") or []
    if not isinstance(quiet_raw, list) or any(q not in _QUIET for q in quiet_raw):
        notes.append(f"device {name!r} has quiet verbs {quiet_raw!r}; dropped")
        return None
    ids: list[UsbId] = []
    for raw in row.get("usb_ids") or []:
        vendor = _hex4(raw.get("vendor")) if isinstance(raw, dict) else None
        if vendor is None:
            notes.append(f"device {name!r} has a usb_ids row with no valid vendor; skipped")
            continue
        product = _hex4(raw.get("product")) if raw.get("product") is not None else None
        if raw.get("product") is not None and product is None:
            notes.append(f"device {name!r} has a usb_ids row with a bad product; skipped")
            continue
        text = raw.get("product_string")
        ids.append(UsbId(vendor, product, text if isinstance(text, str) and text else None))
    if not ids:
        notes.append(f"device {name!r} has no usable usb_ids; dropped")
        return None
    summary = row.get("summary")
    return DeviceEntry(
        name=name,
        summary=summary if isinstance(summary, str) else "",
        method=cast(PowerMethod, method),
        quiet=tuple(cast("list[QuietVerb]", quiet_raw)),
        usb_ids=tuple(ids),
    )


def _from_engine(notes: list[str]) -> dict[str, DeviceEntry] | None:
    """The same list, built from the engine's catalog. ``None`` when the
    engine is not importable or its catalog cannot be found."""
    from hammunition_devctl import devctl

    if not devctl.engine_importable_as_root():
        return None
    try:
        from hammunition.cli.main import find_catalog  # type: ignore[import-not-found,unused-ignore]
        from hammunition.manifest.load import load_hardware  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        return None
    try:
        classes, devices = load_hardware(find_catalog(None) / "hardware")
    except (Exception, SystemExit) as exc:
        # The engine's own errors, whatever they are -- including the SystemExit
        # `find_catalog` raises when there is no checkout beside an installed
        # wheel, which is not an Exception and would end this process.
        notes.append(f"the engine's catalog could not be read: {exc}")
        return None
    found: dict[str, DeviceEntry] = {}
    merged: dict[str, Any] = {**classes, **devices}
    for name, entry in merged.items():
        control = entry.power_control
        if control is None:
            continue
        ids = tuple(
            UsbId(
                vendor=u.vendor.lower(),
                product=u.product.lower() if u.product else None,
                product_string=u.product_string if u.ambiguity is not None else None,
            )
            for u in entry.usb_ids
            if u.confirmed
        )
        if not ids:
            continue
        found[name] = DeviceEntry(
            name=name,
            summary=entry.summary,
            method=control.method,
            quiet=tuple(control.quiet),
            usb_ids=ids,
        )
    return found


def load_devices(notes: list[str]) -> tuple[dict[str, DeviceEntry], Source]:
    """The parkable-device list and where it came from.

    The file is authoritative whenever it exists, even when it is empty or
    unreadable: a machine whose file says nothing is parkable must not fall
    back to an engine catalog that says otherwise.
    """
    before = len(notes)
    data = datafiles.load_yaml(datafiles.DEVICES_FILE, notes)
    if data is not None:
        entries: dict[str, DeviceEntry] = {}
        rows = data.get("devices")
        if rows is not None and not isinstance(rows, list):
            notes.append(f"{datafiles.DEVICES_FILE}: devices is not a list; treated as empty")
            rows = []
        for row in rows or []:
            entry = _entry_from(row, notes)
            if entry is not None:
                entries[entry.name] = entry
        return entries, "file"
    if len(notes) > before or datafiles.DEVICES_FILE.exists():
        return {}, "file"
    engine = _from_engine(notes)
    if engine is not None:
        return engine, "engine-import"
    return {}, "none"
