"""Put the helper's package on the path for the pytest-style tests.

The tests that predate the helper (the Qt tray's, the applet's) are plain
unittest and insert their own paths; these are pytest, and one line here
saves each of them a ``sys.path`` edit.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "devctl"))


import pytest  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_engine_import: run devices._from_engine for real (the suite stubs it otherwise)",
    )


@pytest.fixture(autouse=True)
def _hermetic_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
):
    """No test of the helper may start a real process or read the real data files.

    ``run`` is replaced by a stand-in that fails the test, so a verb that runs
    a command nobody faked is a red test and never a ``systemctl`` or ``nmcli``
    run on the machine that happens to be running the suite. The three data
    files point at nothing, and the engine is not imported unless a test says.
    A test that wants a command or a file installs its own.
    """
    try:
        from hammunition_devctl import datafiles, linger, run
    except ImportError:  # pragma: no cover - the unittest-only jobs have no yaml
        yield
        return

    def refuse(argv):  # type: ignore[no-untyped-def]
        raise AssertionError(f"a test ran a real command: {list(argv)!r}")

    run.set_runner(refuse)
    monkeypatch.setattr(datafiles, "DEVICES_FILE", tmp_path / "absent-devices.yaml")
    monkeypatch.setattr(datafiles, "SERVICES_FILE", tmp_path / "absent-services.yaml")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "absent-config"))
    # What a laptop that really has the helper installed, or a suite run under
    # sudo, would otherwise leak into the tests.
    monkeypatch.setattr(linger, "LINGER_RECORD", tmp_path / "absent-linger.yaml")
    monkeypatch.setattr("hammunition_devctl.devctl.LINGER_RECORD", tmp_path / "absent-linger.yaml")
    for var in ("PKEXEC_UID", "SUDO_UID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    if request.node.get_closest_marker("real_engine_import") is None:
        monkeypatch.setattr("hammunition_devctl.devices._from_engine", lambda notes: None)
    yield
    run.set_runner(None)


@pytest.fixture
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behave as root without being root.

    Three things differ for a root process and each is stubbed here, because
    each measures the machine the suite runs on rather than the code: the
    euid, the ownership check on the data files (the test's files belong to
    the test's user), and the writability gate on the interpreter and package
    (a venv under a group-writable home trips it). All three have their own
    tests with synthetic stat results.
    """
    import os

    from hammunition_devctl import datafiles, devctl

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(datafiles, "untrusted_reason", lambda info, parent: None)
    monkeypatch.setattr(devctl, "_refuse_or_warn_if_unsafe", lambda: None)
