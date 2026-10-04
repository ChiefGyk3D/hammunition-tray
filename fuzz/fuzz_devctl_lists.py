"""Fuzz target: the two allow-lists the root helper reads (devices and services).

`/etc/hammunition/devctl-devices.yaml` and `devctl-services.yaml` decide what a
root process may park or control, so a list that makes the reader raise, or that
lets a row through with a value the validators exist to refuse, is a bug. The
bytes are written to a file inside a temp directory the target made, and the
module's file constants are pointed at it; nothing under the real /etc or the
real HOME is read, and no command is run.
"""

import re
import sys
import tempfile
from pathlib import Path

import atheris
import yaml

with atheris.instrument_imports():
    from hammunition_devctl import datafiles, devices, run, services

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_HEX4 = re.compile(r"[0-9a-f]{4}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# A verb that tried to run a command would be a bug in a reader, so any call is an assertion.


def _refuse(argv):  # type: ignore[no-untyped-def]
    raise AssertionError(f"a list reader ran a command: {list(argv)!r}")


run.set_runner(_refuse)
devices._from_engine = lambda notes: None  # type: ignore[assignment]  # never import the engine here

_TMP = tempfile.TemporaryDirectory(prefix="fuzz-devctl-lists-")
_DIR = Path(_TMP.name)


def _check_device(name: str, entry: devices.DeviceEntry) -> None:
    assert entry.name == name and _NAME.fullmatch(name)
    assert entry.method in ("usb_deauthorize", "pci_runtime")
    assert all(q == "networkmanager_autoconnect" for q in entry.quiet)
    assert entry.usb_ids
    for uid in entry.usb_ids:
        assert _HEX4.fullmatch(uid.vendor)
        assert uid.product is None or _HEX4.fullmatch(uid.product)


def _scalar(fdp: atheris.FuzzedDataProvider, good: tuple[str, ...]) -> object:
    """A known-good value, a near miss, or an arbitrary one, so rows reach the validators."""
    pick = fdp.ConsumeIntInRange(0, 4)
    if pick == 0:
        return good[fdp.ConsumeIntInRange(0, len(good) - 1)]
    if pick == 1:
        return good[fdp.ConsumeIntInRange(0, len(good) - 1)] + fdp.ConsumeUnicodeNoSurrogates(3)
    if pick == 2:
        return fdp.ConsumeIntInRange(-5, 70000)
    if pick == 3:
        return None
    return fdp.ConsumeUnicodeNoSurrogates(12)


def _structured(fdp: atheris.FuzzedDataProvider, kind: str) -> bytes:
    """A version-1 document whose rows are mostly right and sometimes not."""
    rows: list[object] = []
    for _ in range(fdp.ConsumeIntInRange(0, 4)):
        if kind == "devices":
            ids = [
                {
                    "vendor": _scalar(fdp, ("1546", "0bda", "12d1")),
                    "product": _scalar(fdp, ("01a8", "2838")),
                    "product_string": _scalar(fdp, ("GPS",)),
                }
                for _ in range(fdp.ConsumeIntInRange(0, 2))
            ]
            rows.append(
                {
                    "name": _scalar(fdp, ("gps-usb", "modem")),
                    "summary": _scalar(fdp, ("a device",)),
                    "method": _scalar(fdp, ("usb_deauthorize", "pci_runtime")),
                    "quiet": [_scalar(fdp, ("networkmanager_autoconnect",))] if fdp.ConsumeBool() else [],
                    "usb_ids": ids,
                }
            )
        else:
            rows.append(
                {
                    "name": _scalar(fdp, ("gpsd", "rnsd")),
                    "unit": _scalar(fdp, ("gpsd.service", "a@b.timer")),
                    "scope": _scalar(fdp, ("system", "user")),
                    "description": _scalar(fdp, ("a service",)),
                }
            )
    doc = {"version": _scalar(fdp, ("1",)) if fdp.ConsumeBool() else 1, kind: rows}
    return yaml.safe_dump(doc).encode()


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    if fdp.ConsumeBool():
        data = _structured(fdp, "devices")
        services_bytes = _structured(fdp, "services")
    else:
        data = services_bytes = fdp.ConsumeBytes(2048)
    devices_file = _DIR / "devices.yaml"
    services_file = _DIR / "services.yaml"
    user_file = _DIR / "user-services.yaml"
    devices_file.write_bytes(data)
    services_file.write_bytes(services_bytes)
    user_file.write_bytes(services_bytes)
    datafiles.DEVICES_FILE = devices_file
    datafiles.SERVICES_FILE = services_file

    notes: list[str] = []
    entries, source = devices.load_devices(notes)
    assert source in ("file", "none")
    for name, entry in entries.items():
        _check_device(name, entry)

    notes = []
    listed = services.load_services(notes, user_file=user_file)
    seen: set[str] = set()
    for svc in listed:
        assert svc.name not in seen
        seen.add(svc.name)
        assert _NAME.fullmatch(svc.name)
        assert services._UNIT.fullmatch(svc.unit)
        assert svc.scope in ("system", "user")
        assert len(svc.description) <= 200 and not _CONTROL.search(svc.description)

    # The root reader's own gate, on a file this process owns: it must refuse, not raise.
    notes = []
    assert datafiles.read_text_as_root(devices_file, notes) is None or not notes


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
