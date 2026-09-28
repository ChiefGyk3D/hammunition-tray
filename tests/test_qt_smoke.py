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
        key = "state" if program == HELPER else args[1]
        done(self.answers.get(key, ProcResult(started=True, stdout="[]")))


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
        self.assertEqual(runner.calls[0], (HELPER, ["state"]))
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
        self.action(tray, "u-blox GNSS receiver (1-4)").trigger()
        self.assertEqual(runner.calls[1], ("/usr/bin/pkexec", [HELPER, "park", "gnss-ublox@1-4"]))
        self.assertEqual(runner.calls[2], (HELPER, ["state"]))

    def test_a_dismissed_prompt_leaves_the_item_showing_the_truth(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.make([row()])
        runner.answers["park"] = ProcResult(started=True, code=126)
        tray.refresh()
        self.action(tray, "u-blox GNSS receiver (1-4)").trigger()
        self.assertTrue(self.action(tray, "u-blox GNSS receiver (1-4)").isChecked())
        self.assertEqual(tray.state.last_error, "")

    def test_forget_is_wake(self):
        tray, runner = self.make([row(summary="", parked=None, kept=True, attached=False)])
        tray.refresh()
        self.action(tray, "Forget gnss-ublox").trigger()
        self.assertEqual(runner.calls[1], ("/usr/bin/pkexec", [HELPER, "wake", "gnss-ublox@1-4"]))

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
