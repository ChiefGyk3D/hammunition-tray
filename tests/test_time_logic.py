"""The Time section's rules (Hammunition D-058), tested without a display.

Every case is a fake ``hammunition-devctl time state`` from time_fixtures.
The applet's timelogic.js is held to the same answers by test_time_parity.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qt"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hammunition_tray_qt import logic, timelogic  # noqa: E402
from hammunition_tray_qt.logic import ProcResult, TrayState  # noqa: E402
from time_fixtures import BASE, POLLS, STATES  # noqa: E402

HELPER = "/usr/local/libexec/hammunition-devctl"


def ok(stdout="", code=0, stderr=""):
    return ProcResult(started=True, crashed=False, code=code, stdout=stdout, stderr=stderr)


def poll(name, state=None):
    code, out, err = POLLS[name]
    return logic.apply_time_poll(state or TrayState(), ok(out, code, err))


def with_time(name, **kw):
    """A tray that has polled devices (none) and this time state."""
    s = TrayState(devices=(), **kw)
    return logic.apply_time_poll(s, ok(json.dumps(STATES[name])))


def t(name):
    return timelogic.parse_time_state(json.dumps(STATES[name]))


class Contract(unittest.TestCase):
    def test_the_fixture_has_exactly_the_engines_keys(self):
        # hammunition.gpstime.state.JSON_KEYS, Hammunition 0.18.0.
        self.assertEqual(
            list(BASE),
            [
                "mode", "mode_set", "daemon", "gps", "following", "offset_ms", "last_sync",
                "last_source", "holdover_seconds", "rtc", "grants", "dhcp_config", "problems",
            ],
        )

    def test_the_four_modes_in_the_engines_order(self):
        self.assertEqual(timelogic.MODES, ("auto", "prefer-gps", "ntp-only", "gps-only"))

    def test_the_engine_floor(self):
        self.assertEqual(timelogic.ENGINE_FLOOR, "0.18.0")
        self.assertIn("0.18.0", timelogic.headline(None, True))


class Argv(unittest.TestCase):
    def test_the_time_poll_has_no_pkexec(self):
        self.assertEqual(logic.time_poll_argv(), (HELPER, ["time", "state"]))

    def test_a_mode_change_is_pkexec_helper_time_mode_mode(self):
        for mode in timelogic.MODES:
            self.assertEqual(
                logic.time_mode_argv(mode), ("/usr/bin/pkexec", [HELPER, "time", "mode", mode])
            )

    def test_no_other_mode_reaches_pkexec(self):
        for bad in ("", "AUTO", "auto ", "gps-pps", "auto; reboot", "--help", "state", None):
            with self.subTest(mode=bad), self.assertRaises(ValueError):
                logic.time_mode_argv(bad)


class Poll(unittest.TestCase):
    def test_a_good_poll(self):
        s = poll("ok")
        self.assertEqual(s.time_state, t("follows-gps"))
        self.assertFalse(s.time_unsupported)
        self.assertEqual(s.time_error, "")

    def test_an_old_engine_is_unsupported_not_an_error(self):
        s = poll("old-engine")
        self.assertTrue(s.time_unsupported)
        self.assertIsNone(s.time_state)
        self.assertEqual(s.time_error, "")
        self.assertEqual(s.last_error, "")

    def test_an_old_engine_is_said_once_however_many_polls(self):
        s = TrayState(devices=())
        for _ in range(5):
            s = poll("old-engine", s)
        texts = [e.text for e in logic.menu_model(s)]
        self.assertEqual(sum("Update Hammunition" in x for x in texts), 1)
        self.assertEqual([e for e in logic.menu_model(s) if e.kind == "error"], [])
        self.assertEqual([e for e in logic.menu_model(s) if e.kind == "mode"], [])

    def test_an_updated_engine_is_picked_up_without_a_restart(self):
        s = poll("ok", poll("old-engine"))
        self.assertFalse(s.time_unsupported)
        self.assertIsNotNone(s.time_state)

    def test_127_clears_the_section_and_leaves_missing_to_the_device_poll(self):
        s = poll("missing", poll("ok"))
        self.assertIsNone(s.time_state)
        self.assertEqual(s.time_error, "")
        self.assertFalse(s.helper_missing)

    def test_a_helper_that_cannot_start(self):
        s = logic.apply_time_poll(poll("ok"), ProcResult(started=False))
        self.assertIsNone(s.time_state)
        self.assertEqual(s.time_error, "")

    def test_a_failure_keeps_the_last_state_and_says_why(self):
        before = poll("ok")
        s = poll("failed-with-stderr", before)
        self.assertEqual(s.time_error, "error: boom")
        self.assertEqual(s.time_state, before.time_state)
        self.assertEqual(poll("failed-silently").time_error, "Could not read the time state")

    def test_a_crash_is_a_failure(self):
        s = logic.apply_time_poll(TrayState(), ProcResult(started=True, crashed=True, code=2))
        self.assertFalse(s.time_unsupported)
        self.assertEqual(s.time_error, "Could not read the time state")

    def test_anything_but_the_object_is_a_parse_error(self):
        for name in ("not-json", "an-array", "no-mode", "null"):
            with self.subTest(name):
                s = poll(name)
                self.assertEqual(s.time_error, "Could not parse the time state")
                self.assertIsNone(s.time_state)

    def test_a_good_poll_clears_the_error(self):
        self.assertEqual(poll("ok", poll("not-json")).time_error, "")

    def test_the_time_poll_never_touches_the_device_polls_error_or_the_actions(self):
        s = poll("failed-with-stderr", TrayState(last_error="dev", action_error="act"))
        self.assertEqual((s.last_error, s.action_error), ("dev", "act"))
        s, _ = logic.apply_poll(s, ok("[]"))
        self.assertEqual(s.time_error, "error: boom")


class Parse(unittest.TestCase):
    def test_daemon_null_stays_null(self):
        self.assertIsNone(t("timesyncd").daemon)
        self.assertIsNone(t("ntpsec-removed-conffile-left").daemon)

    def test_rtc_false_only_when_said(self):
        self.assertFalse(t("no-rtc").rtc)
        row = dict(BASE)
        del row["rtc"]
        self.assertTrue(timelogic.parse_time_state(json.dumps(row)).rtc)

    def test_wrong_types_fall_back_rather_than_crash(self):
        row = dict(BASE, offset_ms="3", holdover_seconds=True, problems="x", grants="yes")
        s = timelogic.parse_time_state(json.dumps(row))
        self.assertIsNone(s.offset_ms)
        self.assertIsNone(s.holdover_seconds)
        self.assertEqual(s.problems, ())
        self.assertFalse(s.grants)


class Words(unittest.TestCase):
    CASES = {
        "follows-gps": "The clock follows the GPS (offset +3.3 ms)",
        "follows-network": "The clock follows the network (offset +0.3 ms)",
        "follows-network-negative-tie": "The clock follows the network (offset -0.3 ms)",
        "follows-network-tiny-negative": "The clock follows the network (offset +0.0 ms)",
        "follows-gps-no-offset": "The clock follows the GPS",
        "holdover": "Holdover since 14:44 UTC (2 h 5 min): nothing is setting the clock",
        "holdover-days": "Holdover since 14:44 UTC (1 d 1 h): nothing is setting the clock",
        "holdover-just-now": "Holdover since 14:44 UTC (0 min): nothing is setting the clock",
        "never-synchronised": (
            "Nothing is setting the clock, and ntpd has not synchronised since it started"
        ),
        "ntpd-silent": "Time source unknown",
        "timesyncd": "GPS time unavailable: ntpsec is not this machine's time daemon",
        "ntpsec-removed-conffile-left": (
            "GPS time unavailable: ntpsec is not this machine's time daemon"
        ),
    }

    def test_headlines(self):
        for name, want in self.CASES.items():
            with self.subTest(name):
                self.assertEqual(timelogic.headline(t(name), False), want)

    def test_before_the_first_poll(self):
        self.assertEqual(timelogic.headline(None, False), "Reading time state…")

    def test_unsupported_wins(self):
        self.assertIn("Update Hammunition", timelogic.headline(t("follows-gps"), True))

    def test_the_mode_labels(self):
        self.assertEqual(
            [timelogic.mode_label(m) for m in timelogic.MODES],
            ["Automatic (the default)", "Prefer the GPS", "Network only", "GPS only"],
        )
        self.assertEqual(timelogic.mode_label("gps-pps"), "gps-pps")


class Notes(unittest.TestCase):
    def test_a_parked_receiver_says_gps_time_is_off(self):
        self.assertIn(timelogic.PARKED, timelogic.notes(t("parked-auto")))
        self.assertIn(timelogic.PARKED, timelogic.notes(t("parked-gps-only")))

    def test_parked_in_ntp_only_is_no_news(self):
        self.assertEqual(timelogic.notes(t("parked-ntp-only")), [])

    def test_gps_only_with_no_receiver(self):
        self.assertEqual(timelogic.notes(t("absent-gps-only")), [timelogic.NO_RECEIVER])
        self.assertEqual(timelogic.notes(t("absent-auto")), [])

    def test_missing_grants_are_said_without_sending_anyone_to_hardware_apply(self):
        self.assertEqual(timelogic.notes(t("awake-no-grants")), [timelogic.NO_GRANTS])
        for name in STATES:
            for line in timelogic.notes(t(name)) + [timelogic.headline(t(name), False)]:
                self.assertNotIn("hardware apply", line, name)

    def test_no_gpsd_is_not_a_grants_problem(self):
        # Without gpsd, apply declines the grants and `grants` stays false
        # for good; the receiver is absent from the survey too.
        self.assertEqual(timelogic.notes(t("no-gpsd")), [])
        self.assertEqual(timelogic.notes(t("awake-no-grants-ntp-only")), [])

    def test_dhcp(self):
        self.assertEqual(timelogic.notes(t("dhcp")), [timelogic.DHCP])

    def test_problems_are_passed_on_even_without_ntpsec(self):
        self.assertIn("ntpq got no answer", timelogic.notes(t("ntpd-silent"))[0])
        row = dict(STATES["timesyncd"], problems=["mode file: bad"])
        self.assertEqual(timelogic.notes(timelogic.parse_time_state(json.dumps(row))), ["mode file: bad"])

    def test_without_ntpsec_nothing_else_is_said(self):
        self.assertEqual(timelogic.notes(t("timesyncd")), [])
        self.assertEqual(timelogic.notes(t("ntpsec-removed-conffile-left")), [])


class Greying(unittest.TestCase):
    def test_greyed(self):
        for name, want in (
            ("follows-gps", False),
            ("timesyncd", True),
            ("ntpsec-removed-conffile-left", True),
            ("parked-auto", True),
            ("parked-gps-only", True),
            ("parked-ntp-only", False),
            ("absent-gps-only", False),
        ):
            with self.subTest(name):
                self.assertEqual(timelogic.greyed(t(name)), want)
        self.assertFalse(timelogic.greyed(None))

    def test_modes_can_be_chosen_only_with_ntpsec(self):
        self.assertTrue(timelogic.can_choose(t("parked-auto"), False))
        self.assertFalse(timelogic.can_choose(t("timesyncd"), False))
        self.assertFalse(timelogic.can_choose(t("ntpsec-removed-conffile-left"), False))
        self.assertFalse(timelogic.can_choose(t("follows-gps"), True))
        self.assertFalse(timelogic.can_choose(None, False))


class Menu(unittest.TestCase):
    def section(self, state):
        entries = logic.menu_model(state)
        start = next(i for i, e in enumerate(entries) if e.kind == "heading")
        return entries[start:]

    def modes(self, state):
        return [e for e in logic.menu_model(state) if e.kind == "mode"]

    def test_the_section_follows_the_device_footer(self):
        kinds = [e.kind for e in logic.menu_model(with_time("follows-gps"))]
        self.assertLess(kinds.index("footer"), kinds.index("heading"))
        self.assertEqual(kinds[-1], "quit")

    def test_heading_headline_and_four_modes_with_the_current_one_checked(self):
        sec = self.section(with_time("prefer-gps"))
        self.assertEqual((sec[0].kind, sec[0].text), ("heading", "Time"))
        self.assertEqual(sec[1].kind, "time")
        modes = self.modes(with_time("prefer-gps"))
        self.assertEqual([e.mode for e in modes], list(timelogic.MODES))
        self.assertEqual([e.checked for e in modes], [False, True, False, False])
        self.assertTrue(all(e.enabled and e.verb == "time-mode" for e in modes))

    def test_no_ntpsec_disables_the_modes(self):
        for name in ("timesyncd", "ntpsec-removed-conffile-left"):
            self.assertTrue(all(not e.enabled for e in self.modes(with_time(name))), name)

    def test_parked_greys_but_leaves_the_modes_usable(self):
        s = with_time("parked-auto")
        self.assertTrue(all(e.enabled for e in self.modes(s)))
        self.assertIn(timelogic.PARKED, [e.text for e in logic.menu_model(s)])

    def test_modes_are_disabled_while_acting(self):
        s = logic.begin_action(with_time("follows-gps"))
        self.assertTrue(all(not e.enabled for e in self.modes(s)))

    def test_an_unknown_mode_checks_nothing(self):
        self.assertTrue(all(not e.checked for e in self.modes(with_time("unknown-mode"))))

    def test_before_the_first_time_poll(self):
        s = TrayState(devices=())
        self.assertIn("Reading time state…", [e.text for e in self.section(s)])
        self.assertEqual(self.modes(s), [])

    def test_hidden_when_the_helper_is_missing(self):
        s = TrayState(helper_missing=True, time_unsupported=True)
        self.assertFalse(any(e.kind in ("heading", "time", "mode") for e in logic.menu_model(s)))

    def test_the_time_error_is_shown(self):
        s = poll("failed-with-stderr", with_time("follows-gps"))
        self.assertIn("error: boom", [e.text for e in logic.menu_model(s) if e.kind == "error"])

    def test_a_mode_change_error_survives_the_repolls(self):
        # Exit 1 is "written, but not verified": its stderr is the news.
        s = logic.apply_action(
            logic.begin_action(with_time("follows-gps")),
            ok(code=1, stderr="unverified: ntpsec did not come back\n"),
        )
        s, _ = logic.apply_poll(s, ok("[]"))
        s = poll("ok", s)
        self.assertEqual(s.action_error, "unverified: ntpsec did not come back")

    def test_a_refused_mode_change_is_shown_and_a_dismissed_one_is_not(self):
        s = logic.apply_action(TrayState(acting=True), ok(code=2, stderr="error: no ntpsec\n"))
        self.assertEqual(s.action_error, "error: no ntpsec")
        for code in (126, 127):
            s = logic.apply_action(TrayState(acting=True), ok(code=code))
            self.assertEqual(s.action_error, "", code)


class Tooltip(unittest.TestCase):
    def test_no_rtc_is_a_tooltip_line(self):
        self.assertEqual(
            logic.tooltip(with_time("no-rtc")),
            "Hammunition Devices\nNo parkable device is attached\n" + timelogic.NO_RTC,
        )

    def test_otherwise_unchanged(self):
        self.assertEqual(
            logic.tooltip(with_time("follows-gps")),
            "Hammunition Devices\nNo parkable device is attached",
        )


if __name__ == "__main__":
    unittest.main()
