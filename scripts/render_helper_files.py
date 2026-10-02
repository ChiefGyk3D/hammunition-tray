#!/usr/bin/env python3
"""Print the two files the helper is installed with, from the code that defines them.

    render_helper_files.py wrapper INTERPRETER ENTRY   # the /bin/sh wrapper
    render_helper_files.py policy                      # the polkit action

install.sh, the Debian build and the tests all call this, so the wrapper and
the policy are written in one place (devctl/hammunition_devctl/polkit.py) and
cannot drift between the three. Stdlib only: it runs before anything is
installed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "devctl"))

from hammunition_devctl.polkit import policy_xml, wrapper_script  # noqa: E402


def _absolute(label: str, value: str) -> str:
    if not value.startswith("/") or "\n" in value or "\0" in value:
        raise SystemExit(f"error: {label} must be an absolute path on one line, got {value!r}")
    return value


def main(argv: list[str]) -> int:
    if argv[:1] == ["policy"] and len(argv) == 1:
        sys.stdout.write(policy_xml())
        return 0
    if argv[:1] == ["wrapper"] and len(argv) == 3:
        sys.stdout.write(
            wrapper_script(_absolute("INTERPRETER", argv[1]), _absolute("ENTRY", argv[2]))
        )
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
