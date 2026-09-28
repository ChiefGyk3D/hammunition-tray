"""The .deb carries exactly what the spec lists, and declares what it needs."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPLET = "usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices"
APPLET_FILES = {
    "metadata.json",
    "contents/config/config.qml",
    "contents/config/main.xml",
    "contents/icons/hammunition-devices-awake.svg",
    "contents/icons/hammunition-devices-parked.svg",
    "contents/ui/CompactRepresentation.qml",
    "contents/ui/FullRepresentation.qml",
    "contents/ui/configGeneral.qml",
    "contents/ui/main.qml",
}


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
class DebianPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        subprocess.run([str(ROOT / "packaging/debian/build.sh"), str(cls.out)], check=True)
        meta = json.loads((ROOT / "plasmoid/package/metadata.json").read_text())
        cls.deb = cls.out / f"hammunition-tray_{meta['KPlugin']['Version']}_all.deb"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def field(self, name):
        return subprocess.run(
            ["dpkg-deb", "-f", str(self.deb), name], capture_output=True, text=True, check=True
        ).stdout.strip()

    def files(self):
        listing = subprocess.run(
            ["dpkg-deb", "--contents", str(self.deb)], capture_output=True, text=True, check=True
        ).stdout
        return {
            line.split()[-1].removeprefix("./")
            for line in listing.splitlines()
            if not line.startswith("d")
        }

    def test_the_file_is_named_from_the_metadata_version(self):
        self.assertTrue(self.deb.exists(), self.deb)

    def test_control_fields(self):
        self.assertEqual(self.field("Package"), "hammunition-tray")
        self.assertEqual(self.field("Architecture"), "all")
        depends = self.field("Depends")
        for dep in (
            "plasma-workspace (>= 4:6)",
            "qml6-module-org-kde-plasma-plasma5support",
            "qml6-module-org-kde-kirigami",
            "qml6-module-org-kde-notifications",
        ):
            self.assertIn(dep, depends)
        self.assertIn("hammunition hardware apply", self.field("Description"))

    def test_exactly_the_listed_files(self):
        # Written out, not derived from `git ls-files`: derived from the same
        # source the build copies from, a committed stray file would ship and
        # this would still pass. A new applet file is added here on purpose.
        expected = {APPLET + "/" + f for f in APPLET_FILES}
        expected |= {
            "usr/share/icons/hicolor/scalable/apps/hammunition-devices.svg",
            "usr/share/doc/hammunition-tray/copyright",
            "usr/share/doc/hammunition-tray/README.md",
        }
        self.assertEqual(self.files(), expected)

    def test_modes_and_owners_do_not_depend_on_the_builders_umask(self):
        listing = subprocess.run(
            ["dpkg-deb", "--contents", str(self.deb)], capture_output=True, text=True, check=True
        ).stdout
        for line in listing.splitlines():
            mode, owner, *_ , path = line.split()
            self.assertEqual(owner, "root/root", line)
            want = "drwxr-xr-x" if mode.startswith("d") else "-rw-r--r--"
            self.assertEqual(mode, want, line)

    def test_no_maintainer_scripts(self):
        control = subprocess.run(
            ["dpkg-deb", "--ctrl-tarfile", str(self.deb)], capture_output=True, check=True
        ).stdout
        listing = subprocess.run(
            ["tar", "-t"], input=control, capture_output=True, check=True
        ).stdout.decode()
        for script in ("preinst", "postinst", "prerm", "postrm"):
            self.assertNotIn(script, listing)


if __name__ == "__main__":
    unittest.main()
