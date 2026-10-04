"""Fuzz target: the linger record and the polkit wrapper script.

`linger.read_record` parses a YAML file the helper wrote as root; every way it
can be wrong must come back as "absent, with a note", because a reading verb
must still print its one JSON document. `polkit.wrapper_script` builds the
shell wrapper root executes, so whatever interpreter or entry path it is given,
the script must stay three fixed lines plus exactly one `exec` line whose words
are shell-quoted. The bytes go to a file inside a temp directory the target made.
"""

import shlex
import sys
import tempfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from hammunition_devctl import linger, polkit

_TMP = tempfile.TemporaryDirectory(prefix="fuzz-linger-")
_RECORD = Path(_TMP.name) / "linger.yaml"


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    _RECORD.write_bytes(fdp.ConsumeBytes(2048))
    notes: list[str] = []
    record = linger.read_record(_RECORD, notes)
    if record is not None:
        assert isinstance(record.uid, int) and isinstance(record.enabled_by_us, bool)

    interpreter = fdp.ConsumeUnicodeNoSurrogates(48)
    entry = fdp.ConsumeUnicodeNoSurrogates(48)
    script = polkit.wrapper_script(interpreter, entry)
    # Reading the whole script as a shell would (comments dropped, quotes honoured), what is
    # left must be `cd /` and one exec of exactly the two words given, nothing smuggled in.
    words = shlex.split(script, comments=True)
    assert words == ["cd", "/", "exec", interpreter, "-I", entry, "$@"], words


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
