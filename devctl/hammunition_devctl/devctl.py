# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""``hammunition-devctl`` -- the one thing here that can run as root.  D-056.

Moved from the Hammunition engine into this repository (hammunition-tray is
the device project); the verbs are in ``docs/contract.md`` and that file is the
interface. In short:

* ``park NAME``, ``wake NAME``, ``linger on|off``, ``time mode MODE`` and the
  system-scope ``services`` verbs go through pkexec and one polkit action.
* ``state``, ``time state``, ``services state``, ``radio state`` and the
  user-scope ``services`` and ``radio`` verbs never need root.

**It takes a name and derives everything else itself.** It re-reads the USB
bus and the device list in this process and computes the paths it writes; an
argv that carried a path would be a way to write anywhere on the system as
root, and an argv that carried a *plan* would be the same thing spelled
longer. A unit is never taken from argv either: it comes from a row of an
allow-list file, found by name (D-056, and the design's D7: nothing here runs
a command whose words come from input).

``time mode`` and ``time state`` belong to the engine (D-058): they run its
``hammunition.gpstime`` when it can be imported and say so when it cannot.

It never reads the operator's station config. Parking a GPS has nothing to do
with a callsign and this process has no business holding one.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
from pathlib import Path
from typing import Any

from hammunition_devctl import CONTRACT, radio, services
from hammunition_devctl.bus import match_devices, read_usb_bus
from hammunition_devctl.devices import Source, load_devices
from hammunition_devctl.engine import engine_importable_as_root
from hammunition_devctl.linger import (
    LINGER_RECORD,
    plan_linger,
    read_record,
    write_record,
)
from hammunition_devctl.polkit import (
    HELPER_PATH,
    WritabilityFinding,
    WritabilityRisk,
    describe_refusal,
    writable_including_symlink_target,
)
from hammunition_devctl.power import (
    KeptEntry,
    Parkable,
    PowerError,
    execute,
    kept_entry,
    parkable,
    plan_forget,
    plan_park,
    plan_wake,
    read_kept,
)
from hammunition_devctl.run import run

__all__ = ["attached_named", "main", "resolve", "resolve_kept"]

MODES = ("auto", "prefer-gps", "ntp-only", "gps-only")
"""The four time modes. Fixed by the contract; the engine's ``as_mode`` still
validates what it is handed."""

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNPLANNABLE = 2


def _survey() -> tuple[list[Parkable], list[tuple[str, str]]]:
    """What is parkable on this machine right now, read fresh from the bus.

    Fresh on every invocation, never cached and never taken from the caller:
    between an applet's poll and the switch being flipped a device can be
    unplugged, and a USB address can be reused by something else entirely.
    """
    found, skipped, _ = _survey_with_source()
    return found, skipped


def _survey_with_source() -> tuple[list[Parkable], list[tuple[str, str]], Source]:
    notes: list[str] = []
    entries, source = load_devices(notes)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    if source == "engine-import":
        print(
            "note: devices read from the Hammunition engine's catalog "
            "(/etc/hammunition/devctl-devices.yaml is absent; `hammunition hardware apply` writes it)",
            file=sys.stderr,
        )
    elif source == "none":
        print(
            "note: no device list: /etc/hammunition/devctl-devices.yaml is absent "
            "and the Hammunition engine is not importable",
            file=sys.stderr,
        )
    found, skipped = parkable(match_devices(read_usb_bus(), entries), entries)
    return found, skipped, source


def resolve(name: str, found: list[Parkable]) -> Parkable:
    """The one parkable device ``name`` refers to, or a refusal that says why.

    ``NAME`` or ``NAME@ADDRESS``. Two receivers of the same class are two
    parkable devices with one catalog name between them, and picking one
    silently would park whichever the bus happened to list first -- so an
    ambiguous name is refused with both addresses, and the operator says which.
    """
    wanted, _, address = name.partition("@")
    candidates = [p for p in found if p.name == wanted]
    if address:
        candidates = [p for p in candidates if p.address == address]
        if not candidates:
            raise PowerError(
                f"no parkable device {wanted!r} at address {address!r} is attached. "
                f"Attached: {_listing(found)}"
            )
    if not candidates:
        raise PowerError(
            f"{name!r} is not a parkable attached device. Parkable now: {_listing(found)}"
        )
    if len(candidates) > 1:
        addresses = ", ".join(f"{p.name}@{p.address}" for p in candidates)
        raise PowerError(
            f"{wanted!r} names {len(candidates)} attached devices and would be a "
            f"guess: {addresses}. Name one of those instead."
        )
    return candidates[0]


def _listing(found: list[Parkable]) -> str:
    if not found:
        return "nothing (no catalogued parkable device is attached)"
    return ", ".join(f"{p.name}@{p.address}" for p in sorted(found, key=lambda p: p.address))


def attached_named(name: str, found: list[Parkable]) -> bool:
    """Whether any attached parkable device answers to ``NAME`` or ``NAME@ADDRESS``.

    ``wake`` falls back to a kept entry only when this is false. When it is
    true and :func:`resolve` still refused, the refusal is about the attached
    devices -- two of them under one name -- and turning it into a forget of
    a kept entry would remove the entry and leave that device parked.
    """
    wanted, _, address = name.partition("@")
    return any(p.name == wanted and (not address or p.address == address) for p in found)


def resolve_kept(name: str, kept: list[KeptEntry]) -> KeptEntry:
    """A kept entry named ``NAME`` or ``NAME@ADDRESS``, for a device not attached."""
    wanted, _, address = name.partition("@")
    candidates = [e for e in kept if e.name == wanted and (not address or e.address == address)]
    if not candidates:
        raise PowerError(f"{name!r} is neither attached nor kept parked")
    if len(candidates) > 1:
        ports = ", ".join(f"{e.name}@{e.address}" for e in candidates)
        raise PowerError(f"{wanted!r} is kept at {len(candidates)} ports: {ports}. Name one.")
    return candidates[0]


def _needs_root(verb: str) -> int | None:
    """Exit 2 for a verb that changes the machine, run without root.

    Checked after a name has been resolved and before anything is written, so
    a refusal about the name still says why, and nothing is half done: without
    this a `linger on` run unprivileged can enable linger and then fail to
    write its record, and a later `linger off` refuses because it is not ours.
    """
    if os.geteuid() == 0:
        return None
    print(
        f"error: {verb} changes the machine and needs root; run it through pkexec "
        f"(/usr/bin/pkexec {HELPER_PATH} {verb} ...)",
        file=sys.stderr,
    )
    return EXIT_UNPLANNABLE


def _do(verb: str, name: str, *, keep: bool = True) -> int:
    found, skipped = _survey()
    for unit, why in skipped:
        print(f"note: {unit} is not parkable right now: {why}", file=sys.stderr)
    try:
        try:
            target = resolve(name, found)
        except PowerError:
            if verb != "wake" or attached_named(name, found):
                raise
            plan = plan_forget(resolve_kept(name, read_kept()))
        else:
            plan = plan_park(target, keep=keep) if verb == "park" else plan_wake(target)
    except PowerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNPLANNABLE
    refused = _needs_root(verb)
    if refused is not None:
        return refused
    problems = execute(plan)
    for problem in problems:
        print(f"unverified: {problem}", file=sys.stderr)
    return EXIT_FAILED if problems else EXIT_OK


def _state(*, with_source: bool = False) -> int:
    source: Source = "file"
    if with_source:
        found, skipped, source = _survey_with_source()
    else:
        found, skipped = _survey()
    for unit, why in skipped:
        print(f"note: {unit} is not parkable right now: {why}", file=sys.stderr)

    try:
        kept = read_kept()
    except (OSError, PowerError) as exc:
        print(f"note: kept-off entries unreadable: {exc}", file=sys.stderr)
        kept = []

    def is_kept(p: Parkable) -> bool:
        try:
            mine = kept_entry(p)
        except PowerError:
            return False
        return any(e.same_device(mine) for e in kept)

    rows: list[dict[str, object]] = [
        {
            "name": p.name,
            "summary": p.summary,
            "address": p.address,
            "identifier": p.identifier,
            "method": p.method,
            "parked": p.parked,
            "kept": is_kept(p),
            "attached": True,
        }
        for p in sorted(found, key=lambda p: (p.name, p.address))
    ]
    attached = {(p.address, p.identifier.lower()) for p in found}
    for e in sorted(kept, key=lambda e: (e.name, e.address)):
        if (e.address, f"{e.vendor}:{e.product}") in attached:
            continue
        rows.append(
            {
                "name": e.name,
                "summary": "",
                "address": e.address,
                "identifier": f"{e.vendor}:{e.product}",
                "method": "usb_deauthorize",
                "parked": None,
                "kept": True,
                "attached": False,
            }
        )
    # Always a JSON array, including when it is empty: the applet parses this
    # every five seconds and a human sentence here is a parse error every five
    # seconds. `--with-source` is the one opt-in to an object, so the bytes a
    # caller already parses never change.
    if with_source:
        print(json.dumps({"kind": "state", "version": 1, "source": source, "devices": rows}))
    else:
        print(json.dumps(rows))
    return EXIT_OK


_NO_ENGINE = (
    "error: the Hammunition engine is not installed (hammunition.gpstime could not "
    "be imported by this helper's interpreter), so there is no GPS time to {what}. "
    "Install Hammunition, or reinstall this helper with --interpreter pointing at "
    "the engine's Python."
)


def _gpstime() -> Any | None:
    """The engine's ``gpstime`` package, or None when this interpreter has no
    engine, or has one root may not import."""
    if not engine_importable_as_root():
        return None
    try:
        import hammunition.gpstime.apply as apply  # type: ignore[import-not-found,unused-ignore]
        import hammunition.gpstime.mode as mode  # type: ignore[import-not-found,unused-ignore]
        import hammunition.gpstime.state as state  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        return None
    return (apply, mode, state)


def _time_state() -> int:
    """Unprivileged, like ``state``: the tray polls it without pkexec."""
    engine = _gpstime()
    if engine is None:
        print(_NO_ENGINE.format(what="read"), file=sys.stderr)
        return EXIT_UNPLANNABLE
    _, _, state = engine
    found, skipped = _survey()
    for unit, why in skipped:
        print(f"note: {unit} is not parkable right now: {why}", file=sys.stderr)
    # Always one JSON object: the applet parses this on every poll.
    print(json.dumps(state.gather(gps=state.gps_from(found)).as_json()))
    return EXIT_OK


def caller_uid() -> int:
    """The account to act on: the one polkit reports, never an argv.

    pkexec sets ``PKEXEC_UID`` to the uid that invoked it; under ``sudo``
    ``SUDO_UID`` is the equivalent. A direct unprivileged run acts on itself.
    A name is never taken from an argument — that would let a caller linger
    somebody else's account (D-073 §5a).
    """
    for var in ("PKEXEC_UID", "SUDO_UID"):
        value = os.environ.get(var)
        if value and value.isdigit():
            return int(value)
    return os.getuid()


def _linger_is_on(username: str) -> bool:
    result = run((services.LOGINCTL, "show-user", username, "--property=Linger", "--value"))
    return result.ok and result.stdout.strip().lower() in ("yes", "1", "true")


def _linger(on: bool) -> int:
    refused = _needs_root("linger")
    if refused is not None:
        return refused
    uid = caller_uid()
    try:
        username = pwd.getpwuid(uid).pw_name
    except KeyError:
        print(f"error: no account for uid {uid}", file=sys.stderr)
        return EXIT_UNPLANNABLE
    plan = plan_linger(
        on=on,
        uid=uid,
        username=username,
        already_on=_linger_is_on(username),
        existing=_read_record(),
    )
    if plan.command is not None:
        result = run(plan.command)
        if not result.ok:
            print(f"error: {result.stderr.strip() or 'loginctl failed'}", file=sys.stderr)
            return EXIT_FAILED
    if plan.remove_record:
        LINGER_RECORD.unlink(missing_ok=True)
    elif plan.record is not None:
        write_record(plan.record)
    print(plan.note)
    return EXIT_OK


def _time_mode(mode: str) -> int:
    refused = _needs_root("time mode")
    if refused is not None:
        return refused
    engine = _gpstime()
    if engine is None:
        print(_NO_ENGINE.format(what="set"), file=sys.stderr)
        return EXIT_UNPLANNABLE
    apply, modes, _ = engine
    try:
        problems = apply.apply_mode(modes.as_mode(mode))
    except modes.TimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNPLANNABLE
    for problem in problems:
        print(f"unverified: {problem}", file=sys.stderr)
    return EXIT_FAILED if problems else EXIT_OK


def _read_record() -> Any:
    """The linger record, its problems said on stderr like every other note."""
    notes: list[str] = []
    record = read_record(notes=notes)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    return record


def _services_state() -> int:
    notes: list[str] = []
    rows = services.load_services(notes)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    uid = caller_uid()
    record = _read_record()
    ours = bool(record and record.uid == uid and record.enabled_by_us)
    print(json.dumps(services.state_document(rows, services.linger_document(uid, ours))))
    return EXIT_OK


def _services_control(verb: str, name: str) -> int:
    notes: list[str] = []
    rows = services.load_services(notes)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    try:
        problems = services.control(verb, name, rows)
    except services.ServiceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_UNPLANNABLE
    for problem in problems:
        print(f"unverified: {problem}", file=sys.stderr)
    return EXIT_FAILED if problems else EXIT_OK


def _radio_state() -> int:
    print(json.dumps(radio.read_radios()))
    return EXIT_OK


def _radio_switch(state: str, name: str) -> int:
    if os.geteuid() == 0:
        print(
            "error: radio switches are your own session's; run this without pkexec",
            file=sys.stderr,
        )
        return EXIT_UNPLANNABLE
    code, problems = radio.switch(state, name)
    for problem in problems:
        print(f"{'error' if code == EXIT_UNPLANNABLE else 'unverified'}: {problem}", file=sys.stderr)
    return code


def _runtime_writability_findings() -> tuple[WritabilityFinding | None, WritabilityFinding | None]:
    """The same D-056 check ``hardware apply`` runs before install, run again
    here, at the moment this process is actually about to act as root.

    Gated on really being root by the caller: an unprivileged invocation
    (every test in this repository, and a developer running this module
    directly to see what it prints) reading its own writable checkout is not
    the privilege escalation the check exists to catch -- only pkexec's
    elevated process is. A tree that was safe at apply time can still have
    become writable since (a package reinstalled somewhere looser, a
    permission loosened by hand), so this is not redundant with the
    apply-time gate; it is the defence for the gap between "we checked" and
    "we are now running".

    Both paths passed unresolved, deliberately: :func:`writable_including_symlink_target`
    checks the given path *and* its resolved real path, and resolving here
    first would throw away exactly the symlink-holding directory that exists
    to catch (fix round 3).
    """
    interpreter = writable_including_symlink_target(sys.executable)
    package = writable_including_symlink_target(str(Path(os.path.abspath(__file__)).parent))
    return interpreter, package


def _refuse_or_warn_if_unsafe() -> int | None:
    """Returns an exit code this process should return immediately, or
    ``None`` to continue. Only called once the caller has confirmed this
    process is really running as root.

    Fix round 2: round 1 refused outright on *either* fact, which broke the
    project's own documented install -- a venv under `$HOME` is always
    owned by one specific non-root account, never by root, so the check
    fired on every single privileged invocation in the worktree the review
    measured. Only a component writable by *any* local account (not just its
    owner) is the real escalation and gets refused; a component merely owned
    by one non-root account is disclosed with a warning and the process
    proceeds, the same distinction `hardware apply` makes at install time.
    """
    interpreter, package = _runtime_writability_findings()
    refusing = [
        f
        for f in (interpreter, package)
        if f is not None and f.risk is WritabilityRisk.GROUP_OR_OTHER_WRITABLE
    ]
    if refusing:
        print(
            f"error: refusing to run: {describe_refusal(refusing)}, and this process "
            f"is running as root through it. Fix it, then re-run "
            f"`hammunition hardware apply`.",
            file=sys.stderr,
        )
        return EXIT_UNPLANNABLE

    warnings = [
        f
        for f in (interpreter, package)
        if f is not None and f.risk is WritabilityRisk.OWNED_BY_NON_ROOT
    ]
    for finding in warnings:
        print(
            f"warning: {finding.path} is owned by a non-root account, and this "
            f"process is running as root through it. This is the documented "
            f"install (a venv under $HOME); if that account should not be trusted "
            f"with root, fix its ownership.",
            file=sys.stderr,
        )
    return None


def main(argv: list[str] | None = None) -> int:
    if os.geteuid() == 0:
        exit_code = _refuse_or_warn_if_unsafe()
        if exit_code is not None:
            return exit_code

    parser = argparse.ArgumentParser(
        prog="hammunition-devctl",
        description=(
            "Park and wake catalogued devices, control the services and radios "
            "Hammunition manages. The changing verbs that need root run through "
            "polkit; called by `hammunition hardware`, by the generated menu "
            "entries, and by the tray. docs/contract.md is the interface."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hammunition-devctl contract {CONTRACT}",
    )
    sub = parser.add_subparsers(dest="verb", required=True)
    for verb_name, help_text in (
        ("park", "detach a device and let its port suspend"),
        ("wake", "bring a parked device back"),
    ):
        p = sub.add_parser(verb_name, help=help_text)
        p.add_argument(
            "name",
            metavar="NAME",
            help="catalog name, or NAME@ADDRESS when two of a kind are attached",
        )
        if verb_name == "park":
            p.add_argument(
                "--until-reboot",
                action="store_true",
                help="park now without keeping it parked across reboots",
            )
    p_state = sub.add_parser(
        "state", help="JSON: every parkable device, attached or kept, and whether it is parked"
    )
    p_state.add_argument(
        "--with-source",
        action="store_true",
        help="print an object that also says where the device list came from",
    )
    p_services = sub.add_parser(
        "services", help="the services Hammunition manages: state, start, stop, enable, disable"
    )
    services_sub = p_services.add_subparsers(dest="services_verb", required=True)
    services_sub.add_parser("state", help="JSON: every managed service and linger")
    for verb_name in services.VERBS:
        p_svc = services_sub.add_parser(verb_name, help=f"{verb_name} a managed service")
        p_svc.add_argument("name", metavar="NAME", help="a name from `services state`")
    p_radio = sub.add_parser("radio", help="the radios: state, on, off")
    radio_sub = p_radio.add_subparsers(dest="radio_verb", required=True)
    radio_sub.add_parser("state", help="JSON: wwan, wifi and bluetooth")
    for state_name in ("on", "off"):
        p_rad = radio_sub.add_parser(state_name, help=f"turn a radio {state_name}")
        p_rad.add_argument("name", choices=radio.NAMES)
    p_linger = sub.add_parser(
        "linger", help="keep your user services running after you log out (D-073 §5a)"
    )
    p_linger.add_argument("state", choices=("on", "off"))
    p_time = sub.add_parser("time", help="GPS time (D-058): the mode, and what the clock follows")
    time_sub = p_time.add_subparsers(dest="time_verb", required=True)
    p_time_mode = time_sub.add_parser(
        "mode", help="set the time mode: writes three files and restarts ntpsec"
    )
    p_time_mode.add_argument("mode", choices=MODES)
    time_sub.add_parser("state", help="JSON: the mode, the GPS, and what the clock follows")

    args = parser.parse_args(argv)
    if args.verb == "time":
        if args.time_verb == "state":
            return _time_state()
        return _time_mode(args.mode)
    if args.verb == "state":
        return _state(with_source=args.with_source)
    if args.verb == "services":
        if args.services_verb == "state":
            return _services_state()
        return _services_control(args.services_verb, args.name)
    if args.verb == "radio":
        if args.radio_verb == "state":
            return _radio_state()
        return _radio_switch(args.radio_verb, args.name)
    if args.verb == "linger":
        return _linger(args.state == "on")
    verb: str = args.verb
    return _do(verb, args.name, keep=not getattr(args, "until_reboot", False))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
