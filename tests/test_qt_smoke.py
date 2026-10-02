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
from controls_fixtures import RADIOS, RADIOS_POLLS, SERVICES, SERVICES_POLLS  # noqa: E402
from time_fixtures import POLLS, STATES  # noqa: E402


def _time_ok(row=None):
    from hammunition_tray_qt.logic import ProcResult

    return ProcResult(started=True, stdout=json.dumps(row or STATES["follows-gps"]))


TIME_OK = _time_ok()


def _doc_ok(doc):
    from hammunition_tray_qt.logic import ProcResult

    return ProcResult(started=True, stdout=json.dumps(doc))


def _poll(triple):
    from hammunition_tray_qt.logic import ProcResult

    code, out, err = triple
    return ProcResult(started=True, code=code, stdout=out, stderr=err)


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
        # "state", "time state", "services state" and "radio state" for the
        # polls; "park", "wake" and "time mode MODE" for what goes through
        # pkexec; "services VERB NAME" through pkexec for a system-scope
        # service and straight to the helper for a user-scope one; and
        # "radio on|off NAME", always direct.
        if program == HELPER:
            key = " ".join(args)
        else:
            key = args[1] if args[1] in ("park", "wake") else " ".join(args[1:])
        defaults = {
            "time state": TIME_OK,
            "services state": _doc_ok(SERVICES["empty"]),
            "radio state": _doc_ok(RADIOS["empty"]),
        }
        default = defaults.get(key, ProcResult(started=True, stdout="[]"))
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

    def test_one_tick_asks_for_all_four_documents_with_no_pkexec(self):
        tray, runner = self.make([row()])
        tray.refresh()
        self.assertEqual(
            runner.calls,
            [
                (HELPER, ["time", "state"]),
                (HELPER, ["state"]),
                (HELPER, ["services", "state"]),
                (HELPER, ["radio", "state"]),
            ],
        )

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
        self.assertEqual(sections, ["Controls", "Devices", "Services", "Radios", "Time"])
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

    # -- the Controls panel: services and radios (helper contract v1) -------

    def services_tray(self, doc="d2", rows=None):
        tray, runner = self.make(rows if rows is not None else [row()])
        runner.answers["services state"] = _doc_ok(SERVICES[doc])
        runner.answers["radio state"] = _doc_ok(RADIOS["d2"])
        tray.refresh()
        del runner.calls[:]
        return tray, runner

    def test_the_menu_has_the_three_groups_with_their_rows(self):
        tray, _ = self.services_tray()
        texts = self.texts(tray)
        self.assertIn("gps-tether — GPS position for QMapShack and the browser map on 127.0.0.1", texts)
        self.assertIn("rig — rigctld for this operator: not installed", texts)
        self.assertEqual(texts.count("↳ Start at login"), 5)
        self.assertIn("Mobile broadband (WWAN) — cdc-wdm0", texts)
        self.assertIn("Wi-Fi — wlan0", texts)
        self.assertIn("Bluetooth", texts)
        self.assertTrue(self.action(tray, "gps-tether").isChecked())
        self.assertFalse(self.action(tray, "rig").isEnabled())

    def test_a_user_service_runs_the_helper_directly_never_pkexec(self):
        tray, runner = self.services_tray()
        self.action(tray, "gps-tether").trigger()
        self.assertEqual(runner.calls[0], (HELPER, ["services", "stop", "gps-tether"]))
        self.assertTrue(all(c[0] == HELPER for c in runner.calls))
        # Every document is read again afterwards.
        self.assertIn((HELPER, ["services", "state"]), runner.calls[1:])
        self.assertIn((HELPER, ["radio", "state"]), runner.calls[1:])

    def test_a_system_service_goes_through_pkexec(self):
        tray, runner = self.services_tray()
        self.action(tray, "gpsd").trigger()
        self.assertEqual(runner.calls[0], (PKEXEC, [HELPER, "services", "stop", "gpsd"]))

    def test_the_login_checkbox_enables_or_disables(self):
        tray, runner = self.services_tray("disabled-at-login")
        [login] = [a for a in tray.menu.actions() if a.text() == "↳ Start at login"]
        self.assertFalse(login.isChecked())
        login.trigger()
        self.assertEqual(runner.calls[0], (HELPER, ["services", "enable", "gps-tether"]))

    def test_a_radio_runs_the_helper_directly(self):
        tray, runner = self.services_tray()
        self.action(tray, "Wi-Fi").trigger()
        self.assertEqual(runner.calls[0], (HELPER, ["radio", "off", "wifi"]))

    def test_the_intent_shows_at_once_and_the_next_poll_confirms(self):
        tray, runner = self.services_tray("running")
        runner.answers["services state"] = _doc_ok(SERVICES["stopped"])
        self.action(tray, "gps-tether").trigger()
        self.assertFalse(self.action(tray, "gps-tether").isChecked())
        self.assertEqual(tray.state.pending, ())

    def test_a_failed_verb_reverts_and_shows_the_one_line_error(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.services_tray("running")
        runner.answers["services stop gps-tether"] = ProcResult(
            started=True, code=1, stderr="error: gps-tether: failed to stop\nTraceback...\n"
        )
        self.action(tray, "gps-tether").trigger()
        self.assertTrue(self.action(tray, "gps-tether").isChecked())
        self.assertIn("error: gps-tether: failed to stop", self.texts(tray))
        self.assertFalse(any("Traceback" in t for t in self.texts(tray)))

    def test_a_dismissed_system_prompt_leaves_the_service_as_it_was(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.services_tray()
        runner.answers["services stop gpsd"] = ProcResult(started=True, code=126)
        self.action(tray, "gpsd").trigger()
        self.assertTrue(self.action(tray, "gpsd").isChecked())
        self.assertEqual(tray.state.action_error, "")

    def test_a_helper_without_the_verbs_says_update_once_per_group(self):
        tray, runner = self.make([row()])
        runner.answers["services state"] = _poll(SERVICES_POLLS["old-helper"])
        runner.answers["radio state"] = _poll(RADIOS_POLLS["old-helper"])
        for _ in range(3):
            tray.refresh()
        texts = self.texts(tray)
        self.assertEqual(texts.count("update hammunition-tray"), 2)
        self.assertFalse(any("invalid choice" in t for t in texts))
        # The devices and the clock are untouched.
        self.assertIn("u-blox GNSS receiver (1-4) — awake", texts)
        self.assertEqual(len(self.modes(tray)), 4)

    def test_a_service_name_that_is_not_an_allow_list_name_never_runs(self):
        doc = {"kind": "services", "version": 1,
               "services": [{"name": "x; reboot", "unit": "u.service", "scope": "user",
                             "description": "d", "active": "active", "enabled": "enabled", "root": False}]}
        tray, runner = self.make([row()])
        runner.answers["services state"] = _doc_ok(doc)
        tray.refresh()
        del runner.calls[:]
        self.action(tray, "x; reboot").trigger()
        self.assertEqual(runner.calls, [])
        self.assertTrue(any("refusing service name" in t for t in self.texts(tray)))

    def test_an_absent_radio_tool_is_named_and_disabled(self):
        tray, runner = self.make([row()])
        runner.answers["radio state"] = _doc_ok(RADIOS["tool-missing"])
        tray.refresh()
        a = self.action(tray, "Bluetooth")
        self.assertEqual(a.text(), "Bluetooth — not available: bluetoothctl is not installed")
        self.assertFalse(a.isEnabled())

    def test_helper_missing_hides_the_groups(self):
        from hammunition_tray_qt.logic import ProcResult

        tray, runner = self.make([])
        runner.answers["state"] = ProcResult(started=False)
        runner.answers["services state"] = ProcResult(started=False)
        runner.answers["radio state"] = ProcResult(started=False)
        tray.refresh()
        sections = [a.text() for a in tray.menu.actions() if a.isSeparator() and a.text()]
        self.assertNotIn("Services", sections)
        self.assertNotIn("Radios", sections)

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
