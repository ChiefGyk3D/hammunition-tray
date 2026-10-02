"""The Controls panel's rules (helper contract v1), tested without a display.

controls.py holds the rules and the wording both front ends share; logic.py
holds the state they act on. The applet's controlslogic.js is held to
controls.py by test_controls_parity; test_qt_smoke drives the real Tray with
a fake runner.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qt"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from controls_fixtures import (  # noqa: E402
    RADIOS,
    RADIOS_POLLS,
    SERVICES,
    SERVICES_POLLS,
    doc_with,
    radios_doc,
    svc,
)
from hammunition_tray_qt import controls, logic  # noqa: E402
from hammunition_tray_qt.logic import ProcResult, TrayState  # noqa: E402

HELPER = "/usr/local/libexec/hammunition-devctl"
PKEXEC = "/usr/bin/pkexec"


def ok(stdout="", code=0, stderr=""):
    return ProcResult(started=True, crashed=False, code=code, stdout=stdout, stderr=stderr)


OLD_SERVICES = ok(code=2, stderr=SERVICES_POLLS["old-helper"][2])


def services(name):
    return controls.parse_services(json.dumps(SERVICES[name]))


def radios(name):
    return controls.parse_radios(json.dumps(RADIOS[name]))


def row(name, doc="d2"):
    [r] = [r for r in services(doc).rows if r.name == name]
    return r


def with_services(name="d2", state=None):
    return logic.apply_services_poll(state or TrayState(devices=()), ok(json.dumps(SERVICES[name])))


def with_radios(name="d2", state=None):
    return logic.apply_radios_poll(state or TrayState(devices=()), ok(json.dumps(RADIOS[name])))


def entries(state, kind):
    return [e for e in logic.menu_model(state) if e.kind == kind]


class Contract(unittest.TestCase):
    def test_the_floor_is_one_and_lives_here(self):
        self.assertEqual(controls.CONTRACT_FLOOR, 1)

    def test_the_floor_is_recorded_in_no_other_python_module(self):
        for path in (ROOT / "qt/hammunition_tray_qt").glob("*.py"):
            if path.name == "controls.py":
                continue
            self.assertNotIn("CONTRACT_FLOOR =", path.read_text(), path.name)

    def test_the_update_line_is_exact(self):
        self.assertEqual(controls.UPDATE, "update hammunition-tray")


class ParseServices(unittest.TestCase):
    def test_the_d2_document(self):
        doc = services("d2")
        self.assertEqual([r.name for r in doc.rows], ["gps-tether", "gpsd", "time", "gps-resume", "rig"])
        tether = doc.rows[0]
        self.assertEqual(
            (tether.unit, tether.scope, tether.active, tether.enabled, tether.root),
            ("hammunition-gps-tether.service", "user", "active", "enabled", False),
        )
        self.assertEqual(doc.rows[1].scope, "system")
        self.assertTrue(doc.rows[1].root)
        self.assertEqual(doc.linger_state, "off")

    def test_an_unlisted_unit_is_kept_as_not_found_never_dropped(self):
        self.assertEqual(row("gps-resume").enabled, "not-found")
        self.assertEqual(row("rig").enabled, "not-found")

    def test_a_state_this_tray_does_not_know_reads_as_unknown(self):
        [r] = services("future-states").rows
        self.assertEqual((r.active, r.enabled), ("unknown", "unknown"))

    def test_a_newer_document_with_extra_keys_is_read(self):
        self.assertEqual(len(services("newer-version").rows), 1)

    def test_the_linger_block_is_optional(self):
        doc = dict(SERVICES["running"])
        del doc["linger"]
        self.assertIsNone(controls.parse_services(json.dumps(doc)).linger_state)

    def test_refusals(self):
        for name in ("not-json", "an-array", "null", "wrong-kind", "no-rows", "row-not-object",
                     "row-without-name", "row-bad-scope"):
            with self.subTest(name):
                with self.assertRaises(controls.ControlsError):
                    controls.parse_services(SERVICES_POLLS[name][1])


class ParseRadios(unittest.TestCase):
    def test_the_d2_document(self):
        rows = radios("d2")
        self.assertEqual([r.name for r in rows], ["wwan", "wifi", "bluetooth"])
        self.assertEqual(
            (rows[0].present, rows[0].enabled, rows[0].method, rows[0].detail),
            (True, True, "nmcli", "cdc-wdm0"),
        )

    def test_refusals(self):
        for name in ("not-json", "an-array", "null", "wrong-kind", "no-rows", "row-without-name"):
            with self.subTest(name):
                with self.assertRaises(controls.ControlsError):
                    controls.parse_radios(RADIOS_POLLS[name][1])


class PollOutcome(unittest.TestCase):
    def outcome(self, kind, code, out, err, started=True, crashed=False):
        return controls.poll_outcome(kind, started, crashed, code, out, err)

    def each(self, kind, polls):
        return {n: self.outcome(kind, *p) for n, p in polls.items()}

    def test_good_documents(self):
        for kind, polls in (("services", SERVICES_POLLS), ("radios", RADIOS_POLLS)):
            for name in ("ok", "newer-version"):
                with self.subTest(kind=kind, name=name):
                    out = self.outcome(kind, *polls[name])
                    self.assertIsNotNone(out.doc)
                    self.assertEqual((out.unsupported, out.error, out.keep), (False, "", False))

    def test_a_helper_without_the_verb_says_update_once_and_no_error(self):
        for kind, polls in (("services", SERVICES_POLLS), ("radios", RADIOS_POLLS)):
            out = self.outcome(kind, *polls["old-helper"])
            self.assertTrue(out.unsupported)
            self.assertEqual(out.error, "")
            self.assertIsNone(out.doc)

    def test_a_document_below_the_floor_is_unsupported_too(self):
        self.assertTrue(self.outcome("services", *SERVICES_POLLS["version-0"]).unsupported)
        self.assertTrue(self.outcome("radios", *RADIOS_POLLS["version-0"]).unsupported)

    def test_a_document_without_a_version_is_unsupported(self):
        self.assertTrue(self.outcome("services", *SERVICES_POLLS["no-version"]).unsupported)

    def test_no_helper_is_silent_here_the_device_poll_says_it(self):
        for kind, polls in (("services", SERVICES_POLLS), ("radios", RADIOS_POLLS)):
            out = self.outcome(kind, *polls["missing"])
            self.assertEqual((out.doc, out.unsupported, out.error, out.keep), (None, False, "", False))
        out = self.outcome("services", 0, "", "", started=False)
        self.assertEqual((out.doc, out.error), (None, ""))

    def test_a_refusal_that_is_not_a_missing_verb_is_an_error_not_an_update_line(self):
        # The helper's own exit 2 ("error: ...") must not read as "update".
        for kind, polls in (("services", SERVICES_POLLS), ("radios", RADIOS_POLLS)):
            out = self.outcome(kind, *polls["refused"])
            self.assertFalse(out.unsupported)
            self.assertEqual((out.error, out.keep), ("error: the Hammunition engine is not installed", True))

    def test_other_failures_keep_the_last_good_state_and_say_why(self):
        out = self.outcome("services", *SERVICES_POLLS["failed-with-stderr"])
        self.assertEqual((out.error, out.keep), ("error: boom", True))
        out = self.outcome("services", *SERVICES_POLLS["failed-silently"])
        self.assertEqual(out.error, controls.SERVICES_READ_ERROR)
        out = self.outcome("radios", *RADIOS_POLLS["failed-silently"])
        self.assertEqual(out.error, controls.RADIOS_READ_ERROR)
        out = self.outcome("services", 0, "", "", crashed=True)
        self.assertTrue(out.keep)

    def test_unreadable_output_is_a_parse_error_that_keeps_the_state(self):
        for name in ("not-json", "an-array", "null", "wrong-kind", "row-not-object"):
            out = self.outcome("services", *SERVICES_POLLS[name])
            self.assertEqual((out.error, out.keep), (controls.SERVICES_PARSE_ERROR, True), name)
        out = self.outcome("radios", *RADIOS_POLLS["not-json"])
        self.assertEqual(out.error, controls.RADIOS_PARSE_ERROR)

    def test_an_unknown_kind_is_a_bug_not_an_outcome(self):
        with self.assertRaises(ValueError):
            controls.poll_outcome("time", True, False, 0, "{}", "")


class Rules(unittest.TestCase):
    def test_a_running_service(self):
        r = row("gps-tether")
        self.assertTrue(controls.run_checked(r))
        self.assertTrue(controls.login_checked(r))
        self.assertEqual(controls.run_verb(r), "stop")
        self.assertEqual(controls.login_verb(r), "disable")
        self.assertTrue(controls.run_enabled(r, False))
        self.assertTrue(controls.login_enabled(r, False))

    def test_a_stopped_service_offers_start(self):
        r = services("stopped").rows[0]
        self.assertFalse(controls.run_checked(r))
        self.assertEqual(controls.run_verb(r), "start")

    def test_activating_counts_as_running_and_failed_does_not(self):
        self.assertTrue(controls.run_checked(services("starting").rows[0]))
        failed = services("failed").rows[0]
        self.assertFalse(controls.run_checked(failed))
        self.assertEqual(controls.run_verb(failed), "start")
        self.assertTrue(controls.run_enabled(failed, False))

    def test_disabled_at_login_offers_enable(self):
        r = services("disabled-at-login").rows[0]
        self.assertFalse(controls.login_checked(r))
        self.assertEqual(controls.login_verb(r), "enable")

    def test_a_not_installed_unit_has_nothing_to_switch(self):
        r = row("rig")
        self.assertFalse(controls.run_checked(r))
        self.assertFalse(controls.login_checked(r))
        self.assertFalse(controls.run_enabled(r, False))
        self.assertFalse(controls.login_enabled(r, False))

    def test_static_and_unknown_cannot_be_enabled_or_disabled(self):
        for name in ("static", "unknown-enabled", "future-states"):
            self.assertFalse(controls.login_enabled(services(name).rows[0], False), name)
            self.assertFalse(controls.login_checked(services(name).rows[0]), name)

    def test_an_unknown_running_state_is_not_toggled(self):
        self.assertFalse(controls.run_enabled(services("unknown-active").rows[0], False))

    def test_everything_is_disabled_while_acting(self):
        r = row("gps-tether")
        self.assertFalse(controls.run_enabled(r, True))
        self.assertFalse(controls.login_enabled(r, True))
        self.assertFalse(controls.radio_enabled(radios("on")[0], True))

    def test_detail_wording(self):
        self.assertEqual(controls.service_label(row("gps-tether")), "gps-tether")
        self.assertEqual(
            controls.service_detail(row("gps-tether")),
            "GPS position for QMapShack and the browser map on 127.0.0.1",
        )
        self.assertEqual(controls.service_detail(row("rig")), "rigctld for this operator: not installed")
        self.assertEqual(controls.service_detail(services("failed").rows[0]), "the gps-tether service: failed")
        self.assertEqual(controls.service_detail(services("starting").rows[0]), "the gps-tether service: starting")

    def test_radio_wording_and_state(self):
        wwan, wifi, bt = radios("d2")
        self.assertEqual(controls.radio_label(wwan), "Mobile broadband (WWAN)")
        self.assertEqual(controls.radio_label(wifi), "Wi-Fi")
        self.assertEqual(controls.radio_label(bt), "Bluetooth")
        self.assertEqual(controls.radio_detail(wwan), "cdc-wdm0")
        self.assertEqual(controls.radio_detail(wifi), "wlan0")
        self.assertEqual(controls.radio_detail(bt), "")
        self.assertEqual(controls.radio_verb(wwan), "off")
        self.assertEqual(controls.radio_verb(radios("off")[0]), "on")

    def test_a_radio_whose_tool_is_absent_names_it_and_is_disabled(self):
        r = radios("tool-missing")[0]
        self.assertEqual(controls.radio_detail(r), "not available: bluetoothctl is not installed")
        self.assertFalse(controls.radio_enabled(r, False))
        self.assertEqual(controls.radio_detail(radios("tool-missing-no-detail")[0]), "not available")

    def test_a_radio_this_tray_does_not_know_is_shown_never_offered(self):
        r = radios("unknown-radio")[0]
        self.assertEqual(controls.radio_label(r), "lora")
        self.assertFalse(controls.radio_enabled(r, False))


class Argv(unittest.TestCase):
    def test_user_scope_goes_straight_to_the_helper(self):
        self.assertEqual(
            controls.service_argv(PKEXEC, HELPER, row("gps-tether"), "stop"),
            (HELPER, ["services", "stop", "gps-tether"]),
        )

    def test_system_scope_goes_through_pkexec_by_path(self):
        self.assertEqual(
            controls.service_argv(PKEXEC, HELPER, row("gpsd"), "start"),
            (PKEXEC, [HELPER, "services", "start", "gpsd"]),
        )

    def test_the_four_verbs_and_no_other(self):
        r = row("gps-tether")
        for verb in ("start", "stop", "enable", "disable"):
            controls.service_argv(PKEXEC, HELPER, r, verb)
        for verb in ("state", "restart", "mask", "", "start ", "linger"):
            with self.assertRaises(ValueError, msg=verb):
                controls.service_argv(PKEXEC, HELPER, r, verb)

    def test_a_name_that_is_not_a_service_name_never_reaches_a_command(self):
        for name in ("", "-x", "X", "a b", "a;b", "a$(id)", "a`id`", "a\nb", "a/b", "a" * 65, "gps_tether"):
            r = controls.ServiceRow(name, "u.service", "user", "d", "active", "enabled", False)
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    controls.service_argv(PKEXEC, HELPER, r, "start")

    def test_a_scope_that_is_neither_is_refused(self):
        r = controls.ServiceRow("x", "u", "machine", "d", "active", "enabled", False)
        with self.assertRaises(ValueError):
            controls.service_argv(PKEXEC, HELPER, r, "start")

    def test_radios_are_direct_and_only_the_three_names(self):
        wwan = radios("d2")[0]
        self.assertEqual(controls.radio_argv(HELPER, wwan, False), (HELPER, ["radio", "off", "wwan"]))
        self.assertEqual(controls.radio_argv(HELPER, wwan, True), (HELPER, ["radio", "on", "wwan"]))
        self.assertEqual(controls.RADIO_NAMES, ("wwan", "wifi", "bluetooth"))
        with self.assertRaises(ValueError):
            controls.radio_argv(HELPER, radios("unknown-radio")[0], True)
        for name in ("wwan;id", "WIFI", "wifi ", ""):
            bad = controls.RadioRow(name, True, True, "nmcli", "")
            with self.assertRaises(ValueError, msg=name):
                controls.radio_argv(HELPER, bad, True)

    def test_the_polls_have_no_pkexec(self):
        self.assertEqual(controls.services_poll_argv(HELPER), (HELPER, ["services", "state"]))
        self.assertEqual(controls.radios_poll_argv(HELPER), (HELPER, ["radio", "state"]))
        self.assertEqual(logic.services_poll_argv(), (HELPER, ["services", "state"]))
        self.assertEqual(logic.radios_poll_argv(), (HELPER, ["radio", "state"]))


class Pending(unittest.TestCase):
    def test_the_optimistic_value_each_verb_expects(self):
        self.assertEqual(controls.service_pending("start", "x"), ("service:x:active", "active"))
        self.assertEqual(controls.service_pending("stop", "x"), ("service:x:active", "inactive"))
        self.assertEqual(controls.service_pending("enable", "x"), ("service:x:enabled", "enabled"))
        self.assertEqual(controls.service_pending("disable", "x"), ("service:x:enabled", "disabled"))
        self.assertEqual(controls.radio_pending("wwan", True), ("radio:wwan:enabled", True))
        self.assertEqual(controls.radio_pending("wwan", False), ("radio:wwan:enabled", False))

    def test_effective_services_shows_the_intent(self):
        rows = services("running").rows
        eff = controls.effective_services(rows, (controls.service_pending("stop", "gps-tether"),))
        self.assertFalse(controls.run_checked(eff[0]))
        self.assertTrue(controls.login_checked(eff[0]))
        eff = controls.effective_services(rows, (controls.service_pending("disable", "gps-tether"),))
        self.assertFalse(controls.login_checked(eff[0]))
        self.assertTrue(controls.run_checked(eff[0]))

    def test_effective_leaves_other_rows_and_the_real_rows_alone(self):
        rows = services("d2").rows
        eff = controls.effective_services(rows, (controls.service_pending("stop", "gpsd"),))
        self.assertEqual([r for r in eff if r.name != "gpsd"], [r for r in rows if r.name != "gpsd"])
        self.assertTrue(controls.run_checked(row("gpsd")))  # the real row is untouched

    def test_effective_radios(self):
        rows = radios("on")
        eff = controls.effective_radios(rows, (controls.radio_pending("wwan", False),))
        self.assertFalse(eff[0].enabled)
        self.assertTrue(rows[0].enabled)


class Transitions(unittest.TestCase):
    """toggle sent -> optimistic state -> the next poll confirms; a failed
    verb reverts and shows the helper's one-line error."""

    def run_entry(self, state, kind, prefix=None):
        return next(e for e in entries(state, kind) if prefix is None or e.text.startswith(prefix))

    def test_a_poll_fills_the_group(self):
        s = with_services("d2")
        self.assertEqual(len(s.services.rows), 5)
        self.assertFalse(s.services_unsupported)
        self.assertEqual(s.services_error, "")

    def test_a_toggle_is_optimistic_at_once(self):
        s = with_services("running")
        e = self.run_entry(s, "service-run")
        self.assertTrue(e.checked)
        s = logic.begin_control(s, e)
        self.assertTrue(s.acting)
        self.assertFalse(self.run_entry(s, "service-run").checked)
        self.assertFalse(self.run_entry(s, "service-run").enabled)

    def test_success_keeps_the_intent_until_the_next_poll_confirms(self):
        s = with_services("running")
        e = self.run_entry(s, "service-run")
        s = logic.begin_control(s, e)
        s = logic.apply_control(s, e, ok())
        self.assertFalse(s.acting)
        self.assertFalse(self.run_entry(s, "service-run").checked)
        self.assertEqual(s.action_error, "")
        confirmed = logic.apply_services_poll(s, ok(json.dumps(SERVICES["stopped"])))
        self.assertEqual(confirmed.pending, ())
        self.assertFalse(self.run_entry(confirmed, "service-run").checked)

    def test_the_poll_is_the_truth_even_when_it_disagrees(self):
        # The verb "worked" but systemd says otherwise: the poll wins.
        s = with_services("running")
        e = self.run_entry(s, "service-run")
        s = logic.apply_control(logic.begin_control(s, e), e, ok())
        s = logic.apply_services_poll(s, ok(json.dumps(SERVICES["running"])))
        self.assertTrue(self.run_entry(s, "service-run").checked)

    def test_a_poll_that_lands_mid_action_does_not_undo_the_intent(self):
        s = with_services("running")
        e = self.run_entry(s, "service-run")
        s = logic.begin_control(s, e)
        s = logic.apply_services_poll(s, ok(json.dumps(SERVICES["running"])))
        self.assertFalse(self.run_entry(s, "service-run").checked)

    def test_a_failed_verb_reverts_and_shows_the_one_line_error(self):
        s = with_services("running")
        e = self.run_entry(s, "service-run")
        s = logic.begin_control(s, e)
        s = logic.apply_control(s, e, ok(code=1, stderr="error: gps-tether: unit not found\nmore detail\n"))
        self.assertTrue(self.run_entry(s, "service-run").checked)
        self.assertEqual(s.pending, ())
        self.assertEqual(s.action_error, "error: gps-tether: unit not found")
        self.assertIn("error: gps-tether: unit not found", [x.text for x in entries(s, "error")])

    def test_a_failure_with_no_stderr_says_so(self):
        s = with_services("running")
        e = self.run_entry(s, "service-run")
        s = logic.apply_control(logic.begin_control(s, e), e, ok(code=3))
        self.assertEqual(s.action_error, "Action failed (exit 3)")

    def test_a_helper_that_cannot_run_is_one_line(self):
        s = with_services("running")
        e = self.run_entry(s, "service-run")
        s = logic.apply_control(logic.begin_control(s, e), e, ProcResult(started=False))
        self.assertEqual(s.action_error, controls.HELPER_RUN_ERROR)
        self.assertTrue(self.run_entry(s, "service-run").checked)

    def test_a_dismissed_pkexec_prompt_reverts_silently(self):
        s = with_services("d2")
        e = self.run_entry(s, "service-run", "gpsd")
        self.assertTrue(e.checked)
        for code in (126, 127):
            t = logic.begin_control(s, e)
            self.assertFalse(self.run_entry(t, "service-run", "gpsd").checked)
            t = logic.apply_control(t, e, ok(code=code))
            self.assertTrue(self.run_entry(t, "service-run", "gpsd").checked, code)
            self.assertEqual(t.action_error, "", code)

    def test_no_polkit_agent_is_said_for_a_system_service_too(self):
        s = with_services("d2")
        e = self.run_entry(s, "service-run", "gpsd")
        t = logic.apply_control(
            logic.begin_control(s, e), e,
            ok(code=127, stderr="Error executing command as another user: No authentication agent found.\n"),
            desktop="XFCE",
        )
        self.assertIn("No polkit authentication agent is running", t.action_error)
        self.assertTrue(self.run_entry(t, "service-run", "gpsd").checked)

    def test_a_failed_direct_127_is_not_read_as_pkexec(self):
        # A user-scope verb never goes through pkexec, so its 127 is the
        # helper missing, said as an error and reverted.
        s = with_services("running")
        e = self.run_entry(s, "service-run")
        s = logic.apply_control(logic.begin_control(s, e), e, ok(code=127, stderr="not found\n"))
        self.assertEqual(s.action_error, "not found")

    def test_the_login_checkbox_is_its_own_intent(self):
        s = with_services("running")
        e = self.run_entry(s, "service-login")
        self.assertTrue(e.checked)
        self.assertEqual(e.verb, "disable")
        s = logic.begin_control(s, e)
        self.assertFalse(self.run_entry(s, "service-login").checked)
        self.assertTrue(self.run_entry(s, "service-run").checked)

    def test_a_radio_toggle_and_its_failure(self):
        s = with_radios("on")
        e = entries(s, "radio")[0]
        self.assertTrue(e.checked)
        self.assertEqual(e.verb, "off")
        s = logic.begin_control(s, e)
        self.assertFalse(entries(s, "radio")[0].checked)
        failed = logic.apply_control(s, e, ok(code=1, stderr="Error: Radio switch is blocked\n"))
        self.assertTrue(entries(failed, "radio")[0].checked)
        self.assertEqual(failed.action_error, "Error: Radio switch is blocked")
        good = logic.apply_control(s, e, ok())
        self.assertFalse(entries(good, "radio")[0].checked)
        good = logic.apply_radios_poll(good, ok(json.dumps(RADIOS["off"])))
        self.assertEqual(good.pending, ())
        self.assertFalse(entries(good, "radio")[0].checked)

    def test_one_group_poll_never_clears_the_others_intent(self):
        s = with_radios("on", with_services("running"))
        e = self.run_entry(s, "service-run")
        s = logic.apply_control(logic.begin_control(s, e), e, ok())
        s = logic.apply_radios_poll(s, ok(json.dumps(RADIOS["on"])))
        self.assertFalse(self.run_entry(s, "service-run").checked)

    def test_a_new_action_clears_the_last_error(self):
        s = TrayState(action_error="old")
        e = self.run_entry(with_services("running"), "service-run")
        self.assertEqual(logic.begin_control(with_services("running", s), e).action_error, "")

    def test_control_argv_follows_the_entry(self):
        s = with_services("d2")
        self.assertEqual(
            logic.control_argv(self.run_entry(s, "service-run", "gps-tether")),
            (HELPER, ["services", "stop", "gps-tether"]),
        )
        self.assertEqual(
            logic.control_argv(self.run_entry(s, "service-login", "↳")),
            (HELPER, ["services", "disable", "gps-tether"]),
        )
        self.assertEqual(
            logic.control_argv(self.run_entry(s, "service-run", "gpsd")),
            (PKEXEC, [HELPER, "services", "stop", "gpsd"]),
        )
        r = with_radios("d2")
        self.assertEqual(logic.control_argv(entries(r, "radio")[0]), (HELPER, ["radio", "off", "wwan"]))

    def test_control_argv_refuses_an_entry_with_no_target(self):
        with self.assertRaises(ValueError):
            logic.control_argv(logic.MenuEntry("service-run", "x", verb="stop"))


class Group(unittest.TestCase):
    def test_unsupported_is_one_line_per_group_and_no_rows(self):
        s = logic.apply_services_poll(TrayState(devices=()), ok(code=2, stderr=SERVICES_POLLS["old-helper"][2]))
        s = logic.apply_radios_poll(s, ok(code=2, stderr=RADIOS_POLLS["old-helper"][2]))
        texts = [e.text for e in logic.menu_model(s)]
        self.assertEqual(texts.count("update hammunition-tray"), 2)
        self.assertEqual(entries(s, "service-run"), [])
        self.assertEqual(entries(s, "radio"), [])
        self.assertFalse(any("invalid choice" in t for t in texts))

    def test_unsupported_is_per_group(self):
        s = with_radios("d2", logic.apply_services_poll(TrayState(devices=()), OLD_SERVICES))
        texts = [e.text for e in logic.menu_model(s)]
        self.assertEqual(texts.count("update hammunition-tray"), 1)
        self.assertEqual(len(entries(s, "radio")), 3)

    def test_the_helper_arriving_clears_unsupported(self):
        s = logic.apply_services_poll(TrayState(devices=()), OLD_SERVICES)
        self.assertTrue(s.services_unsupported)
        s = logic.apply_services_poll(s, ok(json.dumps(SERVICES["running"])))
        self.assertFalse(s.services_unsupported)

    def test_a_failed_poll_keeps_the_rows_and_shows_its_own_error(self):
        s = with_services("running")
        s = logic.apply_services_poll(s, ok(code=1, stderr="error: boom\n"))
        self.assertEqual(len(s.services.rows), 1)
        self.assertEqual(s.services_error, "error: boom")
        self.assertIn("error: boom", [e.text for e in entries(s, "error")])
        # Neither of the others' errors is touched.
        self.assertEqual(s.last_error, "")
        self.assertEqual(s.radios_error, "")
        s = logic.apply_services_poll(s, ok(json.dumps(SERVICES["running"])))
        self.assertEqual(s.services_error, "")

    def test_each_group_has_its_own_error(self):
        s = logic.apply_radios_poll(with_services("running"), ok("not json"))
        self.assertEqual(s.radios_error, controls.RADIOS_PARSE_ERROR)
        self.assertEqual(s.services_error, "")

    def test_a_missing_helper_hides_both_groups(self):
        s = TrayState(helper_missing=True, services_unsupported=True)
        texts = [e.text for e in logic.menu_model(s)]
        self.assertNotIn("Services", texts)
        self.assertNotIn("Radios", texts)
        self.assertNotIn("update hammunition-tray", texts)

    def test_a_missing_helper_on_the_group_poll_changes_nothing(self):
        s = with_services("running")
        t = logic.apply_services_poll(s, ok(code=127))
        self.assertEqual(t.services, s.services)
        self.assertEqual(t.services_error, "")


class Menu(unittest.TestCase):
    def kinds(self, state):
        return [(e.kind, e.text) for e in logic.menu_model(state) if e.kind == "heading"]

    def test_one_controls_panel_three_groups_then_time(self):
        s = with_radios("d2", with_services("d2"))
        self.assertEqual(
            self.kinds(s),
            [("heading", "Controls"), ("heading", "Devices"), ("heading", "Services"),
             ("heading", "Radios"), ("heading", "Time")],
        )

    def test_the_groups_come_in_order(self):
        s = with_radios("d2", with_services("d2", TrayState(devices=(logic.Device("gnss-ublox", "1-4", "u-blox", False, False, True),))))
        order = [e.kind for e in logic.menu_model(s)]
        self.assertLess(order.index("toggle"), order.index("service-run"))
        self.assertLess(order.index("service-run"), order.index("radio"))
        self.assertLess(order.index("radio"), order.index("time"))
        self.assertEqual(order[-1], "quit")

    def test_devices_are_unchanged(self):
        s = logic.apply_poll(TrayState(), ok(json.dumps([{"name": "gnss-ublox", "summary": "u-blox", "address": "1-4",
                                                          "parked": False, "kept": False, "attached": True}])))[0]
        [e] = entries(s, "toggle")
        self.assertEqual((e.text, e.checked, e.verb), ("u-blox (1-4) — awake", True, "park"))

    def test_service_rows(self):
        s = with_services("d2")
        runs = entries(s, "service-run")
        logins = entries(s, "service-login")
        self.assertEqual(len(runs), 5)
        self.assertEqual(len(logins), 5)
        self.assertEqual(runs[0].text, "gps-tether — GPS position for QMapShack and the browser map on 127.0.0.1")
        self.assertEqual(logins[0].text, "↳ Start at login")
        self.assertEqual((runs[0].checked, runs[0].enabled, runs[0].verb), (True, True, "stop"))
        self.assertEqual((logins[0].checked, logins[0].enabled, logins[0].verb), (True, True, "disable"))

    def test_not_installed_rows_say_so_and_are_disabled(self):
        s = with_services("d2")
        [run] = [e for e in entries(s, "service-run") if e.text.startswith("rig")]
        self.assertIn("not installed", run.text)
        self.assertFalse(run.enabled)
        self.assertFalse(run.checked)
        [login] = [e for e in entries(s, "service-login") if e.service.name == "rig"]
        self.assertFalse(login.enabled)

    def test_radio_rows(self):
        s = with_radios("d2")
        texts = [(e.text, e.checked, e.enabled) for e in entries(s, "radio")]
        self.assertEqual(
            texts,
            [("Mobile broadband (WWAN) — cdc-wdm0", True, True),
             ("Wi-Fi — wlan0", True, True),
             ("Bluetooth", True, True)],
        )

    def test_an_absent_tool_row_names_the_tool_and_is_disabled(self):
        [e] = entries(with_radios("tool-missing"), "radio")
        self.assertEqual(e.text, "Bluetooth — not available: bluetoothctl is not installed")
        self.assertFalse(e.enabled)

    def test_before_the_first_poll_and_when_empty(self):
        texts = [e.text for e in logic.menu_model(TrayState(devices=()))]
        self.assertIn("Reading services…", texts)
        self.assertIn("Reading radios…", texts)
        texts = [e.text for e in logic.menu_model(with_radios("empty", with_services("empty")))]
        self.assertIn("No services are listed", texts)
        self.assertIn("No radios are listed", texts)

    def test_while_acting_every_control_is_disabled(self):
        s = with_radios("d2", with_services("d2"))
        s = logic.begin_action(s)
        for kind in ("service-run", "service-login", "radio"):
            self.assertTrue(all(not e.enabled for e in entries(s, kind)), kind)

    def test_the_menu_text_of_a_hostile_description_is_still_only_text(self):
        doc = doc_with(SERVICES["running"], "services", description="a & b\tc")
        s = logic.apply_services_poll(TrayState(devices=()), ok(json.dumps(doc)))
        [e] = entries(s, "service-run")
        self.assertIn("a & b", e.text.replace("\t", " "))


class Tooltip(unittest.TestCase):
    def test_the_tooltip_is_unchanged(self):
        self.assertEqual(
            logic.tooltip(with_services("d2")), "Hammunition Devices\nNo parkable device is attached"
        )


class RadiosDocBuilder(unittest.TestCase):
    def test_the_fixture_builder_is_what_the_parser_reads(self):
        self.assertEqual(len(controls.parse_radios(json.dumps(radios_doc())) ), 0)
        self.assertEqual(svc("a")["scope"], "user")


if __name__ == "__main__":
    unittest.main()
