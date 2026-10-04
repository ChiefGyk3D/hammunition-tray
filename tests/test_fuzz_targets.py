# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Atheris targets under fuzz/ still run, so a target that rots is caught here.

GYST's python-fuzz.yml runs each target for a fixed time in CI; this is the
cheap half that runs on every ordinary test run. Each target's ``TestOneInput``
is called on a handful of seeds (empty, a valid document, a truncated one, 64 KiB
of random bytes) and must not raise. Atheris publishes wheels for CPython 3.12
to 3.14 on x86_64 only, so where it is absent the test skips, unless
``HAMMUNITION_REQUIRE_ATHERIS`` is set, which turns the skip into a failure (CI
sets it where it installs Atheris).
"""

from __future__ import annotations

import importlib.util
import os
import random
import sys
from pathlib import Path

import pytest

FUZZ_DIR = Path(__file__).resolve().parent.parent / "fuzz"
TARGETS = sorted(FUZZ_DIR.glob("fuzz_*.py"))

if importlib.util.find_spec("atheris") is None:
    if os.environ.get("HAMMUNITION_REQUIRE_ATHERIS"):
        raise ImportError("HAMMUNITION_REQUIRE_ATHERIS is set and atheris is not installed")
    pytest.skip("atheris is not installed (CPython 3.12 to 3.14, x86_64)", allow_module_level=True)

VALID = {
    "fuzz_devctl_lists": (
        b"version: 1\ndevices:\n- name: gps-usb\n  method: usb_deauthorize\n"
        b"  usb_ids:\n  - {vendor: '1546', product: 01a8}\n"
    ),
    "fuzz_sysfs_guard": b"\x01/sys/bus/usb/devices/1-4/power/control",
    "fuzz_kept_rules": (
        b'\x01# kept: gps\nACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", '
        b'KERNEL=="1-4", ATTR{idVendor}=="1546", ATTR{idProduct}=="01a8", ATTR{authorized}="0"\n'
    ),
    "fuzz_linger_record": b"uid: 1000\nenabled_by_us: true\n",
}


def _seeds(name: str) -> list[bytes]:
    valid = VALID[name]
    rng = random.Random(0)
    return [b"", valid, valid[: len(valid) // 2], bytes(rng.randrange(256) for _ in range(64 * 1024))]


def test_every_target_has_seeds() -> None:
    assert {t.stem for t in TARGETS} == set(VALID), "a target was added or removed: update VALID"


@pytest.mark.parametrize("target", TARGETS, ids=lambda p: p.stem)
def test_target_accepts_seeds(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(FUZZ_DIR))
    # A target stubs the engine-import fallback at import time; put it back afterwards so
    # the tests that exercise the real one (marker real_engine_import) still see it.
    from hammunition_devctl import devices

    monkeypatch.setattr(devices, "_from_engine", devices._from_engine)
    sys.modules.pop(target.stem, None)
    module = importlib.import_module(target.stem)
    try:
        for seed in _seeds(target.stem):
            module.TestOneInput(seed)
    finally:
        sys.modules.pop(target.stem, None)
