"""Put the helper's package on the path for the pytest-style tests.

The tests that predate the helper (the Qt tray's, the applet's) are plain
unittest and insert their own paths; these are pytest, and one line here
saves each of them a ``sys.path`` edit.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "devctl"))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_helper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No test of the helper may start a real process or read the real data files.

    ``run`` is replaced by a stand-in that fails the test, so a verb that runs
    a command nobody faked is a red test and never a ``systemctl`` or ``nmcli``
    run on the machine that happens to be running the suite. The three data
    files point at nothing, and the engine is not imported unless a test says.
    A test that wants a command or a file installs its own.
    """
    try:
        from hammunition_devctl import datafiles, run
    except ImportError:  # pragma: no cover - the unittest-only jobs have no yaml
        yield
        return

    def refuse(argv):  # type: ignore[no-untyped-def]
        raise AssertionError(f"a test ran a real command: {list(argv)!r}")

    run.set_runner(refuse)
    monkeypatch.setattr(datafiles, "DEVICES_FILE", tmp_path / "absent-devices.yaml")
    monkeypatch.setattr(datafiles, "SERVICES_FILE", tmp_path / "absent-services.yaml")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "absent-config"))
    monkeypatch.setattr("hammunition_devctl.devices._from_engine", lambda notes: None)
    yield
    run.set_runner(None)
