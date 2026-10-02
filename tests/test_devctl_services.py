"""``services``: the allow-list files, the state document, and the four verbs.

The contract is docs/contract.md. Every command is a fake keyed by argv; no
test runs a real systemctl.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from helper_fakes import FakeRunner, show, write_services

from hammunition_devctl import datafiles
from hammunition_devctl.devctl import main
from hammunition_devctl.run import Result, set_runner

KEYS = ("name", "unit", "scope", "description", "active", "enabled", "root")


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    system = tmp_path / "etc" / "devctl-services.yaml"
    user = tmp_path / "cfg" / "hammunition" / "devctl-services.yaml"
    monkeypatch.setattr(datafiles, "SERVICES_FILE", system)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return system, user


def _as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``as_root`` fixture of conftest.py, for tests that take only
    ``monkeypatch``."""
    from hammunition_devctl import devctl

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(datafiles, "untrusted_reason", lambda info, parent: None)
    monkeypatch.setattr(devctl, "_refuse_or_warn_if_unsafe", lambda: None)


def _linger(state: str = "no") -> dict[tuple[str, ...], Result]:
    import pwd

    name = pwd.getpwuid(os.getuid()).pw_name
    return {("/usr/bin/loginctl", "show-user", name, "--property=Linger", "--value"): Result(0, state + "\n")}


def test_state_lists_system_then_user_rows_with_every_key(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    system, user = files
    write_services(system, "system", [("gpsd", "gpsd.socket", "the GPS daemon")])
    write_services(user, "user", [("gps-tether", "hammunition-gps-tether.service", "the tether")])
    answers = dict(_linger())
    for argv, result in (
        show("gpsd.socket", enabled="enabled"),
        show("hammunition-gps-tether.service", active="inactive", enabled="disabled", user=True),
    ):
        answers[argv] = result
    set_runner(FakeRunner(answers))
    assert main(["services", "state"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["kind"] == "services" and doc["version"] == 1
    assert [tuple(r) for r in doc["services"]] == [KEYS, KEYS]
    gpsd, tether = doc["services"]
    assert (gpsd["name"], gpsd["scope"], gpsd["root"], gpsd["active"]) == ("gpsd", "system", True, "active")
    assert (tether["scope"], tether["root"], tether["enabled"]) == ("user", False, "disabled")
    assert doc["linger"] == {"state": "off", "ours": False}


def test_a_unit_that_is_not_installed_is_listed_as_not_found_never_omitted(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    system, _ = files
    write_services(system, "system", [("gps-resume", "hammunition-gps-resume.service", "resume")])
    argv, _ = show("hammunition-gps-resume.service")
    answers = dict(_linger())
    answers.update([show("hammunition-gps-resume.service", load="not-found")])
    set_runner(FakeRunner(answers))
    assert main(["services", "state"]) == 0
    (row,) = json.loads(capsys.readouterr().out)["services"]
    assert (row["active"], row["enabled"]) == ("inactive", "not-found")


@pytest.mark.parametrize(
    ("unit_file_state", "folded"),
    [
        ("enabled", "enabled"),
        ("enabled-runtime", "enabled"),
        ("disabled", "disabled"),
        ("static", "static"),
        ("indirect", "static"),
        ("generated", "static"),
        ("masked", "unknown"),
        ("masked-runtime", "unknown"),
        ("linked", "unknown"),
        ("linked-runtime", "unknown"),
        ("bad", "unknown"),
        ("", "unknown"),
    ],
)
def test_unit_file_states_fold_into_the_contract_words(
    files: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    unit_file_state: str,
    folded: str,
) -> None:
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    answers = dict(_linger())
    answers.update([show("ntpsec.service", enabled=unit_file_state)])
    set_runner(FakeRunner(answers))
    main(["services", "state"])
    (row,) = json.loads(capsys.readouterr().out)["services"]
    assert row["enabled"] == folded


def test_an_active_state_outside_the_vocabulary_is_unknown(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    answers = dict(_linger())
    answers.update([show("ntpsec.service", active="deactivating")])
    set_runner(FakeRunner(answers))
    main(["services", "state"])
    assert json.loads(capsys.readouterr().out)["services"][0]["active"] == "unknown"


def test_no_files_is_an_empty_list_and_still_one_document(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    set_runner(FakeRunner(_linger()))
    assert main(["services", "state"]) == 0
    assert json.loads(capsys.readouterr().out)["services"] == []


def test_linger_is_unknown_when_logind_cannot_say(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    import pwd

    name = pwd.getpwuid(os.getuid()).pw_name
    set_runner(
        FakeRunner(
            {("/usr/bin/loginctl", "show-user", name, "--property=Linger", "--value"): Result(1, "", "no")}
        )
    )
    main(["services", "state"])
    assert json.loads(capsys.readouterr().out)["linger"]["state"] == "unknown"


def test_a_user_row_may_not_shadow_a_system_name(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    system, user = files
    write_services(system, "system", [("gpsd", "gpsd.socket", "system gpsd")])
    write_services(user, "user", [("gpsd", "evil.service", "user gpsd")])
    answers = dict(_linger())
    answers.update([show("gpsd.socket")])
    set_runner(FakeRunner(answers))
    main(["services", "state"])
    captured = capsys.readouterr()
    rows = json.loads(captured.out)["services"]
    assert [r["unit"] for r in rows] == ["gpsd.socket"]
    assert "shares a name" in captured.err


@pytest.mark.parametrize(
    "unit",
    ["--now", "-x.service", "a b.service", "x.service;reboot", "../x.service", "x.exe", "$(id).service", ""],
)
def test_a_unit_that_could_be_an_option_or_a_command_is_dropped(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str], unit: str
) -> None:
    system, _ = files
    system.parent.mkdir(parents=True)
    system.write_text(
        f"version: 1\nservices:\n  - name: x\n    unit: '{unit}'\n    scope: system\n    description: d\n"
    )
    set_runner(FakeRunner(_linger()))
    main(["services", "state"])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["services"] == []
    assert "dropped" in captured.err


def test_a_row_whose_scope_disagrees_with_its_file_is_dropped(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """A user-writable file must not be able to declare a system service."""
    _, user = files
    write_services(user, "system", [("gpsd", "gpsd.socket", "claims system")])
    set_runner(FakeRunner(_linger()))
    main(["services", "state"])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["services"] == []
    assert "scope" in captured.err


def test_a_broken_file_is_a_note_and_empty_never_half_read(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    system, _ = files
    system.parent.mkdir(parents=True)
    system.write_text("version: 1\nservices: [ {name: gpsd, unit: gpsd.socket\n")
    set_runner(FakeRunner(_linger()))
    assert main(["services", "state"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["services"] == []
    assert "not valid YAML" in captured.err


def test_a_file_that_is_not_version_1_is_refused(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    system, _ = files
    system.parent.mkdir(parents=True)
    system.write_text("version: 2\nservices: []\n")
    set_runner(FakeRunner(_linger()))
    main(["services", "state"])
    assert "not 1" in capsys.readouterr().err


# --- the four verbs -----------------------------------------------------------


def test_a_user_verb_runs_systemctl_user_with_the_unit_from_the_row(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, user = files
    write_services(user, "user", [("gps-tether", "hammunition-gps-tether.service", "the tether")])
    before = show("hammunition-gps-tether.service", active="inactive", user=True)
    after = show("hammunition-gps-tether.service", active="active", user=True)
    runner = FakeRunner(
        {
            before[0]: [before[1], after[1]],
            ("/usr/bin/systemctl", "--user", "start", "hammunition-gps-tether.service"): Result(0),
        }
    )
    set_runner(runner)
    assert main(["services", "start", "gps-tether"]) == 0
    assert ("/usr/bin/systemctl", "--user", "start", "hammunition-gps-tether.service") in runner.calls
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("verb", "before_state", "after_state"),
    [
        ("start", {"active": "inactive"}, {"active": "active"}),
        ("stop", {"active": "active"}, {"active": "inactive"}),
        ("enable", {"enabled": "disabled"}, {"enabled": "enabled"}),
        ("disable", {"enabled": "enabled"}, {"enabled": "disabled"}),
    ],
)
def test_each_verb_is_its_own_systemctl_word_and_is_read_back(
    files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    verb: str,
    before_state: dict[str, str],
    after_state: dict[str, str],
) -> None:
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    _as_root(monkeypatch)
    pre = show("ntpsec.service", **before_state)
    post = show("ntpsec.service", **after_state)
    runner = FakeRunner(
        {pre[0]: [pre[1], post[1]], ("/usr/bin/systemctl", verb, "ntpsec.service"): Result(0)}
    )
    set_runner(runner)
    assert main(["services", verb, "time"]) == 0


@pytest.mark.parametrize(
    ("active", "expected"),
    [("activating", 1), ("inactive", 0), ("failed", 0)],
)
def test_stop_read_back_requires_inactive_or_failed_not_activating(
    files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    active: str,
    expected: int,
) -> None:
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    _as_root(monkeypatch)
    before = show("ntpsec.service", active="active")
    after = show("ntpsec.service", active=active)
    set_runner(
        FakeRunner(
            {
                before[0]: [before[1], after[1]],
                ("/usr/bin/systemctl", "stop", "ntpsec.service"): Result(0),
            }
        )
    )
    assert main(["services", "stop", "time"]) == expected
    if active == "activating":
        assert "unverified:" in capsys.readouterr().err
    else:
        assert capsys.readouterr().err == ""


def test_contract_documents_activating_as_not_stopped() -> None:
    contract = Path(__file__).resolve().parents[1] / "docs" / "contract.md"
    assert "counts as not stopped" in contract.read_text()


def test_a_change_that_does_not_read_back_is_exit_1(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D-031: systemctl exiting 0 is not evidence the unit started."""
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    _as_root(monkeypatch)
    still_off = show("ntpsec.service", active="inactive")
    set_runner(
        FakeRunner(
            {still_off[0]: still_off[1], ("/usr/bin/systemctl", "start", "ntpsec.service"): Result(0)}
        )
    )
    assert main(["services", "start", "time"]) == 1
    assert "unverified:" in capsys.readouterr().err


def test_a_failing_systemctl_is_exit_1_with_its_reason(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    _as_root(monkeypatch)
    off = show("ntpsec.service", active="inactive")
    set_runner(
        FakeRunner(
            {
                off[0]: off[1],
                ("/usr/bin/systemctl", "start", "ntpsec.service"): Result(1, "", "Job failed"),
            }
        )
    )
    assert main(["services", "start", "time"]) == 1
    assert "Job failed" in capsys.readouterr().err


def test_a_name_in_no_file_is_refused_by_name_and_runs_nothing(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    runner = FakeRunner()
    set_runner(runner)
    assert main(["services", "start", "sshd"]) == 2
    assert "'sshd' is not a service Hammunition controls" in capsys.readouterr().err
    assert runner.calls == []


def test_a_unit_name_typed_as_the_name_is_not_a_name(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The unit comes from the row. Giving the unit itself finds no row."""
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    runner = FakeRunner()
    set_runner(runner)
    assert main(["services", "stop", "ntpsec.service"]) == 2
    assert runner.calls == []


def test_a_system_service_without_root_is_refused_before_systemctl(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    system, _ = files
    write_services(system, "system", [("time", "ntpsec.service", "the clock")])
    runner = FakeRunner()
    set_runner(runner)
    assert main(["services", "stop", "time"]) == 2
    assert "pkexec" in capsys.readouterr().err
    assert runner.calls == []


def test_a_user_service_as_root_is_refused_and_the_user_file_is_not_read(
    files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """What root controls must not be chosen by the account asking: under root
    the user file is not read at all, so its name is simply not a service."""
    _, user = files
    write_services(user, "user", [("gps-tether", "hammunition-gps-tether.service", "the tether")])
    _as_root(monkeypatch)
    runner = FakeRunner()
    set_runner(runner)
    assert main(["services", "start", "gps-tether"]) == 2
    assert "not a service Hammunition controls" in capsys.readouterr().err
    assert runner.calls == []


def test_a_unit_that_is_not_installed_is_refused_exit_2(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, user = files
    write_services(user, "user", [("rig", "hammunition-rigctld.service", "rigctld")])
    missing = show("hammunition-rigctld.service", load="not-found", user=True)
    runner = FakeRunner({missing[0]: missing[1]})
    set_runner(runner)
    assert main(["services", "start", "rig"]) == 2
    assert "is not installed" in capsys.readouterr().err
    assert runner.calls == [missing[0]]


def test_an_unknown_services_verb_is_an_argparse_refusal() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["services", "restart", "time"])
    assert caught.value.code == 2


def test_no_unit_ever_reaches_a_command_from_argv(
    files: tuple[Path, Path],
) -> None:
    """D7: every word of every command is a fixed word, the row's unit, or a
    username from the account database. Exercise each verb and check that the
    only argv-supplied word (the service NAME) never appears in a command."""
    _, user = files
    write_services(user, "user", [("zzname", "hammunition-x.service", "x")])
    pre = show("hammunition-x.service", active="inactive", user=True)
    post = show("hammunition-x.service", active="active", user=True)
    runner = FakeRunner(
        {
            pre[0]: [pre[1], post[1]],
            ("/usr/bin/systemctl", "--user", "start", "hammunition-x.service"): Result(0),
        }
    )
    set_runner(runner)
    assert main(["services", "start", "zzname"]) == 0
    assert all("zzname" not in word for call in runner.calls for word in call)
