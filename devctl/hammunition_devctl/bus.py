# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""What is plugged in, read from sysfs.  D-056 (moved from the engine).

The USB bus is read from ``/sys/bus/usb/devices``, never from ``lsusb``: the
kernel already published the descriptor fields in files, ``lsusb`` is a
package that may be absent, and its output is for people.

The match against the device list is the engine's rule, reduced to what
parking needs: vendor, product, and -- for an identifier the catalog records
as shared between products -- the product string. Whether a match is
"ambiguous" matters to the engine when it names a device persistently
(D-028) and does not matter to parking, which is reversible and visible, so
it is not carried here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hammunition_devctl.model import AttachedDevice, DeviceEntry, Match

__all__ = ["USB_DEVICES", "AttachedDevice", "Match", "match_devices", "read_usb_bus"]

USB_DEVICES = Path("/sys/bus/usb/devices")


def _read(path: Path) -> str | None:
    try:
        value = path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return value or None


def read_usb_bus(root: Path | None = None) -> list[AttachedDevice]:
    """Every USB device sysfs reports, deduplicated by identifier and serial.

    An absent ``/sys/bus/usb/devices`` is an empty list, not an error: a
    container without USB passthrough is a normal place to run this.
    """
    base = root or USB_DEVICES
    if not base.is_dir():
        return []
    seen: dict[tuple[str, str, str | None], AttachedDevice] = {}
    for entry in sorted(base.iterdir()):
        vendor = _read(entry / "idVendor")
        product = _read(entry / "idProduct")
        if not vendor or not product:
            continue  # an interface or a root hub, not a device
        device = AttachedDevice(
            vendor=vendor.lower(),
            product=product.lower(),
            manufacturer=_read(entry / "manufacturer"),
            product_string=_read(entry / "product"),
            serial=_read(entry / "serial"),
            sysfs_path=str(entry),
        )
        seen.setdefault((device.vendor, device.product, device.serial), device)
    return list(seen.values())


def match_devices(
    attached: list[AttachedDevice], entries: Mapping[str, DeviceEntry]
) -> list[Match]:
    """Every (entry, attached device) pair the identifiers say belong together.

    A device matched by two entries is returned once per entry, in entry-name
    order, as the engine's matcher always did; ``NAME@ADDRESS`` tells two of
    a kind apart.
    """
    matches: list[Match] = []
    for device in attached:
        for name, entry in sorted(entries.items()):
            for usb_id in entry.usb_ids:
                if usb_id.vendor != device.vendor:
                    continue
                if usb_id.product and usb_id.product != device.product:
                    continue
                if (
                    usb_id.product_string
                    and device.product_string
                    and usb_id.product_string != device.product_string
                ):
                    continue  # a different product sharing the identifier
                matches.append(Match(name=name, attached=device))
    return matches
