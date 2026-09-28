"""The Qt tray's pure logic, tested without a display.

Every rule here is one the Plasma applet already follows (main.qml). The
tray is a second client of the same helper, so nothing about consent,
privilege or what counts as an error may differ between the two.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "qt"))

from hammunition_tray_qt import logic  # noqa: E402
from hammunition_tray_qt.logic import (  # noqa: E402
    Device,
    ProcResult,
    TrayState,
)


def dev(**kw):
    row = {
        "name": "gnss-ublox",
        "summary": "u-blox GNSS receiver",
        "address": "1-4",
        "identifier": "1546:01a8",
        "method": "usb_deauthorize",
        "parked": False,
        "kept": False,
        "attached": True,
    }
    row.update(kw)
    return row


def ok(stdout="", code=0, stderr=""):
    return ProcResult(started=True, crashed=False, code=code, stdout=stdout, stderr=stderr)


def polled(*rows, state=None):
    new, _ = logic.apply_poll(state or TrayState(), ok(json.dumps(list(rows))))
    return new


class Constants(unittest.TestCase):
    def test_the_helper_is_the_path_hammunition_installs(self):
        self.assertEqual(logic.HELPER, "/usr/local/libexec/hammunition-devctl")

    def test_the_helper_path_is_the_one_the_applet_polls(self):
        main = (ROOT / "plasmoid/package/contents/ui/main.qml").read_text()
        self.assertIn(f'"{logic.HELPER}"', main)

    def test_the_poll_is_five_seconds(self):
        self.assertEqual(logic.POLL_MS, 5000)


class ParseState(unittest.TestCase):
    def test_the_helpers_shape(self):
        [d] = logic.parse_state(json.dumps([dev(parked=True, kept=True)]))
        self.assertEqual(
            d,
            Device(
                name="gnss-ublox",
                address="1-4",
                summary="u-blox GNSS receiver",
                parked=True,
                kept=True,
                attached=True,
            ),
        )

    def test_an_empty_array_is_no_devices(self):
        self.assertEqual(logic.parse_state("[]"), ())

    def test_an_absent_kept_row(self):
        # The helper's row for a kept device that is unplugged: no summary,
        # parked is null, attached is false.
        [d] = logic.parse_state(json.dumps([dev(summary="", parked=None, kept=True, attached=False)]))
        self.assertFalse(d.attached)
        self.assertFalse(d.parked)
        self.assertEqual(d.label, "gnss-ublox")

    def test_a_missing_attached_field_means_attached(self):
        # main.qml tests `attached !== false`; an older helper that never
        # printed the field listed only attached devices.
        row = dev()
        del row["attached"]
        [d] = logic.parse_state(json.dumps([row]))
        self.assertTrue(d.attached)

    def test_the_label_is_the_summary_or_the_name(self):
        self.assertEqual(logic.parse_state(json.dumps([dev()]))[0].label, "u-blox GNSS receiver")

    def test_not_json_is_refused(self):
        with self.assertRaises(logic.StateError):
            logic.parse_state("note: something else answered")

    def test_not_an_array_is_refused(self):
        with self.assertRaises(logic.StateError):
            logic.parse_state('{"name": "x"}')

    def test_a_row_that_is_not_an_object_is_refused(self):
        with self.assertRaises(logic.StateError):
            logic.parse_state('["gnss-ublox"]')

    def test_a_row_without_a_string_name_or_address_is_refused(self):
        for bad in (dev(name=None), dev(address=4)):
            with self.assertRaises(logic.StateError):
                logic.parse_state(json.dumps([bad]))


class Target(unittest.TestCase):
    """NAME@ADDRESS, always, and only in a shape the helper itself accepts."""

    def device(self, name="gnss-ublox", address="1-4"):
        return Device(name=name, address=address, summary="", parked=False, kept=False, attached=True)

    def test_always_qualified(self):
        self.assertEqual(logic.target(self.device()), "gnss-ublox@1-4")

    def test_a_hub_port_address(self):
        self.assertEqual(logic.target(self.device(address="3-1.2.4")), "gnss-ublox@3-1.2.4")

    def test_refuses_anything_else(self):
        for name, address in (
            ("", "1-4"),
            ("-rf", "1-4"),
            ("GNSS", "1-4"),
            ("gnss ublox", "1-4"),
            ("gnss;id", "1-4"),
            ("gnss@x", "1-4"),
            ("gnss\n", "1-4"),
            ("gnss-ublox", ""),
            ("gnss-ublox", "1-4 --help"),
            ("gnss-ublox", "../1-4"),
            ("gnss-ublox", "0000:00:14.0"),
            ("gnss-ublox", "1-4\n"),
            ("a" * 65, "1-4"),
        ):
            with self.subTest(name=name, address=address):
                with self.assertRaises(ValueError):
                    logic.target(self.device(name, address))

    def test_the_argv_is_exactly_helper_verb_target(self):
        program, args = logic.action_argv("park", self.device())
        self.assertEqual(program, "pkexec")
        self.assertEqual(args, ["/usr/local/libexec/hammunition-devctl", "park", "gnss-ublox@1-4"])
        self.assertEqual(logic.action_argv("wake", self.device())[1][1], "wake")

    def test_no_other_verb(self):
        for verb in ("state", "apply", "park ", ""):
            with self.assertRaises(ValueError):
                logic.action_argv(verb, self.device())

    def test_the_poll_argv_has_no_pkexec(self):
        # Reading sysfs needs no privilege. A poll that prompted every five
        # seconds would train the operator to authorise without reading.
        self.assertEqual(logic.poll_argv(), ("/usr/local/libexec/hammunition-devctl", ["state"]))


class Poll(unittest.TestCase):
    def test_devices_arrive(self):
        s = polled(dev())
        self.assertEqual(len(s.devices), 1)
        self.assertFalse(s.helper_missing)
        self.assertEqual(s.last_error, "")

    def test_127_means_the_helper_is_missing(self):
        s, _ = logic.apply_poll(polled(dev()), ok(code=127))
        self.assertTrue(s.helper_missing)
        self.assertIsNone(s.devices)

    def test_a_helper_that_cannot_be_started_is_missing(self):
        # QProcess never gets an exit code for a path that does not exist;
        # it reports failure to start, which is the same fact.
        s, _ = logic.apply_poll(TrayState(), ProcResult(started=False))
        self.assertTrue(s.helper_missing)

    def test_the_helper_coming_back_clears_missing(self):
        s, _ = logic.apply_poll(TrayState(), ok(code=127))
        s, _ = logic.apply_poll(s, ok("[]"))
        self.assertFalse(s.helper_missing)
        self.assertEqual(s.devices, ())

    def test_another_failure_shows_stderr_and_keeps_the_last_list(self):
        before = polled(dev())
        s, _ = logic.apply_poll(before, ok(code=1, stderr="error: boom\n"))
        self.assertEqual(s.last_error, "error: boom")
        self.assertEqual(s.devices, before.devices)

    def test_a_failure_with_no_stderr_says_so(self):
        s, _ = logic.apply_poll(TrayState(), ok(code=2))
        self.assertEqual(s.last_error, "Could not read device state")

    def test_unparseable_output(self):
        s, _ = logic.apply_poll(TrayState(), ok("hello"))
        self.assertEqual(s.last_error, "Could not parse the device list")
        self.assertIsNone(s.devices)

    def test_a_good_poll_clears_an_old_error(self):
        s, _ = logic.apply_poll(TrayState(), ok("hello"))
        s, _ = logic.apply_poll(s, ok("[]"))
        self.assertEqual(s.last_error, "")


class KeptNotice(unittest.TestCase):
    """Once per run, on the first successful poll, never again."""

    def test_named_on_the_first_poll(self):
        rows = json.dumps([dev(parked=True, kept=True), dev(name="modem", summary="", address="2-1", parked=True, kept=True)])
        s, notice = logic.apply_poll(TrayState(), ok(rows))
        self.assertEqual(notice, "u-blox GNSS receiver, modem")
        self.assertTrue(s.kept_notice_sent)

    def test_never_twice(self):
        rows = json.dumps([dev(parked=True, kept=True)])
        s, _ = logic.apply_poll(TrayState(), ok(rows))
        _, notice = logic.apply_poll(s, ok(rows))
        self.assertIsNone(notice)

    def test_a_device_kept_later_is_not_announced(self):
        s, first = logic.apply_poll(TrayState(), ok(json.dumps([dev()])))
        self.assertIsNone(first)
        self.assertTrue(s.kept_notice_sent)
        _, later = logic.apply_poll(s, ok(json.dumps([dev(parked=True, kept=True)])))
        self.assertIsNone(later)

    def test_a_failed_poll_does_not_use_up_the_notice(self):
        s, _ = logic.apply_poll(TrayState(), ok(code=127))
        s, _ = logic.apply_poll(s, ok(code=1))
        s, _ = logic.apply_poll(s, ok("junk"))
        self.assertFalse(s.kept_notice_sent)
        _, notice = logic.apply_poll(s, ok(json.dumps([dev(parked=True, kept=True)])))
        self.assertEqual(notice, "u-blox GNSS receiver")

    def test_an_unplugged_kept_device_is_not_announced(self):
        rows = json.dumps([dev(summary="", parked=None, kept=True, attached=False)])
        _, notice = logic.apply_poll(TrayState(), ok(rows))
        self.assertIsNone(notice)


class Action(unittest.TestCase):
    def test_begin_marks_acting_and_clears_the_error(self):
        s = logic.begin_action(TrayState(last_error="old"))
        self.assertTrue(s.acting)
        self.assertEqual(s.last_error, "")

    def test_success(self):
        s = logic.apply_action(logic.begin_action(TrayState()), ok())
        self.assertFalse(s.acting)
        self.assertEqual(s.last_error, "")

    def test_a_dismissed_or_refused_prompt_is_not_an_error(self):
        for code in (126, 127):
            s = logic.apply_action(logic.begin_action(TrayState()), ok(code=code, stderr="Not authorized"))
            self.assertFalse(s.acting)
            self.assertEqual(s.last_error, "", code)

    def test_anything_else_shows_stderr(self):
        s = logic.apply_action(TrayState(acting=True), ok(code=2, stderr="error: ambiguous\n"))
        self.assertEqual(s.last_error, "error: ambiguous")

    def test_without_stderr_the_exit_code(self):
        s = logic.apply_action(TrayState(acting=True), ok(code=3))
        self.assertEqual(s.last_error, "Action failed (exit 3)")

    def test_pkexec_that_cannot_start(self):
        s = logic.apply_action(TrayState(acting=True), ProcResult(started=False))
        self.assertFalse(s.acting)
        self.assertIn("pkexec", s.last_error)

    def test_a_crash_is_an_error(self):
        s = logic.apply_action(TrayState(acting=True), ProcResult(started=True, crashed=True, code=0))
        self.assertNotEqual(s.last_error, "")


class IconAndTooltip(unittest.TestCase):
    def test_missing_helper_is_the_warning_icon(self):
        self.assertEqual(logic.icon_name(TrayState(helper_missing=True)), "dialog-warning")

    def test_parked_when_any_attached_device_is_parked(self):
        self.assertEqual(logic.icon_name(polled(dev(), dev(address="1-5", parked=True))), logic.ICON_PARKED)

    def test_awake_otherwise(self):
        self.assertEqual(logic.icon_name(TrayState()), logic.ICON_AWAKE)
        self.assertEqual(logic.icon_name(polled(dev())), logic.ICON_AWAKE)
        # An unplugged kept device is not "parked" on this machine now.
        self.assertEqual(
            logic.icon_name(polled(dev(parked=None, kept=True, attached=False))), logic.ICON_AWAKE
        )

    def test_the_icon_names_are_distinct_from_the_applets(self):
        self.assertNotEqual(logic.ICON_AWAKE, "hammunition-devices")
        self.assertNotEqual(logic.ICON_PARKED, "hammunition-devices")
        self.assertNotEqual(logic.ICON_AWAKE, logic.ICON_PARKED)

    def test_tooltip_texts_are_the_applets(self):
        cases = (
            (TrayState(helper_missing=True), "Hammunition's device helper is not installed"),
            (TrayState(), "Reading device state…"),
            (polled(), "No parkable device is attached"),
            (polled(dev(parked=True)), "1 device parked"),
            (polled(dev(parked=True), dev(address="1-5", parked=True)), "2 devices parked"),
            (polled(dev()), "0 devices parked"),
        )
        for state, sub in cases:
            with self.subTest(sub=sub):
                self.assertEqual(logic.tooltip(state), f"Hammunition Devices\n{sub}")


class Menu(unittest.TestCase):
    def texts(self, state):
        return [e.text for e in logic.menu_model(state) if e.kind != "separator"]

    def test_helper_missing_says_what_to_run(self):
        entries = logic.menu_model(TrayState(helper_missing=True))
        self.assertIn("Device control is not installed", [e.text for e in entries])
        self.assertTrue(any("hammunition hardware apply" in e.text for e in entries))
        self.assertFalse(any(e.kind in ("toggle", "forget") for e in entries))
        self.assertEqual(entries[-1].kind, "quit")

    def test_before_the_first_poll(self):
        self.assertIn("Reading device state…", self.texts(TrayState()))

    def test_no_devices(self):
        self.assertIn("No parkable device is attached", self.texts(polled()))

    def test_a_switch_per_attached_device(self):
        [e] = [e for e in logic.menu_model(polled(dev())) if e.kind == "toggle"]
        self.assertEqual(e.text, "u-blox GNSS receiver (1-4) — awake")
        self.assertTrue(e.checked)
        self.assertEqual(e.verb, "park")
        self.assertTrue(e.enabled)

    def test_parked(self):
        [e] = [e for e in logic.menu_model(polled(dev(parked=True))) if e.kind == "toggle"]
        self.assertEqual(e.text, "u-blox GNSS receiver (1-4) — parked")
        self.assertFalse(e.checked)
        self.assertEqual(e.verb, "wake")

    def test_kept_off(self):
        [e] = [e for e in logic.menu_model(polled(dev(parked=True, kept=True))) if e.kind == "toggle"]
        self.assertEqual(e.text, "u-blox GNSS receiver (1-4) — kept off")
        self.assertEqual(e.verb, "wake")

    def test_kept_but_awake_still_says_kept_off(self):
        # FullRepresentation.qml labels from `kept` first; only the switch
        # shows `parked`. A device re-authorised outside the helper is awake
        # with its keep rule still in place, and the operator must see both.
        [e] = [e for e in logic.menu_model(polled(dev(parked=False, kept=True))) if e.kind == "toggle"]
        self.assertEqual(e.text, "u-blox GNSS receiver (1-4) — kept off")
        self.assertTrue(e.checked)
        self.assertEqual(e.verb, "park")

    def test_an_unplugged_kept_device_offers_forget_which_is_wake(self):
        state = polled(dev(summary="", parked=None, kept=True, attached=False))
        entries = logic.menu_model(state)
        self.assertFalse(any(e.kind == "toggle" for e in entries))
        [e] = [e for e in entries if e.kind == "forget"]
        self.assertEqual(e.text, "Forget gnss-ublox (1-4) — kept off, not attached")
        self.assertEqual(e.verb, "wake")
        self.assertIsNone(e.checked)

    def test_everything_is_disabled_while_acting(self):
        state = logic.begin_action(polled(dev(), dev(address="2-1", parked=None, kept=True, attached=False)))
        for e in logic.menu_model(state):
            if e.kind in ("toggle", "forget"):
                self.assertFalse(e.enabled)

    def test_the_last_error_is_shown(self):
        s, _ = logic.apply_poll(polled(dev()), ok(code=1, stderr="error: boom"))
        [e] = [e for e in logic.menu_model(s) if e.kind == "error"]
        self.assertEqual(e.text, "error: boom")

    def test_the_reboot_sentence(self):
        self.assertIn("Off stays off across reboots until you turn it back on.", self.texts(polled(dev())))
        self.assertNotIn(
            "Off stays off across reboots until you turn it back on.",
            self.texts(TrayState(helper_missing=True)),
        )

    def test_the_model_is_comparable_so_an_open_menu_is_not_rebuilt_needlessly(self):
        self.assertEqual(logic.menu_model(polled(dev())), logic.menu_model(polled(dev())))


class Qml(unittest.TestCase):
    """The sentences are the applet's own; a change there should be a change here."""

    def test_the_shared_sentences_appear_in_the_applet(self):
        ui = ROOT / "plasmoid/package/contents/ui"
        qml = (ui / "main.qml").read_text() + (ui / "FullRepresentation.qml").read_text()
        for sentence in (
            "Hammunition's device helper is not installed",
            "Reading device state…",
            "No parkable device is attached",
            "Device control is not installed",
            "Could not read device state",
            "Could not parse the device list",
            "Off stays off across reboots until you turn it back on.",
            "Kept off",
            "Forget",
        ):
            self.assertIn(sentence, qml)


if __name__ == "__main__":
    unittest.main()
