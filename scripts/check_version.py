#!/usr/bin/env python3
"""Refuse a release tag that disagrees with the tree it points at.

The tag is the one release input a human types. A v0.2.0 tag on a package
that says 0.1.0 publishes a version number that means two things."""

import json
import re
import sys
from pathlib import Path


def check(tag: str, root: Path) -> str:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"tag {tag!r} is not vMAJOR.MINOR.PATCH")
    wanted = tag[1:]
    meta = json.loads((root / "plasmoid/package/metadata.json").read_text())
    have = meta["KPlugin"]["Version"]
    if have != wanted:
        raise ValueError(f"tag {tag} but metadata.json says {have}")
    changelog = (root / "CHANGELOG.md").read_text()
    if not re.search(rf"^## \[{re.escape(wanted)}\]", changelog, re.M):
        raise ValueError(f"CHANGELOG.md has no '## [{wanted}]' section")
    return wanted


if __name__ == "__main__":
    try:
        print(check(sys.argv[1], Path(__file__).resolve().parent.parent))
    except (IndexError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
