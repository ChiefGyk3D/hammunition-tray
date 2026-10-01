"""The Qt glue, under QT_QPA_PLATFORM=offscreen.

Skips with the reason when PyQt6 is not importable, unless
HAMMUNITION_REQUIRE_PYQT6=1 is set -- which CI sets in the job that
installs python3-pyqt6, so a broken import there is a failure rather than a
quiet skip that passes forever.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QT = ROOT / "qt"
sys.path.insert(0, str(QT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from PyQt6.QtWidgets import QApplication

    PYQT6 = None
except ImportError as exc:  # pragma: no cover - depends on the machine
    PYQT6 = f"PyQt6 is not importable ({exc}); install python3-pyqt6 to run this"

if PYQT6 and os.environ.get("HAMMUNITION_REQUIRE_PYQT6") == "1":
    raise RuntimeError(PYQT6)

HELPER = "/usr/local/libexec/hammunition-devctl"
PKEXEC = "/usr/bin/pkexec"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from time_fixtures import POLLS, STATES  # noqa: E402


def _time_ok(row=None):
    from hammunition_tray_qt.logic import ProcResult

    return ProcResult(started=True, stdout=json.dumps(row or STATES["follows-gps"]))


TIME_OK = _time_ok()


def row(**kw):
    r = {
        "name": "gnss-ublox",
        "summary": "u-blox GNSS receiver",
        "address": "1-4",
        "parked": False,
        "kept": False,
        "attached": True,
    }
    r.update(kw)
    return r


class FakeRunner:
    """Answers synchronously from a queue, and records every argv."""

    def __init__(self):
        self.calls = []
        self.answers = {}

    def run(self, program, args, done, timeout_ms=None):
        from hammunition_tray_qt.logic import ProcResult

        self.calls.append((program, list(args)))
        # "state" and "time state" for the polls; "park", "wake" and
        # "time mode MODE" for what goes through pkexec.
        if program == HELPER:
            key = " ".join(args)
        else:
            key = args[1] if args[1] in ("park", "wake") else " ".join(args[1:])
        default = TIME_OK if key == "time state" else ProcResult(started=True, stdout="[]")
        done(self.answers.get(key, default))


@unittest.skipIf(PYQT6, PYQT6 or "")
class Smoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, rows):
        from hammunition_tray_qt.logic import ProcResult
        from hammunition_tray_qt.tray import Tray

        runner = FakeRunner()
        runner.answers["state"] = ProcResult(started=True, stdout=json.dumps(rows))
        tray = Tray(runner=runner)
        notices = []
        tray.icon.showMessage = lambda *a: notices.append(a)
        tray.notices = notices
        self.addCleanup(tray.close)
        return tray, runner

    def texts(self, tray):
        return [a.text() for a in tray.menu.actions() if not a.isSeparator()]

    def action(self, tray, prefix):
        [a] = [a for a in tray.menu.actions() if a.text().startswith(prefix)]
        return a

    def test_it_polls_and_builds_the_menu(self):
        tray, runner = self.make([row(), row(address="1-5", parked=True, kept=True)])
        tray.refresh()
        self.assertEqual(runner.calls[:2], [(HELPER, ["time", "state"]), (HELPER, ["state"])])
        texts = self.texts(tray)
        self.assertIn("u-blox GNSS receiver (1-4) — awake", texts)
        self.assertIn("u-blox GNSS receiver (1-5) — kept off", texts)
        self.assertIn("Quit", texts)
        self.assertTrue(self.action(tray, "u-blox GNSS receiver (1-4)").isChecked())
        self.assertFalse(self.action(tray, "u-blox GNSS receiver (1-5)").isChecked())
        self.assertIn("1 device parked", tray.icon.toolTip())
        self.assertFalse(tray.icon.icon().isNull())

    def test_the_kept_notice_once(self):
        tray, _ = self.make([row(parked=True, kept=True)])
        tray.refresh()
        tray.refresh()
        self.assertEqual(len(tray.notices), 1)
        self.assertEqual(tray.notices[0][:2], ("Kept off", "u-blox GNSS receiver"))

    def test_a_toggle_runs_pkexec_with_exactly_three_arguments_then_repolls(self):
        tray, runner = self.make([row()])
        tray.refresh()
        del runner.calls[:]
        self.action(tray, "u-blox GNSS receiver (1-4)").trigger()
        self.assertEqual(runner.calls[0], (PKEXEC, [HELPER, "park", "gnss-ublox@1-4"]))
        self.assertIn((HELPER, ["state"]), runner.calls[1:])

    def test_a_dismissed_prompt_leaves_the_item_showing_the_truth(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.make([row()])
        runner.answers["park"] = ProcResult(started=True, code=126)
        tray.refresh()
        self.action(tray, "u-blox GNSS receiver (1-4)").trigger()
        self.assertTrue(self.action(tray, "u-blox GNSS receiver (1-4)").isChecked())
        self.assertEqual(tray.state.action_error, "")

    def test_no_polkit_agent_is_shown(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.make([row()])
        runner.answers["park"] = ProcResult(
            started=True,
            code=127,
            stderr="Error executing command as another user: No authentication agent found.\n",
        )
        tray.refresh()
        self.action(tray, "u-blox GNSS receiver (1-4)").trigger()
        self.assertIn("No polkit authentication agent is running", tray.state.action_error)

    def test_forget_is_wake(self):
        tray, runner = self.make([row(summary="", parked=None, kept=True, attached=False)])
        tray.refresh()
        del runner.calls[:]
        self.action(tray, "Forget gnss-ublox").trigger()
        self.assertEqual(runner.calls[0], (PKEXEC, [HELPER, "wake", "gnss-ublox@1-4"]))

    def test_a_name_that_is_not_a_catalog_name_never_reaches_pkexec(self):
        tray, runner = self.make([row(name="x; reboot")])
        tray.refresh()
        self.action(tray, "u-blox GNSS receiver").trigger()
        self.assertEqual([c for c in runner.calls if c[0] != HELPER], [])
        self.assertTrue(any("refusing device name" in t for t in self.texts(tray)))

    def test_an_ampersand_in_a_summary_is_not_a_mnemonic(self):
        tray, _ = self.make([row(summary="R&D receiver")])
        tray.refresh()
        self.assertIn("R&&D receiver (1-4) — awake", self.texts(tray))

    def test_a_long_error_is_elided_in_the_menu_and_whole_in_its_tooltip(self):
        from hammunition_tray_qt.logic import ProcResult

        long = "error: refusing; attached: " + ", ".join(f"gnss-{i}@1-{i}" for i in range(60))
        tray, runner = self.make([row()])
        runner.answers["park"] = ProcResult(started=True, code=2, stderr=long)
        tray.refresh()
        self.action(tray, "u-blox GNSS receiver (1-4)").trigger()
        [a] = [a for a in tray.menu.actions() if a.text().startswith("error: refusing")]
        self.assertLessEqual(len(a.text()), 121)
        self.assertTrue(a.text().endswith("…"))
        self.assertEqual(a.toolTip(), long)
        self.assertTrue(tray.menu.toolTipsVisible())

    # -- the Time section (Hammunition D-058) -----------------------------

    def modes(self, tray):
        labels = ("Automatic (the default)", "Prefer the GPS", "Network only", "GPS only")
        return [a for a in tray.menu.actions() if a.text() in labels]

    def test_the_time_section_is_a_heading_a_sentence_and_four_modes(self):
        tray, runner = self.make([row()])
        tray.refresh()
        self.assertIn((HELPER, ["time", "state"]), runner.calls)
        sections = [a.text() for a in tray.menu.actions() if a.isSeparator() and a.text()]
        self.assertEqual(sections, ["Time"])
        self.assertIn("The clock follows the GPS (offset +3.3 ms)", self.texts(tray))
        modes = self.modes(tray)
        self.assertEqual(len(modes), 4)
        self.assertEqual([a.isChecked() for a in modes], [True, False, False, False])
        self.assertTrue(all(a.isEnabled() and a.isCheckable() for a in modes))

    def test_a_mode_runs_pkexec_helper_time_mode_then_repolls(self):
        tray, runner = self.make([row()])
        tray.refresh()
        del runner.calls[:]
        self.action(tray, "GPS only").trigger()
        self.assertEqual(runner.calls[0], (PKEXEC, [HELPER, "time", "mode", "gps-only"]))
        self.assertIn((HELPER, ["time", "state"]), runner.calls[1:])
        self.assertIn((HELPER, ["state"]), runner.calls[1:])

    def test_the_current_mode_asks_for_nothing(self):
        tray, runner = self.make([row()])
        tray.refresh()
        del runner.calls[:]
        self.action(tray, "Automatic (the default)").trigger()
        self.assertEqual(runner.calls, [])
        self.assertTrue(self.action(tray, "Automatic (the default)").isChecked())

    def test_a_dismissed_mode_prompt_leaves_the_reported_mode_checked(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.make([row()])
        runner.answers["time mode gps-only"] = ProcResult(started=True, code=126)
        tray.refresh()
        self.action(tray, "GPS only").trigger()
        self.assertFalse(self.action(tray, "GPS only").isChecked())
        self.assertTrue(self.action(tray, "Automatic (the default)").isChecked())
        self.assertEqual(tray.state.action_error, "")

    def test_an_unverified_mode_change_is_shown(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.make([row()])
        runner.answers["time mode gps-only"] = ProcResult(
            started=True, code=1, stderr="unverified: ntpsec did not restart\n"
        )
        tray.refresh()
        self.action(tray, "GPS only").trigger()
        self.assertIn("unverified: ntpsec did not restart", self.texts(tray))

    def test_an_old_engine_says_update_once_and_no_error(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.make([row()])
        code, out, err = POLLS["old-engine"]
        runner.answers["time state"] = ProcResult(started=True, code=code, stdout=out, stderr=err)
        for _ in range(3):
            tray.refresh()
        texts = self.texts(tray)
        self.assertEqual(sum("Update Hammunition" in t for t in texts), 1)
        self.assertEqual(self.modes(tray), [])
        self.assertFalse(any("invalid choice" in t for t in texts))

    def test_no_ntpsec_disables_the_modes(self):
        tray, runner = self.make([row()])
        runner.answers["time state"] = _time_ok(STATES["ntpsec-removed-conffile-left"])
        tray.refresh()
        self.assertTrue(all(not a.isEnabled() for a in self.modes(tray)))
        self.assertIn("GPS time unavailable: ntpsec is not this machine's time daemon", self.texts(tray))

    def test_no_rtc_is_in_the_tooltip(self):
        tray, runner = self.make([row()])
        runner.answers["time state"] = _time_ok(STATES["no-rtc"])
        tray.refresh()
        self.assertIn("No hardware clock", tray.icon.toolTip())

    def test_helper_missing(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.make([])
        runner.answers["state"] = ProcResult(started=False)
        tray.refresh()
        self.assertIn("Device control is not installed", self.texts(tray))
        self.assertFalse(tray.icon.icon().isNull())

    def test_the_real_runner_reports_a_missing_program_as_not_started(self):
        from PyQt6.QtCore import QEventLoop, QTimer

        from hammunition_tray_qt.tray import QtRunner

        results = []
        loop = QEventLoop()
        runner = QtRunner()

        def done(r):
            results.append(r)
            loop.quit()

        runner.run("/nonexistent/hammunition-devctl", ["state"], done)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].started)

    def test_the_real_runner_kills_a_poll_that_outlives_its_timeout(self):
        import time

        from PyQt6.QtCore import QEventLoop, QTimer

        from hammunition_tray_qt.tray import QtRunner

        results = []
        loop = QEventLoop()

        def done(r):
            results.append(r)
            loop.quit()

        started = time.monotonic()
        QtRunner().run(sys.executable, ["-c", "import time; time.sleep(10)"], done, timeout_ms=200)
        QTimer.singleShot(8000, loop.quit)
        loop.exec()
        self.assertLess(time.monotonic() - started, 8)
        [r] = results
        self.assertTrue(r.crashed)

    def test_the_real_runner_captures_code_and_output_without_a_shell(self):
        from PyQt6.QtCore import QEventLoop, QTimer

        from hammunition_tray_qt.tray import QtRunner

        results = []
        loop = QEventLoop()

        def done(r):
            results.append(r)
            loop.quit()

        # A shell metacharacter passed as an argument stays an argument.
        QtRunner().run(sys.executable, ["-c", "import sys; print(sys.argv[1]); sys.exit(3)", "$(id); x"], done)
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        [r] = results
        self.assertTrue(r.started)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.stdout.strip(), "$(id); x")


@unittest.skipIf(PYQT6, PYQT6 or "")
class NoTray(unittest.TestCase):
    def test_no_tray_is_one_line_on_stderr_and_exit_0(self):
        # offscreen has no system tray, which is exactly GNOME without the
        # AppIndicator extension as far as Qt can tell.
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(QT))
        p = subprocess.run(
            [sys.executable, "-m", "hammunition_tray_qt"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = [line for line in p.stderr.splitlines() if line.startswith("hammunition-tray-qt:")]
        self.assertEqual(len(lines), 1, p.stderr)
        self.assertIn("no system tray", lines[0])


if __name__ == "__main__":
    unittest.main()
