"""Static checks on the Plasma applet package.

These exist because the failures they catch are all invisible until the
applet is on a real panel, and two of them are properties of the *design*
rather than of the code: reading device state must never prompt, and
writing must always prompt.

The KConfigLoader trap is inherited from dell-battery-balance, where it
cost an afternoon: an XML comment inside main.xml makes KConfigLoader drop
the defaults of every entry after it, so a poll interval silently becomes
NaN and the timer never fires.
"""

import json
import os
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
PKG = os.path.join(ROOT, "plasmoid", "package")
UI = os.path.join(PKG, "contents", "ui")
MAIN_XML = os.path.join(PKG, "contents", "config", "main.xml")
METADATA = os.path.join(PKG, "metadata.json")
APPLET_ID = "com.chiefgyk3d.hammunition.devices"
HELPER = "/usr/local/libexec/hammunition-devctl"


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def qml_files():
    return sorted(f for f in os.listdir(UI) if f.endswith(".qml"))


class Metadata(unittest.TestCase):
    def test_metadata_is_valid_json(self):
        json.loads(read(METADATA))

    def test_the_id_is_the_one_the_scripts_install_and_remove(self):
        meta = json.loads(read(METADATA))
        self.assertEqual(meta["KPlugin"]["Id"], APPLET_ID)
        self.assertIn(APPLET_ID, read(os.path.join(ROOT, "install.sh")))
        self.assertIn(APPLET_ID, read(os.path.join(ROOT, "uninstall.sh")))

    def test_it_declares_plasma_6(self):
        meta = json.loads(read(METADATA))
        self.assertEqual(meta["X-Plasma-API-Minimum-Version"], "6.0")
        self.assertEqual(meta["KPackageStructure"], "Plasma/Applet")

    def test_the_licence_matches_the_repository(self):
        meta = json.loads(read(METADATA))
        self.assertEqual(meta["KPlugin"]["License"], "GPL-3.0-or-later")


class ConfigSchema(unittest.TestCase):
    def test_no_xml_comments_anywhere(self):
        # An XML comment makes KConfigLoader drop the defaults of every
        # entry after it. The failure is silent and the symptom is a NaN
        # interval, which looks like a QML bug rather than a schema one.
        self.assertNotIn("<!--", read(MAIN_XML))

    def test_every_entry_has_a_typed_default(self):
        ns = {"k": "http://www.kde.org/standards/kcfg/1.0"}
        entries = ET.parse(MAIN_XML).getroot().findall(".//k:entry", ns)
        self.assertTrue(entries, "the schema declares no entries at all")
        for entry in entries:
            name = entry.get("name")
            self.assertIsNotNone(entry.get("type"), f"{name} has no type")
            self.assertIsNotNone(entry.find("k:default", ns), f"{name} has no default")

    def test_the_poll_default_is_what_the_design_says(self):
        ns = {"k": "http://www.kde.org/standards/kcfg/1.0"}
        root = ET.parse(MAIN_XML).getroot()
        entry = root.find(".//k:entry[@name='pollSeconds']", ns)
        self.assertIsNotNone(entry, "pollSeconds is gone")
        self.assertEqual(entry.find("k:default", ns).text, "5")


class PrivilegeBoundary(unittest.TestCase):
    """The two properties that make this applet safe to run.

    Both are design decisions from D-056, and both are the kind of thing a
    refactor breaks silently -- a prompt on every poll is merely annoying
    until people start clicking through prompts without reading them.
    """

    def test_reading_state_never_goes_through_pkexec(self):
        # Reading sysfs needs no privilege; only writing does. A poll that
        # prompted every few seconds would train the operator to authorise
        # without looking, which is worse than no prompt at all.
        #
        # Asserted against refresh()'s body specifically, not by scanning
        # the file: the first version of this test grepped every line for
        # "pkexec" near "state" and flagged the dispatch guard that exists
        # precisely to tell the two apart.
        body = read(os.path.join(UI, "main.qml"))
        refresh = re.search(r"function refresh\(\)\s*\{(.*?)\n    \}", body, re.S)
        self.assertIsNotNone(refresh, "refresh() is gone or was renamed")
        self.assertNotIn("pkexec", refresh.group(1), "the poll escalates")
        self.assertIn("state", refresh.group(1), "refresh() no longer reads state")

    def test_park_and_wake_always_go_through_pkexec(self):
        body = read(os.path.join(UI, "main.qml"))
        act = re.search(r"function act\([^)]*\)\s*\{(.*?)\n    \}", body, re.S)
        self.assertIsNotNone(act, "act() is gone or was renamed")
        self.assertIn("pkexec", act.group(1), "act() no longer escalates")

    def test_the_helper_path_matches_the_one_hammunition_installs(self):
        # The polkit action authorises this exact path. If the applet polls
        # a different one, it silently reports the helper as missing forever.
        self.assertIn(HELPER, read(os.path.join(UI, "main.qml")))
        self.assertIn(HELPER, read(os.path.join(ROOT, "install.sh")))

    def test_a_dismissed_prompt_is_not_reported_as_an_error(self):
        # pkexec exits 126 when the dialog is dismissed and 127 when
        # authorisation is refused. Nothing was written in either case.
        body = read(os.path.join(UI, "main.qml"))
        self.assertIn("126", body)
        self.assertIn("127", body)

    def test_actions_name_the_device_by_address(self):
        # Two receivers of one class share a catalog name; the helper
        # refuses a bare name rather than guessing, so a switch that sent
        # one would simply stop working the moment a second is plugged in.
        body = read(os.path.join(UI, "main.qml"))
        self.assertRegex(body, r'name\s*\+\s*"@"\s*\+\s*\w+\.address')


class Qml(unittest.TestCase):
    def test_every_qml_file_carries_the_licence_header(self):
        for name in qml_files():
            self.assertIn(
                "SPDX-License-Identifier: GPL-3.0-or-later",
                read(os.path.join(UI, name)),
                f"{name} has no SPDX header",
            )

    def test_the_representations_metadata_names_exist(self):
        main = read(os.path.join(UI, "main.qml"))
        for prop, component in (
            ("compactRepresentation", "CompactRepresentation"),
            ("fullRepresentation", "FullRepresentation"),
        ):
            self.assertIn(prop, main, f"{prop} is not set")
            self.assertTrue(
                os.path.exists(os.path.join(UI, component + ".qml")),
                f"{component}.qml is referenced and missing",
            )

    def test_expanded_is_not_addressed_through_plasmoid(self):
        # `plasmoid.expanded` is not a property in Plasma 6; clicking the
        # icon silently never opens the popup. Inherited lesson.
        for name in qml_files():
            self.assertNotIn(
                "plasmoid.expanded",
                read(os.path.join(UI, name)),
                f"{name} uses plasmoid.expanded, which does not exist in Plasma 6",
            )

    def test_the_config_page_the_model_names_exists(self):
        config = read(os.path.join(PKG, "contents", "config", "config.qml"))
        for source in re.findall(r'source:\s*"([^"]+)"', config):
            self.assertTrue(
                os.path.exists(os.path.join(UI, source)),
                f"config.qml names {source}, which does not exist",
            )



ICONS = os.path.join(PKG, "contents", "icons")
SVG_NS = "{http://www.w3.org/2000/svg}"


class Icons(unittest.TestCase):
    """The penguin icon. Qt's SVG renderer, which Plasma draws icons with,
    silently ignores clipPath, mask and filter: the first draft clipped the
    hill to the disc with a clipPath and the hill spilled into the corners
    on screen while looking right in a browser."""

    UNSUPPORTED = {"clipPath", "mask", "filter", "foreignObject"}

    def svgs(self):
        return sorted(f for f in os.listdir(ICONS) if f.endswith(".svg"))

    def test_both_states_ship(self):
        self.assertEqual(
            self.svgs(),
            ["hammunition-devices-awake.svg", "hammunition-devices-parked.svg"],
        )

    def test_no_element_qt_ignores(self):
        for name in self.svgs():
            tree = ET.parse(os.path.join(ICONS, name))
            for el in tree.iter():
                tag = el.tag.replace(SVG_NS, "")
                self.assertNotIn(tag, self.UNSUPPORTED, f"{name} uses <{tag}>")
                self.assertNotIn("clip-path", el.attrib, f"{name} sets clip-path")
                self.assertNotIn("mask", el.attrib, f"{name} sets mask")

    def test_parked_has_no_signal_arcs(self):
        # The one visual difference that has to survive at 16 px.
        awake = read(os.path.join(ICONS, "hammunition-devices-awake.svg"))
        parked = read(os.path.join(ICONS, "hammunition-devices-parked.svg"))
        self.assertIn(" A8 8 ", awake)
        self.assertNotIn(" A8 8 ", parked)

    def test_every_icon_the_qml_names_exists(self):
        for name in qml_files():
            for rel in re.findall(r'"\.\./icons/([^"]+)"', read(os.path.join(UI, name))):
                self.assertTrue(
                    os.path.exists(os.path.join(ICONS, rel)),
                    f"{name} names icons/{rel}, which does not exist",
                )

    def test_install_puts_the_metadata_icon_where_the_name_resolves(self):
        icon = json.loads(read(METADATA))["KPlugin"]["Icon"]
        self.assertIn(f"/{icon}.svg", read(os.path.join(ROOT, "install.sh")))
        self.assertIn(f"/{icon}.svg", read(os.path.join(ROOT, "uninstall.sh")))


class KeptOff(unittest.TestCase):
    def test_the_notice_is_sent_at_most_once_per_load(self):
        main = read(os.path.join(UI, "main.qml"))
        self.assertIn("import org.kde.notification", main)
        self.assertIn("property bool keptNoticeSent: false", main)
        self.assertRegex(main, r"if \(!keptNoticeSent[^)]*\)")
        self.assertIn("keptNoticeSent = true", main)

    def test_an_absent_device_gets_no_switch(self):
        full = read(os.path.join(UI, "FullRepresentation.qml"))
        self.assertIn("visible: modelData.attached !== false", full)

    def test_an_absent_kept_device_can_be_forgotten(self):
        full = read(os.path.join(UI, "FullRepresentation.qml"))
        self.assertIn('i18n("Forget")', full)
        self.assertIn("root.forget(modelData)", full)

    def test_the_package_depends_on_the_notification_module(self):
        build = read(os.path.join(ROOT, "packaging", "debian", "build.sh"))
        self.assertIn("qml6-module-org-kde-notifications", build)


if __name__ == "__main__":
    unittest.main()


class ActionErrors(unittest.TestCase):
    """An action is followed at once by a poll. When one lastError served
    both, the poll cleared the action's error as it appeared, so a failed
    park or wake showed nothing. The two are kept apart now."""

    def poll_branch(self):
        main = read(os.path.join(UI, "main.qml"))
        start = main.index('if (kind === "devices")')
        end = main.index("// A park, a wake or a time mode finished", start)
        return main[start:end]

    def action_branch(self):
        main = read(os.path.join(UI, "main.qml"))
        start = main.index("// A park, a wake or a time mode finished")
        return main[start:main.index("\n    }", start)]

    def test_the_poll_never_touches_the_action_error(self):
        self.assertNotIn("actionError", self.poll_branch())

    def test_an_action_writes_its_error_to_its_own_property(self):
        action = self.action_branch()
        self.assertIn("actionError = stderr", action)
        self.assertNotIn("lastError", action)

    def test_the_next_action_clears_it(self):
        main = read(os.path.join(UI, "main.qml"))
        for fn in ("act", "forget"):
            body = re.search(rf"function {fn}\([^)]*\)\s*\{{(.*?)\n    \}}", main, re.S).group(1)
            self.assertIn('actionError = "";', body, fn)

    def test_the_popup_shows_it(self):
        full = read(os.path.join(UI, "FullRepresentation.qml"))
        self.assertIn("text: root.actionError", full)

    def test_no_polkit_agent_is_said(self):
        # Parity with the Qt tray; on Plasma the KDE agent is normally there.
        action = self.action_branch()
        self.assertIn("no authentication agent", action)
        self.assertIn("polkit-kde-agent-1", action)


class Time(unittest.TestCase):
    """The Time section (Hammunition D-058). The same two guarantees as the
    switches: reading never prompts, changing always does. Its wording and
    rules are timelogic.js, held to the Qt tray's by test_time_parity."""

    MODES = ["auto", "prefer-gps", "ntp-only", "gps-only"]

    def main(self):
        return read(os.path.join(UI, "main.qml"))

    def full(self):
        return read(os.path.join(UI, "FullRepresentation.qml"))

    def set_time_mode(self):
        found = re.search(r"function setTimeMode\([^)]*\)\s*\{(.*?)\n    \}", self.main(), re.S)
        self.assertIsNotNone(found, "setTimeMode() is gone or was renamed")
        return found.group(1)

    def test_the_time_poll_never_goes_through_pkexec(self):
        refresh = re.search(r"function refresh\(\)\s*\{(.*?)\n    \}", self.main(), re.S)
        self.assertIn('helper + " time state"', refresh.group(1))
        self.assertNotIn("pkexec", refresh.group(1))

    def test_a_mode_change_always_goes_through_pkexec_by_its_path(self):
        self.assertIn('"/usr/bin/pkexec " + helper + " time mode " + mode', self.set_time_mode())

    def test_only_the_engines_four_modes_can_reach_the_helper(self):
        found = re.search(r"readonly property var timeModes: \[([^\]]*)\]", self.main())
        self.assertIsNotNone(found)
        self.assertEqual(re.findall(r'"([^"]+)"', found.group(1)), self.MODES)
        body = self.set_time_mode()
        # The guard comes before the command is built.
        self.assertLess(body.index("timeModes.indexOf(mode) === -1"), body.index("exec.run"))

    def test_a_mode_change_clears_the_last_action_error(self):
        self.assertIn('actionError = "";', self.set_time_mode())

    def test_the_time_poll_has_its_own_error(self):
        main = self.main()
        self.assertIn('property string timeError: ""', main)
        branch = main[main.index('if (kind === "time")') : main.index('if (kind === "services" ||')]
        self.assertIn("timeError = out.error", branch)
        self.assertNotIn("lastError", branch)
        self.assertNotIn("actionError", branch)
        self.assertIn("text: root.timeError", self.full())

    def test_the_library_is_imported_where_it_is_used(self):
        for text in (self.main(), self.full()):
            self.assertIn('import "timelogic.js" as TimeLogic', text)
        self.assertTrue(os.path.exists(os.path.join(UI, "timelogic.js")))

    def test_the_library_is_a_pragma_library_with_a_licence_header(self):
        js = read(os.path.join(UI, "timelogic.js"))
        self.assertTrue(js.startswith(".pragma library\n"))
        self.assertIn("SPDX-License-Identifier: GPL-3.0-or-later", js)
        # A library script has no QML context: an i18n call in it would be
        # a ReferenceError on the panel, so it only ever calls tr().
        self.assertNotRegex(js, r"\bi18n\(")

    def test_the_section_is_in_the_popup(self):
        full = self.full()
        self.assertIn('i18n("Time")', full)
        self.assertIn("model: root.timeModes", full)
        self.assertIn("root.setTimeMode(", full)
        self.assertIn("TimeLogic.headline(root.timeState, root.timeUnsupported, root.tr)", full)
        self.assertIn("TimeLogic.notes(root.timeState, root.tr)", full)

    def test_greyed_and_disabled_follow_the_shared_rules(self):
        main = self.main()
        self.assertIn("TimeLogic.greyed(timeState)", main)
        self.assertIn("TimeLogic.canChoose(timeState, timeUnsupported)", main)
        full = self.full()
        self.assertIn("opacity: root.timeGreyed ? 0.6 : 1.0", full)
        self.assertIn("enabled: !root.acting && root.timeChoosable", full)

    def test_a_dismissed_prompt_leaves_the_reported_mode_checked(self):
        full = self.full()
        self.assertIn("checked = Qt.binding(() => root.timeState !== null && root.timeState.mode === modelData)", full)

    def test_no_rtc_is_in_the_tooltip(self):
        tip = self.main()[self.main().index("toolTipSubText:"):]
        self.assertIn("TimeLogic.rtcNote(timeState, root.tr)", tip)


class Controls(unittest.TestCase):
    """The Controls panel (helper contract v1). The same two guarantees as
    the switches: reading never prompts, and a system-scope change always
    does. Its wording and rules are controlslogic.js, held to the Qt tray's
    by test_controls_parity."""

    def main(self):
        return read(os.path.join(UI, "main.qml"))

    def full(self):
        return read(os.path.join(UI, "FullRepresentation.qml"))

    def refresh(self):
        found = re.search(r"function refresh\(\)\s*\{(.*?)\n    \}", self.main(), re.S)
        self.assertIsNotNone(found, "refresh() is gone or was renamed")
        return found.group(1)

    def test_one_tick_asks_for_all_four_documents_and_never_through_pkexec(self):
        body = self.refresh()
        for verb in (" state", " time state", " services state", " radio state"):
            self.assertIn(f'helper + "{verb}"', body)
        self.assertNotIn("pkexec", body)

    def test_a_system_service_goes_through_pkexec_by_its_path(self):
        self.assertIn('Controls.serviceArgv("/usr/bin/pkexec", helper, row, verb)', self.main())

    def test_a_radio_never_does(self):
        found = re.search(r"function setRadio\([^)]*\)\s*\{(.*?)\n    \}", self.main(), re.S)
        self.assertIsNotNone(found, "setRadio() is gone or was renamed")
        self.assertNotIn("pkexec", found.group(1))
        self.assertIn("Controls.radioArgv(helper, row, on)", found.group(1))

    def test_nothing_reaches_the_shell_string_unchecked(self):
        # The command is a shell string, so the argv comes only from the
        # library that refuses anything the helper would not accept.
        main = self.main()
        run = re.search(r"function runControl\([^)]*\)\s*\{(.*?)\n    \}", main, re.S).group(1)
        self.assertIn("exec.run(words.join(\" \"))", run)
        for fn in ("setService", "setRadio"):
            body = re.search(rf"function {fn}\([^)]*\)\s*\{{(.*?)\n    \}}", main, re.S).group(1)
            self.assertLess(body.index("Controls."), body.index("runControl("), fn)
            self.assertIn("catch", body, fn)
            self.assertNotIn("exec.run", body, fn)

    def test_each_poll_has_its_own_error_and_flag(self):
        main = self.main()
        for name in ("servicesError", "radiosError", "servicesUnsupported", "radiosUnsupported"):
            self.assertIn(f"property", main[main.index(name) - 30 : main.index(name)])
        branch = main[main.index('if (kind === "services" || kind === "radios")') : main.index('if (kind === "control")')]
        self.assertNotIn("lastError", branch)
        self.assertNotIn("actionError", branch)
        self.assertNotIn("timeError", branch)

    def test_a_failed_verb_takes_back_only_its_own_request(self):
        main = self.main()
        control = main[main.index('if (kind === "control")') : main.index('if (kind === "devices")')]
        self.assertIn("Controls.directError(code, stderr, root.tr)", control)
        self.assertIn("dropInflight()", control)
        # A pkexec verb (a system service) is an action: a dismissed prompt
        # takes the request back too.
        action = main[main.index("if (inflight.length > 0)") :]
        self.assertIn("dropInflight()", action[:200])

    def test_a_poll_mid_verb_does_not_take_the_request_off_the_screen(self):
        body = re.search(r"function dropPending\([^)]*\)\s*\{(.*?)\n    \}", self.main(), re.S).group(1)
        self.assertIn("if (acting) return;", body)

    def test_the_library_is_imported_where_it_is_used(self):
        for text in (self.main(), self.full()):
            self.assertIn('import "controlslogic.js" as Controls', text)

    def test_the_library_is_a_pragma_library_with_a_licence_header(self):
        js = read(os.path.join(UI, "controlslogic.js"))
        self.assertTrue(js.startswith(".pragma library\n"))
        self.assertIn("SPDX-License-Identifier: GPL-3.0-or-later", js)
        self.assertNotRegex(js, r"\bi18n\(")

    def test_the_panel_is_one_panel_with_three_groups_and_a_scroll(self):
        full = self.full()
        self.assertIn("root.controlStrings.heading", full)
        for group in ("group_devices", "group_services", "group_radios"):
            self.assertIn(f"root.controlStrings.{group}", full)
        self.assertIn("PlasmaComponents.ScrollView", full)
        self.assertNotIn('i18n("Radio devices")', full)
        self.assertIn("Controls.strings(tr)", self.main())

    def test_each_service_has_a_running_switch_and_a_login_checkbox(self):
        full = self.full()
        self.assertIn("PlasmaComponents.CheckBox", full)
        self.assertIn("root.controlStrings.login_label", full)
        self.assertIn("root.setService(row, Controls.runVerb(row))", full)
        self.assertIn("root.setService(row, Controls.loginVerb(row))", full)
        self.assertIn("root.setRadio(row, wantOn)", full)

    def test_the_rows_drawn_are_the_pending_overlay_not_the_helpers_rows(self):
        main, full = self.main(), self.full()
        self.assertIn("Controls.effectiveServices(servicesRows, pending)", main)
        self.assertIn("Controls.effectiveRadios(radiosRows, pending)", main)
        self.assertIn("root.effectiveServices", full)
        self.assertIn("root.effectiveRadios", full)
        self.assertNotIn("root.servicesRows", full)
        self.assertNotIn("root.radiosRows", full)

    def test_a_dismissed_prompt_leaves_the_truth_checked(self):
        full = self.full()
        self.assertIn("checked = Qt.binding(() => Controls.runChecked(modelData))", full)
        self.assertIn("checked = Qt.binding(() => Controls.loginChecked(modelData))", full)
        self.assertIn("checked = Qt.binding(() => modelData.enabled)", full)

    def test_an_absent_radio_and_a_missing_service_are_disabled_by_the_shared_rules(self):
        full = self.full()
        self.assertIn("enabled: Controls.radioEnabled(modelData, root.acting)", full)
        self.assertIn("enabled: Controls.runEnabled(modelData, root.acting)", full)
        self.assertIn("enabled: Controls.loginEnabled(modelData, root.acting)", full)

    def test_a_helper_without_the_verb_is_one_line_per_group(self):
        full = self.full()
        self.assertEqual(full.count("text: root.controlStrings.update"), 2)
        self.assertIn("root.servicesUnsupported", full)
        self.assertIn("root.radiosUnsupported", full)
