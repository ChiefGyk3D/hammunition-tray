"""The verbs the engine's helper already had answer exactly as they did.

The Plasma applet and the Qt tray were written against the engine's
``hammunition-devctl`` and their own tests (`FakeRunner` in test_qt_smoke.py,
`time_fixtures.py`) pin what they send and what they parse. This file pins the
other side: the argv the helper still accepts and the bytes it prints, so a
move of the code cannot change what a front end sees. Where it asserts a
literal, the literal was captured from the engine's helper.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from hammunition_devctl import devctl
from hammunition_devctl.devctl import main
from hammunition_devctl.power import KeptEntry, Parkable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _parkable(address: str = "1-4", parked: bool = False) -> Parkable:
    return Parkable(
        "gnss-ublox",
        "u-blox GNSS receiver",
        "usb_deauthorize",
        (),
        f"/sys/bus/usb/devices/{address}",
        "1546:01a8",
        parked,
    )


def test_state_bytes_are_the_engine_s_array_with_the_engine_s_key_order(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    kept = KeptEntry("gnss-ublox", "1-9", "1546", "01a8")
    monkeypatch.setattr(devctl, "_survey", lambda: ([_parkable(parked=True)], []))
    monkeypatch.setattr(devctl, "read_kept", lambda: [kept])
    assert main(["state"]) == 0
    assert capsys.readouterr().out == (
        '[{"name": "gnss-ublox", "summary": "u-blox GNSS receiver", "address": "1-4", '
        '"identifier": "1546:01a8", "method": "usb_deauthorize", "parked": true, '
        '"kept": false, "attached": true}, '
        '{"name": "gnss-ublox", "summary": "", "address": "1-9", "identifier": "1546:01a8", '
        '"method": "usb_deauthorize", "parked": null, "kept": true, "attached": false}]\n'
    )


def test_an_empty_state_is_the_two_characters_the_applet_parses(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(devctl, "_survey", lambda: ([], []))
    monkeypatch.setattr(devctl, "read_kept", lambda: [])
    assert main(["state"]) == 0
    assert capsys.readouterr().out == "[]\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["state"],
        ["park", "gnss-ublox"],
        ["park", "gnss-ublox@1-4"],
        ["park", "gnss-ublox@1-4", "--until-reboot"],
        ["wake", "gnss-ublox"],
        ["wake", "gnss-ublox@3-1.2.4"],
        ["linger", "on"],
        ["linger", "off"],
        ["time", "state"],
        ["time", "mode", "auto"],
        ["time", "mode", "prefer-gps"],
        ["time", "mode", "ntp-only"],
        ["time", "mode", "gps-only"],
    ],
)
def test_every_argv_the_engine_s_helper_accepted_still_parses(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """argparse is reached before anything acts: stub every action and check
    the argv is accepted rather than refused with exit 2 by the parser."""
    for name in ("_state", "_do", "_linger", "_time_state", "_time_mode"):
        monkeypatch.setattr(devctl, name, lambda *a, **k: 0)
    assert main(argv) == 0


@pytest.mark.parametrize(
    "argv",
    [["park"], ["wake"], ["linger", "maybe"], ["time", "mode", "gps"], ["time"], []],
)
def test_what_the_engine_s_helper_refused_is_still_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == 2


def test_the_exit_codes_are_the_engine_s() -> None:
    assert (devctl.EXIT_OK, devctl.EXIT_FAILED, devctl.EXIT_UNPLANNABLE) == (0, 1, 2)


def _stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("_state", "_do", "_linger", "_time_state", "_time_mode"):
        monkeypatch.setattr(devctl, name, lambda *a, **k: 0)


def test_every_argv_the_qt_tray_builds_is_accepted_by_this_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the tray's argv with the tray's own code and parse each with the
    helper's parser: a front end and the helper cannot drift apart without this
    going red."""
    sys.path.insert(0, str(ROOT / "qt"))
    from hammunition_tray_qt import logic, timelogic

    _stubbed(monkeypatch)
    device = logic.Device("gnss-ublox", "1-4", "u-blox GNSS receiver", False, False, True)
    built = [
        logic.poll_argv(),
        logic.time_poll_argv(),
        logic.action_argv("park", device),
        logic.action_argv("wake", device),
        *(logic.time_mode_argv(mode) for mode in timelogic.MODES),
    ]
    assert len(built) >= 6
    for program, args in built:
        words = list(args)
        if program == logic.PKEXEC:
            assert words[0] == logic.HELPER
            words = words[1:]
        else:
            assert program == logic.HELPER
        assert main(words) == 0, words


def test_the_applet_names_only_verbs_the_helper_still_has() -> None:
    qml = (ROOT / "plasmoid/package/contents/ui/main.qml").read_text()
    verbs = set(re.findall(r'helper \+ " ([a-z]+)', qml))
    verbs |= set(re.findall(r'\? "(park|wake) "', qml))
    assert {"state", "time", "park", "wake"} <= verbs
    assert verbs <= {"state", "time", "park", "wake", "linger"}


def test_version_prints_the_contract_number_and_the_contract_file_agrees(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from hammunition_devctl import CONTRACT

    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"hammunition-devctl contract {CONTRACT}\n"
    text = (ROOT / "docs" / "contract.md").read_text()
    assert f"# The device helper's contract (version {CONTRACT})" in text
    assert f"hammunition-devctl contract {CONTRACT}" in text


def test_the_contract_file_documents_every_verb_the_parser_has() -> None:
    text = (ROOT / "docs" / "contract.md").read_text()
    for verb in (
        "state --with-source",
        "park NAME",
        "wake NAME",
        "linger on|off",
        "time mode",
        "time state",
        "services state",
        "services start|stop|enable|disable",
        "radio state",
        "radio on|off",
        "--version",
    ):
        assert verb in text, verb
