# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The wrapper and the polkit action the helper is installed with, and the
writability check it repeats as root. The plan-and-compare half stays with
the engine."""

from __future__ import annotations

import os
import re
import shlex
from xml.etree import ElementTree


from hammunition_devctl.polkit import (
    ACTION_ID,
    HELPER_PATH,
    WritabilityFinding,
    WritabilityRisk,
    describe_refusal,
    group_is_private_to,
    policy_xml,
    wrapper_script,
    writable_by_non_root,
    writable_including_symlink_target,
)


def _stat(uid: int, mode: int = 0o40755, gid: int = 0) -> os.stat_result:
    return os.stat_result((mode, 0, 0, 1, uid, gid, 0, 0, 0, 0))


def _owned(path: str) -> WritabilityFinding:
    return WritabilityFinding(path, WritabilityRisk.OWNED_BY_NON_ROOT)


def _writable(path: str) -> WritabilityFinding:
    return WritabilityFinding(path, WritabilityRisk.GROUP_OR_OTHER_WRITABLE)


ENTRY = "/usr/share/hammunition-devctl/hammunition-devctl"


def test_the_policy_is_well_formed_xml() -> None:
    root = ElementTree.fromstring(policy_xml())
    assert root.tag == "policyconfig"


def test_the_policy_declares_exactly_one_action_with_our_id() -> None:
    root = ElementTree.fromstring(policy_xml())
    actions = root.findall("action")
    assert len(actions) == 1
    assert actions[0].get("id") == ACTION_ID


def test_the_policy_prompts_once_then_stays_quiet_for_the_session() -> None:
    root = ElementTree.fromstring(policy_xml())
    defaults = root.find("action/defaults")
    assert defaults is not None
    assert defaults.findtext("allow_active") == "auth_self_keep"
    assert defaults.findtext("allow_inactive") == "auth_admin"
    assert defaults.findtext("allow_any") == "auth_admin"


def test_the_policy_annotates_the_wrapper_path_it_authorises() -> None:
    root = ElementTree.fromstring(policy_xml())
    annotations = {a.get("key"): (a.text or "") for a in root.findall("action/annotate")}
    assert annotations["org.freedesktop.policykit.exec.path"] == HELPER_PATH
    assert annotations["org.freedesktop.policykit.exec.allow_gui"] == "true"


def test_the_wrapper_execs_the_interpreter_that_owns_the_package() -> None:
    """A venv install's entry point is not on root's PATH, and polkit
    annotates an absolute path. The wrapper is the stable indirection."""
    body = wrapper_script("/opt/hammunition/.venv/bin/python3", ENTRY)
    assert body.startswith("#!/bin/sh\n")
    assert "/opt/hammunition/.venv/bin/python3" in body
    assert ENTRY in body
    assert body.rstrip().endswith('"$@"')


def test_the_wrapper_quotes_an_interpreter_path_with_a_space() -> None:
    body = wrapper_script("/home/op/my venv/bin/python3", ENTRY)
    assert shlex.quote("/home/op/my venv/bin/python3") in body


def test_the_wrapper_runs_the_interpreter_isolated() -> None:
    """CRITICAL fix: `python -m <pkg>` inserts `os.getcwd()` at `sys.path[0]`.
    `pkexec` normally masks that by `chdir()`-ing to the target user's home,
    but `pkexec --keep-cwd` does not, and the polkit action pins an
    executable *path*, not an argument list -- nothing stops a caller from
    adding that flag. Without `-I`, a local user could `cd` to a directory
    holding their own `hammunition_devctl/devctl.py` and have it imported and
    run as root instead of the real one. `-I` must sit between the
    interpreter and `-m`, exactly where it takes effect for the module
    import that follows.

    Falsified: removing ` -I` from the wrapper's exec line turns this red
    (confirmed by hand before this test was written); restoring it turns it
    green again.
    """
    body = wrapper_script("/opt/hammunition/.venv/bin/python3", ENTRY)
    match = re.search(
        r"exec\s+"
        + re.escape(shlex.quote("/opt/hammunition/.venv/bin/python3"))
        + r"\s+(-I)\s+"
        + re.escape(shlex.quote(ENTRY)),
        body,
    )
    assert match is not None, f"expected ' -I' between the interpreter and the entry; got: {body!r}"


def test_writable_by_non_root_finds_the_first_offending_component_from_the_leaf_up() -> None:
    """The operator's own venv, sitting under a root-owned prefix -- the
    normal, expected shape D-056's ruling is about, not an exotic attack."""
    chain = {
        "/opt/hammunition/.venv/bin/python3": _stat(0, 0o100755),
        "/opt/hammunition/.venv/bin": _stat(0),
        "/opt/hammunition/.venv": _stat(1000),
        "/opt/hammunition": _stat(0),
        "/opt": _stat(0),
        "/": _stat(0),
    }
    offending = writable_by_non_root(
        "/opt/hammunition/.venv/bin/python3", stat_fn=lambda p: chain[p]
    )
    assert offending == _owned("/opt/hammunition/.venv")


def test_writable_by_non_root_is_none_when_every_component_is_closed() -> None:
    chain = {
        "/opt/hammunition/.venv/bin/python3": _stat(0, 0o100755),
        "/opt/hammunition/.venv/bin": _stat(0),
        "/opt/hammunition/.venv": _stat(0),
        "/opt/hammunition": _stat(0),
        "/opt": _stat(0),
        "/": _stat(0),
    }
    offending = writable_by_non_root(
        "/opt/hammunition/.venv/bin/python3", stat_fn=lambda p: chain[p]
    )
    assert offending is None


def test_writable_by_non_root_flags_a_root_owned_but_world_writable_component() -> None:
    """Ownership alone is not the whole check: a root-owned directory that is
    group- or other-writable is exactly as replaceable as one somebody else
    owns outright -- and it is the severe class, not the confirmable one."""
    chain = {
        "/opt/thing": _stat(0, 0o40777),
        "/opt": _stat(0),
        "/": _stat(0),
    }
    offending = writable_by_non_root("/opt/thing", stat_fn=lambda p: chain[p])
    assert offending == _writable("/opt/thing")


def test_writable_by_non_root_group_or_other_writable_wins_over_a_nearer_owned_component() -> None:
    """Fix round 2: the two-pass scan must not stop at the first (leaf-most)
    finding regardless of class. A merely non-root-owned leaf must not mask
    a group-writable component further up the same chain -- the severe fact
    always wins, wherever it sits."""
    chain = {
        "/opt/hammunition/.venv/bin/python3": _stat(1000, 0o100755),
        "/opt/hammunition/.venv/bin": _stat(1000),
        "/opt/hammunition/.venv": _stat(1000),
        "/opt/hammunition": _stat(0, 0o40777),  # group/other-writable, further up
        "/opt": _stat(0),
        "/": _stat(0),
    }
    offending = writable_by_non_root(
        "/opt/hammunition/.venv/bin/python3", stat_fn=lambda p: chain[p]
    )
    assert offending == _writable("/opt/hammunition")


def test_writable_by_non_root_treats_an_unstattable_component_as_the_severe_class() -> None:
    """A component that cannot be stat'd cannot be proven safe either, and
    the conservative answer is the one that gets refused, not the one that
    gets merely confirmed."""

    def raising(path: str) -> os.stat_result:
        raise OSError("permission denied")

    offending = writable_by_non_root("/opt/hammunition/.venv/bin/python3", stat_fn=raising)
    assert offending is not None
    assert offending.risk is WritabilityRisk.GROUP_OR_OTHER_WRITABLE
    assert offending.unstatable is True, (
        "fix round 3, item 6: an unstat'd component is a different fact from "
        "an actually-writable one, and must be flagged as such"
    )


def test_writable_by_non_root_a_real_writable_component_is_not_flagged_unstatable() -> None:
    """The mirror of the test above: a component that really is group- or
    other-writable (and stat'd successfully) must not carry the `unstatable`
    flag, or `describe_refusal` would understate it."""
    chain = {
        "/opt/thing": _stat(0, 0o40777),
        "/opt": _stat(0),
        "/": _stat(0),
    }
    offending = writable_by_non_root("/opt/thing", stat_fn=lambda p: chain[p])
    assert offending is not None
    assert offending.unstatable is False


def test_describe_refusal_distinguishes_writable_from_unstatable() -> None:
    """Fix round 3, item 6: 'is writable by any local account' is simply
    false of a component that could not be read at all -- different fact,
    different sentence."""
    writable = WritabilityFinding("/opt/thing", WritabilityRisk.GROUP_OR_OTHER_WRITABLE)
    unstatable = WritabilityFinding(
        "/opt/other", WritabilityRisk.GROUP_OR_OTHER_WRITABLE, unstatable=True
    )

    writable_text = describe_refusal([writable])
    assert "writable" in writable_text.lower()
    assert "could not be checked" not in writable_text.lower()

    unstatable_text = describe_refusal([unstatable])
    assert "could not be checked" in unstatable_text.lower()
    assert "is writable by any local account" not in unstatable_text


_SYMLINK_BYPASS_TREE = {
    # The direct (unresolved) chain from the symlink itself. `os.stat`
    # follows a symlink, so the leaf entry carries the target's own (clean)
    # attributes -- the *directory holding the symlink* is the one that is
    # actually unsafe here, one level up.
    "/opt/hamvenv/bin/python3": _stat(0, 0o100755),
    "/opt/hamvenv/bin": _stat(0, 0o40777),  # the bypass: world-writable
    "/opt/hamvenv": _stat(0),
    "/opt": _stat(0),
    "/": _stat(0),
    # The resolved chain: a clean target with a clean chain all the way up,
    # which is exactly why checking only this side missed the bypass.
    "/usr/bin/python3.13": _stat(0, 0o100755),
    "/usr/bin": _stat(0),
    "/usr": _stat(0),
}


def _symlink_bypass_realpath(path: str) -> str:
    """Stands in for :func:`os.path.realpath`: the one path this tree cares
    about resolves through the symlink; anything else (the calls
    ``writable_by_non_root`` makes against an already-resolved path) is the
    identity, matching what ``os.path.realpath`` does to a path with no
    further symlinks to follow."""
    if path == "/opt/hamvenv/bin/python3":
        return "/usr/bin/python3.13"
    return path


def test_writable_including_symlink_target_catches_a_writable_symlink_directory() -> None:
    """Fix round 3, item 1 (Critical) / fix round 4: `plan_polkit` and the
    devctl runtime check both checked only the *resolved* interpreter path,
    but the wrapper ``exec``s the *unresolved* one. A world-writable
    directory holding a symlink to an otherwise root-owned, clean-chain
    target disabled both gates completely: resolving first hides exactly
    the directory an attacker would use to retarget the symlink itself.

    Fix round 4: the round-3 version of this test built the tree for real
    under `tmp_path`, symlinked to the real `/usr/bin/python3.13`, and
    skipped if that path did not exist. That made the test's result a
    property of the machine running it (root-owned there, uid 65534 inside
    an unprivileged user namespace, unknown-and-varying across the seven
    target containers) rather than of the code -- exactly what CLAUDE.md's
    "test the matrix, not your machine" forbids. Both `stat_fn` and
    `realpath_fn` are injected here, so nothing touches the real filesystem
    and the tree's shape is the only thing under test.
    """
    stat_fn = _SYMLINK_BYPASS_TREE.__getitem__

    # The regression, demonstrated directly: checking only the resolved path
    # finds nothing wrong, because the target's own chain really is clean.
    assert (
        writable_by_non_root(_symlink_bypass_realpath("/opt/hamvenv/bin/python3"), stat_fn=stat_fn)
        is None
    )

    # The fix: the union also checks the unresolved path and catches the
    # writable directory the symlink itself sits in.
    finding = writable_including_symlink_target(
        "/opt/hamvenv/bin/python3", stat_fn=stat_fn, realpath_fn=_symlink_bypass_realpath
    )
    assert finding is not None
    assert finding.risk is WritabilityRisk.GROUP_OR_OTHER_WRITABLE
    assert finding.path == "/opt/hamvenv/bin"


def test_writable_including_symlink_target_falsification_resolved_only_misses_it() -> None:
    """Falsifies the exact round-3 fix: a version of the union that checks
    only the resolved path (what every call site did before fix round 3)
    must be shown finding nothing, over the same synthetic tree the test
    above proves the real fix catches."""
    stat_fn = _SYMLINK_BYPASS_TREE.__getitem__

    def resolved_only(path: str) -> WritabilityFinding | None:
        return writable_by_non_root(_symlink_bypass_realpath(path), stat_fn=stat_fn)

    assert resolved_only("/opt/hamvenv/bin/python3") is None, (
        "this is the bug fix round 3 closes, demonstrated directly: a "
        "resolved-only check must find nothing on a tree the real fix flags"
    )


# -- A user-private group is not "any local account" -------------------------
#
# Measured on the field laptop, 2026-09-27: Parrot 7's stock session umask is
# 0002 with USERGROUPS_ENAB, so every checkout and venv the operator creates is
# group-writable -- by the operator's own group, which has no other member.
# The gate refused that as "writable by any local account", which was false,
# and the helper could not be installed at all. Group-write is the escalation
# only when somebody other than the owner is in the group.

_OPERATOR = 1000
_PRIVATE_GID = 1002
_SHARED_GID = 1003


def _only_private(gid: int, uid: int) -> bool:
    return gid == _PRIVATE_GID and uid == _OPERATOR


def _venv_chain(bin_mode: int, bin_gid: int) -> dict[str, os.stat_result]:
    return {
        "/home/op/src/ham/.venv/bin/python3": _stat(0, 0o100755),
        "/home/op/src/ham/.venv/bin": _stat(_OPERATOR, bin_mode, bin_gid),
        "/home/op/src/ham/.venv": _stat(_OPERATOR, 0o40755, _PRIVATE_GID),
        "/home/op/src/ham": _stat(_OPERATOR, 0o40755, _PRIVATE_GID),
        "/home/op/src": _stat(_OPERATOR, 0o40755, _PRIVATE_GID),
        "/home/op": _stat(_OPERATOR, 0o40700, _PRIVATE_GID),
        "/home": _stat(0),
        "/": _stat(0),
    }


def test_group_write_by_the_owners_private_group_is_only_confirmable() -> None:
    chain = _venv_chain(0o40775, _PRIVATE_GID)
    finding = writable_by_non_root(
        "/home/op/src/ham/.venv/bin/python3",
        stat_fn=chain.__getitem__,
        private_group_fn=_only_private,
    )
    assert finding == _owned("/home/op/src/ham/.venv/bin")


def test_group_write_by_a_group_with_other_members_still_refuses() -> None:
    chain = _venv_chain(0o40775, _SHARED_GID)
    finding = writable_by_non_root(
        "/home/op/src/ham/.venv/bin/python3",
        stat_fn=chain.__getitem__,
        private_group_fn=_only_private,
    )
    assert finding == _writable("/home/op/src/ham/.venv/bin")


def test_other_write_refuses_even_when_the_group_is_private() -> None:
    chain = _venv_chain(0o40777, _PRIVATE_GID)
    finding = writable_by_non_root(
        "/home/op/src/ham/.venv/bin/python3",
        stat_fn=chain.__getitem__,
        private_group_fn=_only_private,
    )
    assert finding == _writable("/home/op/src/ham/.venv/bin")


def test_the_symlink_union_passes_the_private_group_answer_through() -> None:
    chain = _venv_chain(0o40775, _PRIVATE_GID)
    finding = writable_including_symlink_target(
        "/home/op/src/ham/.venv/bin/python3",
        stat_fn=chain.__getitem__,
        realpath_fn=lambda p: p,
        private_group_fn=_only_private,
    )
    assert finding == _owned("/home/op/src/ham/.venv/bin")


class _Group:
    def __init__(self, members: list[str]) -> None:
        self.gr_mem = members


class _Passwd:
    def __init__(self, uid: int, gid: int) -> None:
        self.pw_uid = uid
        self.pw_gid = gid


def _lookups(members: list[str], accounts: list[tuple[int, int]]) -> dict[str, object]:
    groups = {_PRIVATE_GID: _Group(members)}

    def getgrgid(gid: int) -> _Group:
        return groups[gid]  # KeyError for an unknown gid, as grp does

    return {
        "getgrgid": getgrgid,
        "getpwall": lambda: [_Passwd(u, g) for u, g in accounts],
    }


def test_a_group_is_private_when_only_its_owner_holds_it() -> None:
    lookups = _lookups([], [(0, 0), (_OPERATOR, _PRIVATE_GID)])
    assert group_is_private_to(_PRIVATE_GID, _OPERATOR, **lookups)  # type: ignore[arg-type]


def test_a_supplementary_member_makes_the_group_shared() -> None:
    lookups = _lookups(["someone"], [(0, 0), (_OPERATOR, _PRIVATE_GID)])
    assert not group_is_private_to(_PRIVATE_GID, _OPERATOR, **lookups)  # type: ignore[arg-type]


def test_another_account_with_it_as_primary_group_makes_it_shared() -> None:
    lookups = _lookups([], [(_OPERATOR, _PRIVATE_GID), (1001, _PRIVATE_GID)])
    assert not group_is_private_to(_PRIVATE_GID, _OPERATOR, **lookups)  # type: ignore[arg-type]


def test_a_group_the_owner_does_not_hold_as_primary_is_not_private_to_them() -> None:
    lookups = _lookups([], [(_OPERATOR, 100)])
    assert not group_is_private_to(_PRIVATE_GID, _OPERATOR, **lookups)  # type: ignore[arg-type]


def test_an_unknown_gid_fails_closed() -> None:
    lookups = _lookups([], [(_OPERATOR, _PRIVATE_GID)])
    assert not group_is_private_to(4242, _OPERATOR, **lookups)  # type: ignore[arg-type]


def test_the_one_action_says_it_also_sets_the_time_source() -> None:
    """D-058 adds no action; the prompt must not claim a power change when the
    operator is choosing a time source."""
    from hammunition_devctl.polkit import policy_xml

    xml = policy_xml()
    assert "time source" in xml
    assert xml.count("<action id=") == 1


def test_the_wrapper_carries_the_mark_an_uninstall_looks_for() -> None:
    """An uninstall removes the file at HELPER_PATH only when it says it is
    ours; a wrapper some other installer put there is left alone."""
    from hammunition_devctl.polkit import WRAPPER_MARK

    assert WRAPPER_MARK in wrapper_script("/usr/bin/python3", ENTRY)
    assert wrapper_script("/usr/bin/python3", ENTRY).splitlines()[1] == WRAPPER_MARK.rstrip("\n")


def test_the_one_action_says_it_also_controls_services() -> None:
    assert "service" in policy_xml()
