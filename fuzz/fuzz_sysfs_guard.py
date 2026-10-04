"""Fuzz target: the lexical sysfs path guard of the root helper.

`power.guard` is the one check between a path and a root write under /sys. Any
string may reach it; it must either refuse (PowerError) or return a path that,
after `os.path.normpath`, sits under an allowed root as exactly one device
component followed by one writable leaf. The target asserts that property, so a
path that slips outside the roots, or into a kernel-made symlink such as
`driver/unbind`, is a crash. Nothing is written: the guard is pure.
"""

import os
import sys

import atheris

with atheris.instrument_imports():
    from hammunition_devctl import power

_SEEDS = ("/sys/bus/usb/devices/", "/sys/bus/pci/devices/", "../", "/power/control", "/authorized", "//", "driver/")


def _candidate(fdp: atheris.FuzzedDataProvider) -> str:
    """Mostly structured near-misses of the legal shape, so the fuzzer reaches the
    interesting branches instead of only the 'outside every root' refusal."""
    parts: list[str] = []
    for _ in range(fdp.ConsumeIntInRange(0, 8)):
        if fdp.ConsumeBool():
            parts.append(_SEEDS[fdp.ConsumeIntInRange(0, len(_SEEDS) - 1)])
        else:
            parts.append(fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 12)))
    return "".join(parts)


def _check(path: str) -> None:
    try:
        accepted = power.guard(path)
    except power.PowerError:
        return  # the documented refusal
    assert accepted == os.path.normpath(path), f"guard returned {accepted!r} for {path!r}"
    for root in power.ALLOWED_ROOTS:
        prefix = root.rstrip("/") + "/"
        if accepted.startswith(prefix):
            rest = accepted[len(prefix) :].split("/")
            assert rest[0] and ".." not in rest and "" not in rest, f"guard accepted {path!r} with a bad component"
            assert "/".join(rest[1:]) in power.WRITABLE_LEAVES, f"guard accepted {path!r} with a leaf it never writes"
            return
    raise AssertionError(f"guard accepted {path!r} as {accepted!r}, outside every allowed root")


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    _check(_candidate(fdp))
    _check(fdp.ConsumeUnicodeNoSurrogates(256))
    # The kept-rules file's own guard is an exact match; nothing else may pass.
    other = fdp.ConsumeUnicodeNoSurrogates(64)
    if other != power.KEPT_RULES:
        try:
            power._guard_kept(other)
        except power.PowerError:
            return
        raise AssertionError(f"_guard_kept accepted {other!r}")


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
