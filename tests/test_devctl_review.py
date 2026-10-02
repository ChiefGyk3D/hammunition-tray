"""Findings from the review of the helper's move, each pinned.

* the engine-import fallback survives the engine's ``SystemExit``;
* the engine is never imported as root from a tree anyone can write;
* verbs that change the machine refuse without root, before any side effect;
* a damaged linger record never stops ``services state`` printing its document;
* the helper's own scripts and the .deb do not overwrite each other's files.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from hammunition_devctl import devctl, devices, linger, power
from hammunition_devctl.devctl import main
from hammunition_devctl.polkit import WritabilityFinding, WritabilityRisk

ROOT = Path(__file__).resolve().parent.parent


# --- the engine-import fallback ----------------------------------------------


def _fake_engine(monkeypatch: pytest.MonkeyPatch, find_catalog, load_hardware) -> None:
    """Install stand-ins for the two engine modules `_from_engine` imports."""
    for name in ("hammunition", "hammunition.cli", "hammunition.manifest"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    main_mod = types.ModuleType("hammunition.cli.main")
    main_mod.find_catalog = find_catalog  # type: ignore[attr-defined]
    load_mod = types.ModuleType("hammunition.manifest.load")
    load_mod.load_hardware = load_hardware  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hammunition.cli.main", main_mod)
    monkeypatch.setitem(sys.modules, "hammunition.manifest.load", load_mod)


@pytest.mark.real_engine_import
def test_the_engines_system_exit_is_a_note_not_the_end_of_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`find_catalog` raises SystemExit when an installed wheel has no checkout
    beside it. SystemExit is not an Exception: caught as one it ends `state`,
    `park` and `time state` with exit 1 instead of source 'none'."""

    def no_catalog(_: object) -> Path:
        raise SystemExit("does not look like a catalog")

    _fake_engine(monkeypatch, no_catalog, lambda path: ({}, {}))
    notes: list[str] = []
    assert devices._from_engine(notes) is None
    assert any("does not look like a catalog" in n for n in notes)


@pytest.mark.real_engine_import
def test_main_state_still_prints_an_array_when_the_engine_has_no_catalog(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_catalog(_: object) -> Path:
        raise SystemExit("nope")

    _fake_engine(monkeypatch, no_catalog, lambda path: ({}, {}))
    monkeypatch.setattr(devctl, "read_usb_bus", lambda: [])
    monkeypatch.setattr(devctl, "read_kept", lambda: [])
    assert main(["state"]) == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.real_engine_import
def test_the_engine_import_builds_the_same_entries_the_file_would(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parity of the two sources: what the engine's catalog says is parkable,
    read through the import, equals the entries `devctl-devices.yaml` carries
    for the same catalog (confirmed ids only; product string only for a shared
    identifier)."""
    uid = SimpleNamespace
    gps = uid(
        summary="USB GNSS receivers",
        power_control=uid(method="usb_deauthorize", quiet=[]),
        usb_ids=[
            uid(vendor="1546", product="01A8", product_string=None, confirmed=True, ambiguity=None),
            uid(vendor="0403", product="6001", product_string="FT232R USB UART", confirmed=True, ambiguity="shared"),
            uid(vendor="dead", product="beef", product_string=None, confirmed=False, ambiguity=None),
        ],
    )
    unparkable = uid(summary="x", power_control=None, usb_ids=[])
    _fake_engine(
        monkeypatch,
        lambda _: Path("/nonexistent"),
        lambda path: ({"gps-receiver": gps}, {"hackrf": unparkable}),
    )
    got = devices._from_engine([])
    assert got == {
        "gps-receiver": devices.DeviceEntry(
            "gps-receiver",
            "USB GNSS receivers",
            "usb_deauthorize",
            (),
            (
                devices.UsbId("1546", "01a8", None),
                devices.UsbId("0403", "6001", "FT232R USB UART"),
            ),
        )
    }


# --- the engine is not imported as root from a tree anyone can write -----------


def test_unprivileged_the_engine_is_always_importable() -> None:
    assert devctl.engine_importable_as_root() is True


def test_root_refuses_to_import_an_engine_any_account_can_write(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(devctl, "_engine_dir", lambda: "/home/op/src/hammunition")
    monkeypatch.setattr(
        devctl,
        "writable_including_symlink_target",
        lambda path: WritabilityFinding(path, WritabilityRisk.GROUP_OR_OTHER_WRITABLE),
    )
    assert devctl.engine_importable_as_root() is False
    assert "not importing the Hammunition engine as root" in capsys.readouterr().err


def test_root_warns_and_imports_an_engine_one_non_root_account_owns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D-056's ruling, kept: the documented install is a venv under $HOME."""
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(devctl, "_engine_dir", lambda: "/home/op/venv/lib/hammunition")
    monkeypatch.setattr(
        devctl,
        "writable_including_symlink_target",
        lambda path: WritabilityFinding("/home/op/venv", WritabilityRisk.OWNED_BY_NON_ROOT),
    )
    assert devctl.engine_importable_as_root() is True
    assert "owned by a non-root account" in capsys.readouterr().err


def test_root_imports_a_root_owned_engine_quietly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(devctl, "_engine_dir", lambda: "/usr/lib/python3/dist-packages/hammunition")
    monkeypatch.setattr(devctl, "writable_including_symlink_target", lambda path: None)
    assert devctl.engine_importable_as_root() is True
    assert capsys.readouterr().err == ""


def test_an_untrusted_engine_makes_the_time_verbs_say_engine_not_installed(
    as_root: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(devctl, "engine_importable_as_root", lambda: False)
    monkeypatch.setattr(devctl, "_survey", lambda: ([], []))
    assert main(["time", "mode", "auto"]) == 2
    assert "engine is not installed" in capsys.readouterr().err


# --- verbs that change the machine need root, before any side effect ----------


def test_linger_without_root_is_exit_2_and_changes_nothing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this, unprivileged `linger on` could run loginctl and then fail
    to write its record, leaving linger on that a later `off` calls not ours."""
    from helper_fakes import FakeRunner

    from hammunition_devctl.run import set_runner

    runner = FakeRunner()
    set_runner(runner)
    monkeypatch.setattr(devctl, "write_record", lambda record: pytest.fail("wrote a record"))
    assert main(["linger", "on"]) == 2
    assert "needs root" in capsys.readouterr().err
    assert runner.calls == []


def test_time_mode_without_root_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["time", "mode", "auto"]) == 2
    assert "needs root" in capsys.readouterr().err


def test_park_and_wake_without_root_are_exit_2_before_the_write(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = power.Parkable(
        "gnss-ublox", "s", "usb_deauthorize", (), "/sys/bus/usb/devices/1-4", "1546:01a8", False
    )
    monkeypatch.setattr(devctl, "_survey", lambda: ([found], []))
    monkeypatch.setattr(devctl, "execute", lambda plan: pytest.fail("wrote without root"))
    for verb in ("park", "wake"):
        assert main([verb, "gnss-ublox"]) == 2
        assert "needs root" in capsys.readouterr().err


def test_a_refusal_about_the_name_still_comes_first_without_root(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(devctl, "_survey", lambda: ([], []))
    assert main(["park", "nothing"]) == 2
    assert "not a parkable" in capsys.readouterr().err


# --- a damaged linger record -------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["{{{ not yaml", "uid: abc\nenabled_by_us: true\n", "uid: [1, 2]\n", "- a\n- list\n", "uid:\n"],
)
def test_a_damaged_record_is_absent_never_a_crash(tmp_path: Path, text: str) -> None:
    path = tmp_path / "linger.yaml"
    path.write_text(text)
    notes: list[str] = []
    assert linger.read_record(path=path, notes=notes) is None


def test_services_state_still_prints_one_document_with_a_damaged_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from helper_fakes import FakeRunner

    from hammunition_devctl.run import Result, set_runner

    record = tmp_path / "absent-linger.yaml"  # the conftest's redirect target
    record.write_text("uid: abc\n")
    import pwd

    name = pwd.getpwuid(os.getuid()).pw_name
    set_runner(
        FakeRunner(
            {("/usr/bin/loginctl", "show-user", name, "--property=Linger", "--value"): Result(0, "no\n")}
        )
    )
    assert main(["services", "state"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["linger"] == {"state": "off", "ours": False}
    assert "not a number" in captured.err


def test_root_does_not_read_a_linger_record_it_would_not_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "linger.yaml"
    path.write_text("uid: 1000\nenabled_by_us: true\n")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    notes: list[str] = []
    if os.getuid() == 0:
        pytest.skip("running as root")
    assert linger.read_record(path=path, notes=notes) is None  # owned by the test's user
    assert any("not owned by root" in n for n in notes)


def test_linger_commands_are_absolute() -> None:
    assert linger.enable_command("op")[0] == "/usr/bin/loginctl"
    assert linger.disable_command("op")[0] == "/usr/bin/loginctl"


# --- names ---------------------------------------------------------------------


def test_a_name_twice_in_the_system_file_is_listed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hammunition_devctl import datafiles, services

    path = tmp_path / "svc.yaml"
    monkeypatch.setattr(datafiles, "SERVICES_FILE", path)
    path.write_text(
        "version: 1\nservices:\n"
        "  - {name: time, unit: ntpsec.service, scope: system, description: a}\n"
        "  - {name: time, unit: chrony.service, scope: system, description: b}\n"
    )
    notes: list[str] = []
    rows = services.load_services(notes)
    assert [r.unit for r in rows] == ["ntpsec.service"]
    assert any("appears twice" in n for n in notes)


def test_the_privileged_commands_are_started_by_absolute_path() -> None:
    from hammunition_devctl import services

    assert services.SYSTEMCTL == "/usr/bin/systemctl"
    assert services.LOGINCTL == "/usr/bin/loginctl"


# --- install.sh / uninstall.sh and the .deb ------------------------------------


def _script(name: str, root: Path, *args: str, path_dir: Path | None = None):
    env = {**os.environ, "HAMMUNITION_DEVCTL_ROOT": str(root), "HAMMUNITION_DEVCTL_SUDO": ""}
    if path_dir is not None:
        env["PATH"] = f"{path_dir}:{env['PATH']}"
    return subprocess.run(
        [str(ROOT / name), *args],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def _fake_dpkg_query(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "dpkg-query"
    fake.write_text('#!/bin/sh\necho "hammunition-devctl: $2"\nexit 0\n')
    fake.chmod(0o755)
    return bin_dir


def test_install_sh_does_not_overwrite_files_the_deb_owns(tmp_path: Path) -> None:
    root = tmp_path / "root"
    done = _script("install.sh", root, "--helper-only", "--yes", path_dir=_fake_dpkg_query(tmp_path))
    assert done.returncode == 0
    assert "installed by the hammunition-devctl package" in done.stdout
    assert not root.exists()


def test_uninstall_sh_does_not_delete_files_the_deb_owns(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _script("install.sh", root, "--helper-only", "--yes")  # no dpkg-query fake: installs
    done = _script("uninstall.sh", root, "--helper-only", "--yes", path_dir=_fake_dpkg_query(tmp_path))
    assert "installed by the hammunition-devctl package" in done.stdout
    assert (root / "usr/local/libexec/hammunition-devctl").exists()


def test_the_deb_tree_on_disk_also_counts_as_owned(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "usr/share/hammunition-devctl").mkdir(parents=True)
    done = _script("install.sh", root, "--helper-only", "--yes")
    assert "installed by the hammunition-devctl package" in done.stdout
    assert not (root / "usr/local").exists()


def test_install_sh_refuses_an_interpreter_that_does_not_exist(tmp_path: Path) -> None:
    done = _script("install.sh", tmp_path / "root", "--helper-only", "--yes", "--interpreter", "/nonexistent/python")
    assert done.returncode == 2 and "not an executable" in done.stderr


def test_a_reinstall_leaves_no_file_an_older_version_shipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _script("install.sh", root, "--helper-only", "--yes")
    stale = root / "usr/local/lib/hammunition-devctl/hammunition_devctl/old_module.py"
    stale.write_text("raise SystemExit('stale')\n")
    _script("install.sh", root, "--helper-only", "--yes")
    assert not stale.exists()


def test_install_sh_warns_about_an_interpreter_a_user_owns(tmp_path: Path) -> None:
    """A wrapper that runs a Python (and, through the `time` verbs, an engine)
    from a tree an unprivileged account can edit is the escalation the
    runtime gate exists for; saying so at install time is the first line."""
    interp = tmp_path / "venv" / "bin" / "python"
    interp.parent.mkdir(parents=True)
    interp.symlink_to(sys.executable)
    done = _script("install.sh", tmp_path / "root", "--helper-only", "--yes", "--interpreter", str(interp))
    assert done.returncode == 0
    assert "owned by a non-root account" in done.stderr
