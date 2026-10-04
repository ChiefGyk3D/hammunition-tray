# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""The records the helper's modules pass between each other.

A leaf: it imports nothing from this package. ``bus`` (what is plugged in),
``devices`` (what may be parked) and ``power`` (the park/wake plans) each
need the others' shapes, and importing them from one another made a ring
that worked only for one import order. The shapes live here; each of those
modules re-exports the names it used to define.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "AttachedDevice",
    "DeviceEntry",
    "Match",
    "PowerMethod",
    "QuietVerb",
    "UsbId",
]

PowerMethod = Literal["usb_deauthorize", "pci_runtime"]
"""The engine's closed enum (D-056). A device file may carry either; only the
first is implemented, and the second is refused when a verb would act on it."""

QuietVerb = Literal["networkmanager_autoconnect"]
"""The engine's closed vocabulary of consumers to hush. Schema-valid, refused
when non-empty, exactly as in the engine."""


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


@dataclass(frozen=True)
class AttachedDevice:
    """One USB device the kernel is reporting."""

    vendor: str
    product: str
    manufacturer: str | None = None
    product_string: str | None = None
    serial: str | None = None
    sysfs_path: str | None = None
    """The node this record was read from. Kept because the power planner must
    write to *the node it read*, not to one re-found by identifier: two
    identical dongles share an identifier and differ only in address."""

    @property
    def identifier(self) -> str:
        return f"{self.vendor}:{self.product}"


@dataclass(frozen=True)
class Match:
    """A device-list entry the bus appears to contain."""

    name: str
    attached: AttachedDevice
