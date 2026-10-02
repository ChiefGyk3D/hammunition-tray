"""The device list: the file, the engine fallback, ``state --with-source``,
the matching rule, and the trust check a root process applies."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from hammunition_devctl import datafiles, devices
from hammunition_devctl.bus import AttachedDevice, match_devices, read_usb_bus
from hammunition_devctl.devctl import main
from hammunition_devctl.devices import DeviceEntry, UsbId, load_devices

GOOD = """\
version: 1
devices:
  - name: gps-receiver
    summary: u-blox GNSS receiver
    method: usb_deauthorize
    quiet: []
    usb_ids:
      - {vendor: "1546", product: "01a8"}
      - {vendor: "0403", product: "6001", product_string: "FT232R USB UART"}
"""


@pytest.fixture
def devices_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "devctl-devices.yaml"
    monkeypatch.setattr(datafiles, "DEVICES_FILE", path)
    return path


def test_the_file_is_the_list(devices_file: Path) -> None:
    devices_file.write_text(GOOD)
    notes: list[str] = []
    entries, source = load_devices(notes)
    assert source == "file" and notes == []
    entry = entries["gps-receiver"]
    assert entry.method == "usb_deauthorize" and entry.summary == "u-blox GNSS receiver"
    assert entry.usb_ids == (
        UsbId("1546", "01a8"),
        UsbId("0403", "6001", "FT232R USB UART"),
    )


def test_an_absent_file_with_no_engine_is_none(devices_file: Path) -> None:
    entries, source = load_devices([])
    assert (entries, source) == ({}, "none")


def test_an_absent_file_falls_back_to_the_engine_and_says_so(
    devices_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = DeviceEntry("gps-receiver", "s", "usb_deauthorize", (), (UsbId("1546", "01a8"),))
    monkeypatch.setattr(devices, "_from_engine", lambda notes: {"gps-receiver": entry})
    assert load_devices([]) == ({"gps-receiver": entry}, "engine-import")


def test_a_present_file_wins_even_when_it_is_empty(
    devices_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A machine whose file says nothing is parkable must not fall back to an
    engine catalog that says otherwise."""
    devices_file.write_text("version: 1\ndevices: []\n")
    monkeypatch.setattr(devices, "_from_engine", lambda notes: pytest.fail("fell back"))
    assert load_devices([]) == ({}, "file")


def test_a_broken_file_is_empty_with_a_note_not_a_fallback(
    devices_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    devices_file.write_text("version: 1\ndevices: [ {\n")
    monkeypatch.setattr(devices, "_from_engine", lambda notes: pytest.fail("fell back"))
    notes: list[str] = []
    assert load_devices(notes) == ({}, "file")
    assert any("not valid YAML" in n for n in notes)


@pytest.mark.parametrize(
    "row",
    [
        "{name: 'Bad Name', method: usb_deauthorize, usb_ids: [{vendor: '1546'}]}",
        "{name: x, method: run_this, usb_ids: [{vendor: '1546'}]}",
        "{name: x, method: usb_deauthorize, quiet: [rm], usb_ids: [{vendor: '1546'}]}",
        "{name: x, method: usb_deauthorize, usb_ids: []}",
        "{name: x, method: usb_deauthorize, usb_ids: [{vendor: 'zzzz'}]}",
        "{name: x, method: usb_deauthorize, usb_ids: [{vendor: '1546', product: '1'}]}",
    ],
)
def test_a_row_that_breaks_a_rule_is_dropped_with_a_note(devices_file: Path, row: str) -> None:
    devices_file.write_text(f"version: 1\ndevices:\n  - {row}\n")
    notes: list[str] = []
    entries, source = load_devices(notes)
    assert entries == {} and source == "file" and notes


def test_hex_given_as_a_yaml_number_still_matches_when_quoted_in_the_file(
    devices_file: Path,
) -> None:
    """`1546` unquoted is a YAML int and `0403` an octal-looking one; the
    contract says quote them. An unquoted one that survives as a valid four-digit
    string is accepted, and one that cannot be read as four hex digits is not."""
    devices_file.write_text(
        "version: 1\ndevices:\n  - {name: x, method: usb_deauthorize, usb_ids: [{vendor: 1546}]}\n"
    )
    entries, _ = load_devices([])
    assert entries["x"].usb_ids[0].vendor == "1546"


def _attached(vendor="1546", product="01a8", product_string=None, address="1-4"):
    return AttachedDevice(vendor, product, product_string=product_string, sysfs_path=f"/x/{address}")


def _entry(*ids: UsbId, name="gps-receiver") -> dict[str, DeviceEntry]:
    return {name: DeviceEntry(name, "s", "usb_deauthorize", (), ids)}


def test_matching_is_vendor_and_product() -> None:
    entries = _entry(UsbId("1546", "01a8"))
    assert len(match_devices([_attached()], entries)) == 1
    assert match_devices([_attached(product="01a9")], entries) == []
    assert match_devices([_attached(vendor="1547")], entries) == []


def test_an_id_without_a_product_matches_any_product_of_the_vendor() -> None:
    assert len(match_devices([_attached(product="ffff")], _entry(UsbId("1546")))) == 1


def test_a_shared_identifier_needs_the_product_string_when_the_bus_has_one() -> None:
    entries = _entry(UsbId("0403", "6001", "FT232R USB UART"))
    other = _attached("0403", "6001", product_string="Some other FTDI board")
    same = _attached("0403", "6001", product_string="FT232R USB UART")
    bare = _attached("0403", "6001")
    assert match_devices([other], entries) == []
    assert len(match_devices([same], entries)) == 1
    assert len(match_devices([bare], entries)) == 1


def test_a_device_two_entries_claim_is_listed_once_per_entry_in_name_order() -> None:
    entries = {**_entry(UsbId("1546"), name="b-device"), **_entry(UsbId("1546"), name="a-class")}
    assert [m.name for m in match_devices([_attached()], entries)] == ["a-class", "b-device"]


def test_the_bus_reader_skips_interfaces_and_lowercases(tmp_path: Path) -> None:
    node = tmp_path / "1-4"
    node.mkdir()
    (node / "idVendor").write_text("1546\n")
    (node / "idProduct").write_text("01A8\n")
    (tmp_path / "1-4:1.0").mkdir()
    (found,) = read_usb_bus(tmp_path)
    assert (found.vendor, found.product, found.sysfs_path) == ("1546", "01a8", str(node))
    assert read_usb_bus(tmp_path / "nope") == []


# --- state --with-source -------------------------------------------------------


def test_with_source_wraps_the_same_rows_and_names_the_source(
    devices_file: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from hammunition_devctl import devctl
    from hammunition_devctl.power import Parkable

    parked = Parkable(
        "gps-receiver", "s", "usb_deauthorize", (), "/sys/bus/usb/devices/1-4", "1546:01a8", False
    )
    monkeypatch.setattr(devctl, "read_kept", lambda: [])
    monkeypatch.setattr(devctl, "_survey", lambda: ([parked], []))
    monkeypatch.setattr(devctl, "_survey_with_source", lambda: ([parked], [], "engine-import"))
    assert main(["state"]) == 0
    plain = json.loads(capsys.readouterr().out)
    assert isinstance(plain, list)
    assert main(["state", "--with-source"]) == 0
    wrapped = json.loads(capsys.readouterr().out)
    assert list(wrapped) == ["kind", "version", "source", "devices"]
    assert wrapped["kind"] == "state" and wrapped["version"] == 1
    assert wrapped["source"] == "engine-import"
    assert wrapped["devices"] == plain


def test_a_fallback_is_a_note_on_stderr_and_the_plain_state_is_still_an_array(
    devices_file: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hammunition_devctl.devctl.read_kept", lambda: [])
    monkeypatch.setattr("hammunition_devctl.devctl.read_usb_bus", lambda: [])
    assert main(["state"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "no device list" in captured.err


# --- the trust check a root process applies ---------------------------------


def _st(mode: int, uid: int = 0) -> os.stat_result:
    return os.stat_result((mode, 0, 0, 1, uid, 0, 0, 0, 0, 0))


FILE_OK = _st(stat.S_IFREG | 0o644)
DIR_OK = _st(stat.S_IFDIR | 0o755)


def test_a_root_owned_file_in_a_root_owned_directory_is_trusted() -> None:
    assert datafiles.untrusted_reason(FILE_OK, DIR_OK) is None


@pytest.mark.parametrize(
    ("info", "parent", "why"),
    [
        (_st(stat.S_IFREG | 0o644, uid=1000), DIR_OK, "not owned by root"),
        (_st(stat.S_IFREG | 0o664), DIR_OK, "writable by group or other"),
        (_st(stat.S_IFREG | 0o646), DIR_OK, "writable by group or other"),
        (_st(stat.S_IFLNK | 0o777), DIR_OK, "not a regular file"),
        (_st(stat.S_IFDIR | 0o755), DIR_OK, "not a regular file"),
        (FILE_OK, _st(stat.S_IFDIR | 0o755, uid=1000), "directory that is not owned by root"),
        (FILE_OK, _st(stat.S_IFDIR | 0o775), "directory writable by group or other"),
        (FILE_OK, _st(stat.S_IFDIR | 0o757), "directory writable by group or other"),
    ],
)
def test_root_refuses_what_anyone_else_could_have_written(
    info: os.stat_result, parent: os.stat_result, why: str
) -> None:
    """Pure over stat results, so it says the same on a laptop, in CI and
    under a real root."""
    reason = datafiles.untrusted_reason(info, parent)
    assert reason is not None and why in reason


def test_root_never_follows_a_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "t.yaml"
    target.write_text("version: 1\n")
    link = tmp_path / "l.yaml"
    link.symlink_to(target)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    notes: list[str] = []
    assert datafiles.load_yaml(link, notes) is None
    assert notes and "not reading it as root" in notes[0]


def test_root_reads_the_file_it_opened_not_the_path_it_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The checks are on the descriptor: whatever the path points at *after*
    the open is not what is read."""
    path = tmp_path / "f.yaml"
    path.write_text("version: 1\nwho: first\n")
    seen: list[os.stat_result] = []

    def spy(info: os.stat_result, parent: os.stat_result) -> None:
        seen.append(info)
        path.unlink()  # swap the path out from under the check
        path.write_text("version: 1\nwho: second\n")
        return None

    monkeypatch.setattr(datafiles, "untrusted_reason", spy)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert datafiles.load_yaml(path, []) == {"version": 1, "who": "first"}
    assert seen


def test_root_refuses_a_file_it_does_not_own_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real checks, on a real file made by whoever runs the suite. Skipped
    only under a real root, where the file *is* root's and is trusted."""
    if os.getuid() == 0:
        pytest.skip("running as root: the file would be root-owned and trusted")
    path = tmp_path / "f.yaml"
    path.write_text("version: 1\n")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    notes: list[str] = []
    assert datafiles.load_yaml(path, notes) is None
    assert "not owned by root" in notes[0]


def test_the_user_file_follows_xdg_config_home_then_home(tmp_path: Path) -> None:
    assert datafiles.user_services_file({"XDG_CONFIG_HOME": str(tmp_path)}) == (
        tmp_path / "hammunition" / "devctl-services.yaml"
    )
    assert datafiles.user_services_file({}, home=tmp_path) == (
        tmp_path / ".config" / "hammunition" / "devctl-services.yaml"
    )
    # a relative XDG_CONFIG_HOME is not an absolute path and is ignored, as the spec says
    assert datafiles.user_services_file({"XDG_CONFIG_HOME": "rel"}, home=tmp_path) == (
        tmp_path / ".config" / "hammunition" / "devctl-services.yaml"
    )
