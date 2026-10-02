"""``radio``: state and the switches, with every command faked by argv."""

from __future__ import annotations

import json
import os

import pytest
from helper_fakes import FakeRunner

from hammunition_devctl.devctl import main
from hammunition_devctl.run import Result, set_runner

RADIO = ("nmcli", "-t", "-f", "WIFI,WWAN", "radio")
DEVICES = ("nmcli", "-t", "-f", "TYPE,DEVICE", "device", "status")
SHOW = ("bluetoothctl", "show")

BT_ON = "Controller 00:00:00:00:00:00 (public)\n\tPowered: yes\n\tBlocked: no\n"
BT_OFF = "Controller 00:00:00:00:00:00 (public)\n\tPowered: no\n\tBlocked: no\n"
BT_BLOCKED = "Controller 00:00:00:00:00:00 (public)\n\tPowered: no\n\tBlocked: yes\n"
DEVS = "ethernet:enp0s1\nwifi:wlan0\ngsm:cdc-wdm0\nloopback:lo\n"


def _answers(radio="enabled:enabled", devices=DEVS, bluetooth=BT_ON):
    return {
        RADIO: Result(0, radio + "\n"),
        DEVICES: Result(0, devices),
        SHOW: Result(0, bluetooth),
    }


def test_state_is_three_rows_in_a_fixed_order(capsys: pytest.CaptureFixture[str]) -> None:
    set_runner(FakeRunner(_answers()))
    assert main(["radio", "state"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["kind"] == "radios" and doc["version"] == 1
    assert [r["name"] for r in doc["radios"]] == ["wwan", "wifi", "bluetooth"]
    for row in doc["radios"]:
        assert tuple(row) == ("name", "present", "enabled", "method", "detail")
    wwan, wifi, bt = doc["radios"]
    assert (wwan["present"], wwan["enabled"], wwan["method"], wwan["detail"]) == (
        True,
        True,
        "nmcli",
        "cdc-wdm0",
    )
    assert (wifi["detail"], bt["method"], bt["enabled"]) == ("wlan0", "bluetoothctl", True)


def test_a_radio_that_is_off_reads_off(capsys: pytest.CaptureFixture[str]) -> None:
    set_runner(FakeRunner(_answers(radio="enabled:disabled", bluetooth=BT_OFF)))
    main(["radio", "state"])
    wwan, wifi, bt = json.loads(capsys.readouterr().out)["radios"]
    assert (wwan["enabled"], wifi["enabled"], bt["enabled"]) == (False, True, False)


def test_no_modem_is_present_false_not_a_made_up_row(capsys: pytest.CaptureFixture[str]) -> None:
    set_runner(FakeRunner(_answers(devices="wifi:wlan0\n")))
    main(["radio", "state"])
    wwan = json.loads(capsys.readouterr().out)["radios"][0]
    assert (wwan["present"], wwan["enabled"]) == (False, False)
    assert wwan["detail"]


def test_a_blocked_bluetooth_controller_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    set_runner(FakeRunner(_answers(bluetooth=BT_BLOCKED)))
    main(["radio", "state"])
    assert json.loads(capsys.readouterr().out)["radios"][2]["detail"] == "blocked by rfkill"


def test_an_absent_tool_is_present_false_and_names_the_tool(
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = Result(127, "", "command not found")
    set_runner(FakeRunner({RADIO: missing, SHOW: missing}))
    assert main(["radio", "state"]) == 0
    wwan, wifi, bt = json.loads(capsys.readouterr().out)["radios"]
    assert wwan["present"] is False and "nmcli" in wwan["detail"]
    assert wifi["present"] is False
    assert bt["present"] is False and "bluetoothctl" in bt["detail"]


def test_no_bluetooth_controller_is_not_present(capsys: pytest.CaptureFixture[str]) -> None:
    answers = _answers()
    answers[SHOW] = Result(0, "No default controller available\n")
    set_runner(FakeRunner(answers))
    main(["radio", "state"])
    assert json.loads(capsys.readouterr().out)["radios"][2]["present"] is False


def test_detail_never_carries_an_address_or_a_hostname(capsys: pytest.CaptureFixture[str]) -> None:
    answers = _answers(bluetooth=BT_ON + "\tName: somebodys-laptop\n\tAlias: somebodys-laptop\n")
    set_runner(FakeRunner(answers))
    main(["radio", "state"])
    out = capsys.readouterr().out
    assert "somebodys-laptop" not in out and "00:00:00" not in out


@pytest.mark.parametrize(
    ("radio", "command", "state"),
    [
        ("wwan", ("nmcli", "radio", "wwan"), "off"),
        ("wifi", ("nmcli", "radio", "wifi"), "off"),
        ("bluetooth", ("bluetoothctl", "power"), "off"),
        ("wwan", ("nmcli", "radio", "wwan"), "on"),
        ("wifi", ("nmcli", "radio", "wifi"), "on"),
        ("bluetooth", ("bluetoothctl", "power"), "on"),
    ],
)
def test_each_switch_is_one_fixed_argv_and_is_read_back(
    radio: str, command: tuple[str, ...], state: str
) -> None:
    start_on = state == "off"
    before = _answers(
        radio="enabled:enabled" if start_on else "disabled:disabled",
        bluetooth=BT_ON if start_on else BT_OFF,
    )
    after = _answers(
        radio="disabled:disabled" if start_on else "enabled:enabled",
        bluetooth=BT_OFF if start_on else BT_ON,
    )
    answers: dict[tuple[str, ...], Result | list[Result]] = {
        key: [before[key], after[key]] for key in before
    }
    answers[(*command, state)] = Result(0)
    runner = FakeRunner(answers)
    set_runner(runner)
    assert main(["radio", state, radio]) == 0
    assert (*command, state) in runner.calls
    # nothing but reads and the one switch ran: rfkill is never written
    assert all(call[0] in ("nmcli", "bluetoothctl") for call in runner.calls)


def test_a_switch_that_does_not_read_back_is_exit_1(capsys: pytest.CaptureFixture[str]) -> None:
    set_runner(
        FakeRunner({**_answers(), ("nmcli", "radio", "wwan", "off"): Result(0)})
    )  # still enabled afterwards
    assert main(["radio", "off", "wwan"]) == 1
    assert "unverified:" in capsys.readouterr().err


def test_a_failing_switch_is_exit_1_with_its_reason(capsys: pytest.CaptureFixture[str]) -> None:
    set_runner(
        FakeRunner({**_answers(), ("nmcli", "radio", "wwan", "off"): Result(1, "", "not authorized")})
    )
    assert main(["radio", "off", "wwan"]) == 1
    assert "not authorized" in capsys.readouterr().err


def test_a_radio_whose_tool_is_absent_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    missing = Result(127, "", "command not found")
    runner = FakeRunner({RADIO: missing, SHOW: Result(0, BT_ON)})
    set_runner(runner)
    assert main(["radio", "off", "wifi"]) == 2
    assert "not available" in capsys.readouterr().err
    assert all(call in (RADIO, SHOW) for call in runner.calls)


def test_the_switches_refuse_to_run_as_root(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    runner = FakeRunner()
    set_runner(runner)
    assert main(["radio", "off", "wwan"]) == 2
    assert "without pkexec" in capsys.readouterr().err
    assert runner.calls == []


@pytest.mark.parametrize("bad", ["rfkill", "wwan;reboot", "", "WWAN", "gps"])
def test_only_the_three_names_are_accepted(bad: str) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["radio", "off", bad])
    assert caught.value.code == 2


def test_the_command_table_is_the_whole_set_of_commands_the_switch_can_run() -> None:
    from hammunition_devctl.radio import SWITCH

    assert SWITCH == {
        "wwan": ("nmcli", "radio", "wwan"),
        "wifi": ("nmcli", "radio", "wifi"),
        "bluetooth": ("bluetoothctl", "power"),
    }
