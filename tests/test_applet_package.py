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
