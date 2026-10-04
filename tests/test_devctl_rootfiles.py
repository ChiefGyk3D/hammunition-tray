# SPDX-FileCopyrightText: Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later

"""``rootfiles.atomic_write``: the mode it writes, and the modes it refuses."""

from __future__ import annotations

from pathlib import Path

import pytest

from hammunition_devctl.rootfiles import atomic_write


def test_the_default_mode_is_world_readable_and_owner_writable_only(
    tmp_path: Path,
) -> None:
    target = tmp_path / "x.rules"
    atomic_write(target, "a\n")
    assert oct(target.stat().st_mode & 0o777) == "0o644"


@pytest.mark.parametrize("mode", [0o666, 0o664, 0o646, 0o620, 0o602, 0o777])
def test_a_group_or_other_writable_mode_is_refused_and_leaves_nothing(
    tmp_path: Path, mode: int
) -> None:
    target = tmp_path / "x.rules"
    with pytest.raises(ValueError, match="writable"):
        atomic_write(target, "a\n", mode=mode)
    assert list(tmp_path.iterdir()) == []


def test_a_private_mode_is_allowed(tmp_path: Path) -> None:
    target = tmp_path / "x.yaml"
    atomic_write(target, "a\n", mode=0o600)
    assert oct(target.stat().st_mode & 0o777) == "0o600"
