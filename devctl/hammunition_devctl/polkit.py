# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The privileged artefacts the helper is installed with: the wrapper and the
polkit action. D-056, moved here from the engine.

The engine's ``plan_polkit`` (whether the files on disk are current) stays
there; what is here is what the files *say* and the writability check the
helper repeats at the moment it runs as root.
"""

from __future__ import annotations

import enum
import grp
import os
import pwd
import shlex
import stat as stat_module
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ACTION_ID",
    "HELPER_PATH",
    "POLICY_PATH",
    "WRAPPER_MARK",
    "WritabilityFinding",
    "WritabilityRisk",
    "describe_refusal",
    "group_is_private_to",
    "policy_xml",
    "wrapper_script",
    "writable_by_non_root",
    "writable_including_symlink_target",
]

HELPER_PATH = "/usr/local/libexec/hammunition-devctl"
"""Where pkexec is pointed. A fixed path under the shared prefix, because a
polkit action annotates an absolute executable and a venv's path is not one
an operator's policy file should have to follow across an upgrade."""

WRAPPER_MARK = "# Installed by hammunition-tray (hammunition-devctl, D-056).\n"
"""The second line of a wrapper this repository wrote. An uninstall removes a
file at :data:`HELPER_PATH` only when it carries this line, so a wrapper some
other installer put there is left alone."""

ACTION_ID = "com.chiefgyk3d.hammunition.devctl"
POLICY_PATH = f"/usr/share/polkit-1/actions/{ACTION_ID}.policy"


def wrapper_script(interpreter: str, entry: str) -> str:
    """A small POSIX shell wrapper that execs the helper's entry point.

    Needed because polkit annotates an *absolute executable path* and the
    helper's entry point lives wherever the install put it (``/usr/share``
    for the package, ``/usr/local/lib`` for a checkout install), under an
    interpreter that may be the engine's own venv so that the ``time`` verbs
    can import it. The wrapper is the fixed thing the policy names; the
    interpreter and entry inside it are rewritten by the next install.

    ``-I`` (isolated mode) is load-bearing, not tidiness — do not remove it
    for looking like noise. ``python -m <pkg>`` inserts ``os.getcwd()`` at
    ``sys.path[0]``. ``pkexec`` normally masks that by ``chdir()``-ing to the
    target user's home before it execs the authorised program, **but
    ``pkexec --keep-cwd`` does not**, and the polkit action here pins an
    executable *path*, not an argument list — nothing stops a caller from
    adding that flag. Without ``-I``, a local user with an active session can
    ``cd`` to a directory holding their own ``hammunition_devctl/``,
    run ``pkexec --keep-cwd /usr/local/libexec/hammunition-devctl state``,
    authenticate with *their own* password (``auth_self_keep``), and have
    their module imported and run as root instead of the real one — the
    working directory is a second value crossing the privilege boundary
    that D-056 says nothing but a device name should cross. ``-I`` drops
    the working directory, ``PYTHONPATH``, ``PYTHONHOME`` and user
    site-packages from the import path while still resolving ``hammunition``
    from the interpreter's own venv; with a script argument ``sys.path[0]``
    is the script's own directory, an absolute root-owned path the entry
    inserts deliberately, never the working directory. ``cd /`` before the ``exec`` is defence in depth on top of
    it, in case a future edit ever runs something cwd-sensitive first.
    """
    return (
        "#!/bin/sh\n"
        + WRAPPER_MARK
        + "# Do not edit: the polkit action at "
        + POLICY_PATH
        + "\n# authorises this exact path, and the next install rewrites this file.\n"
        "cd /\n"
        "exec " + shlex.quote(interpreter) + " -I " + shlex.quote(entry) + ' "$@"\n'
    )


def policy_xml() -> str:
    """One action, authorising one executable. The battery applet's shape.

    ``auth_self_keep`` on an active session: the operator authenticates once
    and stays authorised for a few minutes afterwards (polkit's own manual
    page: "a brief period (e.g. five minutes)", not the rest of the
    session), because a tray switch that asks for a password on every single
    flip is a tray switch nobody uses. Inactive and remote sessions get
    ``auth_admin``, because parking someone else's GPS over SSH is not a
    thing a password prompt should make easy.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1.0/policyconfig.dtd">
<policyconfig>
  <vendor>Hammunition</vendor>
  <vendor_url>https://github.com/Renegade-Penguin/Hammunition</vendor_url>
  <action id="{ACTION_ID}">
    <description>Park or wake a radio device, set the clock's time source, control a system service Hammunition manages, or keep your services running after you log out</description>
    <message>Authentication is required to change a radio device's power state, the clock's time source, a system service Hammunition manages, or whether your services keep running after you log out</message>
    <icon_name>preferences-system-power</icon_name>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_self_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">{HELPER_PATH}</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
"""


class WritabilityRisk(enum.Enum):
    """Two different facts, deliberately not collapsed into one boolean.

    Fix round 2's ruling: the round 1 gate treated "owned by a non-root
    account" and "writable by any local account" as the same risk, and a
    devctl startup check that hard-refused on either broke the project's own
    documented install -- a venv under ``$HOME`` is *always* owned by a
    non-root account. Only one of these two facts is the actual escalation.
    """

    OWNED_BY_NON_ROOT = "owned_by_non_root"
    """The tree belongs to one specific non-root account -- the ordinary
    shape of a venv the operator's own account created. Confirmable, never
    refused outright."""

    GROUP_OR_OTHER_WRITABLE = "group_or_other_writable"
    """*Any* local account, not just the owner, can modify the tree -- the
    real escalation. Refused outright, never merely confirmed."""


@dataclass(frozen=True)
class WritabilityFinding:
    """What :func:`writable_by_non_root` found, and how serious it is."""

    path: str
    risk: WritabilityRisk
    unstatable: bool = False
    """True when ``path`` was classified :attr:`WritabilityRisk.GROUP_OR_OTHER_WRITABLE`
    only because it could not be `stat()`'d at all (fail-closed, since it
    cannot be proven safe either) -- not because it is actually writable.
    Different fact, and the message shown for it should say so (fix round
    3): "is writable by any local account" is simply false of a component
    that could not be read at all, typically a permission problem on the way
    down rather than a loose one."""


def group_is_private_to(
    gid: int,
    uid: int,
    *,
    getgrgid: Callable[[int], grp.struct_group] = grp.getgrgid,
    getpwall: Callable[[], list[pwd.struct_passwd]] = pwd.getpwall,
) -> bool:
    """True when ``gid`` is ``uid``'s user-private group: nobody is listed in
    it, and ``uid`` is the only account holding it as a primary group. Group
    write on such a group grants nobody anything the owner lacks.

    Measured on the field laptop, 2026-09-27: Parrot 7's stock session umask
    is 0002 with ``USERGROUPS_ENAB``, so every checkout and venv the operator
    makes is group-writable by exactly this kind of group, and the gate that
    read group-write as "any local account" refused the documented install.

    Fails closed: an unknown gid is not private. ``getpwall`` sees the local
    account database and whatever NSS enumerates; a directory service that
    does not enumerate could hold an account this cannot see, which is the
    residual risk the D-056 amendment records.
    """
    try:
        group = getgrgid(gid)
    except KeyError:
        return False
    if group.gr_mem:
        return False
    holders = {account.pw_uid for account in getpwall() if account.pw_gid == gid}
    return holders == {uid}


def writable_by_non_root(
    path: str | Path,
    *,
    stat_fn: Callable[[str], os.stat_result] = os.stat,
    private_group_fn: Callable[[int, int], bool] = group_is_private_to,
) -> WritabilityFinding | None:
    """The first offending component from ``path`` up to the filesystem
    root, classified by :class:`WritabilityRisk`, or ``None`` if every one of
    them is closed to non-root.

    ``stat_fn`` defaults to :func:`os.stat` and exists so this can be proven
    against a synthetic tree in a test — an unprivileged dev machine and an
    unprivileged CI run both lack any real root-owned file to test the "safe"
    answer against.

    D-056's ruling: the wrapper execs this path (or a path under the
    ``hammunition`` package directory) *as root*, through a polkit action
    that an active local session can satisfy once and keep for a few minutes
    afterwards (``auth_self_keep``, not the rest of the session). A
    component that is group- or other-writable is checked across
    the *whole* chain first, and wins over a merely non-root-owned one
    regardless of which is nearer the leaf — the real escalation must never
    be masked by a nearer, milder finding. Only once nothing in the chain is
    writable by everyone does the nearest merely-non-root-owned component
    become the (confirmable) answer. A component that cannot be stat'd at all
    is treated as the severe case (:attr:`WritabilityFinding.unstatable`):
    it cannot be proven safe either, but it is a different fact from actually
    being writable, and is reported as one.

    Group write by the owner's own user-private group (``private_group_fn``,
    :func:`group_is_private_to` by default) is not the severe class: nobody
    but the owner is in that group, so the component falls through to the
    ownership pass and is confirmable like any other operator-owned tree.
    """
    current = Path(path)
    chain = [current, *current.parents]
    stats: list[tuple[str, os.stat_result | None]] = []
    for component in chain:
        try:
            stats.append((str(component), stat_fn(str(component))))
        except OSError:
            stats.append((str(component), None))

    for name, info in stats:
        if info is None:
            return WritabilityFinding(
                name, WritabilityRisk.GROUP_OR_OTHER_WRITABLE, unstatable=True
            )
        if info.st_mode & stat_module.S_IWOTH:
            return WritabilityFinding(name, WritabilityRisk.GROUP_OR_OTHER_WRITABLE)
        if info.st_mode & stat_module.S_IWGRP and not private_group_fn(info.st_gid, info.st_uid):
            return WritabilityFinding(name, WritabilityRisk.GROUP_OR_OTHER_WRITABLE)

    for name, info in stats:
        if info is not None and info.st_uid != 0:
            return WritabilityFinding(name, WritabilityRisk.OWNED_BY_NON_ROOT)

    return None


def writable_including_symlink_target(
    path: str | Path,
    *,
    stat_fn: Callable[[str], os.stat_result] = os.stat,
    realpath_fn: Callable[[str], str] = os.path.realpath,
    private_group_fn: Callable[[int, int], bool] = group_is_private_to,
) -> WritabilityFinding | None:
    """:func:`writable_by_non_root` over ``path`` exactly as given, unioned
    with the same check over its resolved real path -- the severe class
    winning across both, exactly as it already wins within one chain.

    Fix round 3's regression: every call site checked only
    ``os.path.realpath(path)``, which resolves *through* a symlink and so
    never looks at the directory the symlink itself sits in. The wrapper
    ``exec``s (and the package is imported from) the path exactly as given,
    unresolved -- if that path is a symlink, a 0777 directory holding a
    clean symlink to an otherwise root-owned target passed the resolved-only
    check as safe, because resolution hid the one directory an attacker
    would actually use: retarget the symlink, not the root-owned file it
    used to point to. Checking only the unresolved path would just as
    wrongly miss a writable *target* the symlink already trusts (a clean
    symlink pointing at a file someone else can overwrite). Both checked;
    worse of the two wins.

    ``realpath_fn`` defaults to :func:`os.path.realpath` and, like
    ``stat_fn``, exists so this can be proven against a synthetic tree
    without touching the real filesystem at all (fix round 4: a test that
    depended on a real system path's real ownership measured the host it
    happened to run on, not the code -- true here, false inside an
    unprivileged user namespace, and would have been just as environment-
    dependent inside the seven target containers).
    """
    direct = writable_by_non_root(path, stat_fn=stat_fn, private_group_fn=private_group_fn)
    resolved = writable_by_non_root(
        realpath_fn(str(path)), stat_fn=stat_fn, private_group_fn=private_group_fn
    )
    findings = [f for f in (direct, resolved) if f is not None]
    for finding in findings:
        if finding.risk is WritabilityRisk.GROUP_OR_OTHER_WRITABLE:
            return finding
    return findings[0] if findings else None


def describe_refusal(findings: list[WritabilityFinding]) -> str:
    """One clause per finding, said accurately: "writable by any local
    account" only for a finding that really is, "could not be checked" for
    one that is refused merely because it could not be proven safe (fix
    round 3, item 6 -- the two are different facts, and were reported with
    the same, stronger sentence for both)."""
    clauses = []
    for finding in findings:
        if finding.unstatable:
            clauses.append(
                f"{finding.path} could not be checked (a stat failure), and is treated as unsafe until it can be"
            )
        else:
            clauses.append(f"{finding.path} is writable by any local account, not only its owner")
    return "; ".join(clauses)
