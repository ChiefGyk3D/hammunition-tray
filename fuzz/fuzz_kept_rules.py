"""Fuzz target: the reader of the kept-parked udev rules file.

`power.parse_kept` reads /etc/udev/rules.d/66-hammunition-kept.rules back before
the helper rewrites it, and anything it does not recognise must be a refusal
(PowerError), never a skipped line and never another exception. A file it
accepts must survive a round trip through `render_kept`, and every value in an
accepted entry must be the shape that is allowed to reach a root-applied udev
rule. Pure over text: no file is read or written.
"""

import re
import sys

import atheris

with atheris.instrument_imports():
    from hammunition_devctl import power

_ADDRESS = re.compile(r"\d+-\d+(\.\d+)*")
_HEX4 = re.compile(r"[0-9a-f]{4}")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def _text(fdp: atheris.FuzzedDataProvider) -> str:
    """Raw text half the time; otherwise a plausible file with one mutated field."""
    if fdp.ConsumeBool():
        return fdp.ConsumeUnicodeNoSurrogates(2048)
    lines = [power.KEPT_HEADER.rstrip("\n")]
    for _ in range(fdp.ConsumeIntInRange(0, 4)):
        name = fdp.ConsumeUnicodeNoSurrogates(8)
        entry = power.KeptEntry(
            name,
            fdp.ConsumeUnicodeNoSurrogates(6),
            fdp.ConsumeUnicodeNoSurrogates(4),
            fdp.ConsumeUnicodeNoSurrogates(4),
        )
        lines.append(f"# kept: {entry.name}")
        lines.append(entry.rule())
    return "\n".join(lines) + fdp.ConsumeUnicodeNoSurrogates(16)


def TestOneInput(data: bytes) -> None:
    text = _text(atheris.FuzzedDataProvider(data))
    try:
        entries = power.parse_kept(text)
    except power.PowerError:
        return  # the documented refusal
    for e in entries:
        assert _NAME.fullmatch(e.name) and _ADDRESS.fullmatch(e.address)
        assert _HEX4.fullmatch(e.vendor) and _HEX4.fullmatch(e.product)
    assert power.parse_kept(power.render_kept(entries)) == sorted(
        set(entries), key=lambda e: (e.address, e.vendor, e.product, e.name)
    )


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
