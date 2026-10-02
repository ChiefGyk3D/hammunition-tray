"""The second .deb, hammunition-tray-qt: exactly its files, their modes,
what it declares it needs, and that it never starts a second tray in Plasma."""

import configparser
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = "usr/share/hammunition-tray-qt/hammunition_tray_qt"
AUTOSTART = "etc/xdg/autostart/hammunition-tray-qt.desktop"
LAUNCHER = "usr/bin/hammunition-tray-qt"


def desktop(text):
    parser = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    parser.optionxform = str
    parser.read_string(text)
    return parser["Desktop Entry"]


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
class QtDebianPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        subprocess.run(
            [str(ROOT / "packaging/debian/build.sh"), str(cls.out)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        meta = json.loads((ROOT / "plasmoid/package/metadata.json").read_text())
        cls.version = meta["KPlugin"]["Version"]
        cls.deb = cls.out / f"hammunition-tray-qt_{cls.version}_all.deb"
        cls.tree = cls.out / "x"
        subprocess.run(["dpkg-deb", "-x", str(cls.deb), str(cls.tree)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def field(self, name):
        return subprocess.run(
            ["dpkg-deb", "-f", str(self.deb), name], capture_output=True, text=True, check=True
        ).stdout.strip()

    def listing(self):
        return subprocess.run(
            ["dpkg-deb", "--contents", str(self.deb)], capture_output=True, text=True, check=True
        ).stdout.splitlines()

    def control_members(self):
        control = subprocess.run(
            ["dpkg-deb", "--ctrl-tarfile", str(self.deb)], capture_output=True, check=True
        ).stdout
        return subprocess.run(["tar", "-t"], input=control, capture_output=True, check=True).stdout.decode()

    def test_both_packages_are_built_with_one_version(self):
        self.assertTrue(self.deb.exists(), self.deb)
        self.assertTrue((self.out / f"hammunition-tray_{self.version}_all.deb").exists())
        self.assertEqual(self.field("Version"), self.version)

    def test_control_fields(self):
        self.assertEqual(self.field("Package"), "hammunition-tray-qt")
        self.assertEqual(self.field("Architecture"), "all")
        self.assertEqual(
            self.field("Depends"), "python3 (>= 3.11), python3-pyqt6, pkexec | policykit-1"
        )
        self.assertIn("hammunition hardware apply", self.field("Description"))

    def test_exactly_the_listed_files(self):
        # Written out, not derived: a stray committed file under qt/ would
        # otherwise ship and this would still pass.
        expected = {
            LAUNCHER,
            f"{LIB}/__init__.py",
            f"{LIB}/__main__.py",
            f"{LIB}/controls.py",
            f"{LIB}/logic.py",
            f"{LIB}/timelogic.py",
            f"{LIB}/tray.py",
            "usr/share/applications/hammunition-tray-qt.desktop",
            AUTOSTART,
            "usr/share/icons/hicolor/scalable/apps/hammunition-tray-qt-awake.svg",
            "usr/share/icons/hicolor/scalable/apps/hammunition-tray-qt-parked.svg",
            "usr/share/doc/hammunition-tray-qt/copyright",
            "usr/share/doc/hammunition-tray-qt/README.md",
        }
        files = {
            line.split()[-1].removeprefix("./") for line in self.listing() if not line.startswith("d")
        }
        self.assertEqual(files, expected)

    def test_modes_and_owners(self):
        for line in self.listing():
            mode, owner, *_, path = line.split()
            self.assertEqual(owner, "root/root", line)
            if mode.startswith("d"):
                want = "drwxr-xr-x"
            elif path == f"./{LAUNCHER}":
                want = "-rwxr-xr-x"
            else:
                want = "-rw-r--r--"
            self.assertEqual(mode, want, line)

    def test_the_icons_are_the_applets_two(self):
        icons = ROOT / "plasmoid/package/contents/icons"
        apps = self.tree / "usr/share/icons/hicolor/scalable/apps"
        for state in ("awake", "parked"):
            self.assertEqual(
                (apps / f"hammunition-tray-qt-{state}.svg").read_bytes(),
                (icons / f"hammunition-devices-{state}.svg").read_bytes(),
            )

    def test_autostart_never_runs_in_plasma(self):
        # Plasma has the applet. A machine with Plasma and Xfce both
        # installed must not get two trays in Plasma.
        entry = desktop((self.tree / AUTOSTART).read_text())
        self.assertEqual(entry["NotShowIn"], "KDE;")
        self.assertEqual(entry["Type"], "Application")
        self.assertTrue(entry["Exec"].startswith("hammunition-tray-qt"))
        # Removed but not purged, the conffile stays; TryExec keeps login
        # from trying to run a program that is no longer there.
        self.assertEqual(entry["TryExec"], "hammunition-tray-qt")

    def test_the_autostart_file_is_a_conffile(self):
        self.assertIn("conffiles", self.control_members())
        conffiles = subprocess.run(
            ["dpkg-deb", "--info", str(self.deb), "conffiles"], capture_output=True, text=True, check=True
        ).stdout.split()
        self.assertEqual(conffiles, ["/" + AUTOSTART])

    def test_the_menu_entry(self):
        entry = desktop((self.tree / "usr/share/applications/hammunition-tray-qt.desktop").read_text())
        self.assertEqual(entry["Exec"], "hammunition-tray-qt")
        self.assertEqual(entry["Icon"], "hammunition-tray-qt-awake")
        self.assertNotIn("NotShowIn", entry)

    # The CI job that installs desktop-file-utils also sets
    # HAMMUNITION_REQUIRE_PYQT6; there a missing validator fails, not skips.
    @unittest.skipUnless(
        shutil.which("desktop-file-validate") or os.environ.get("HAMMUNITION_REQUIRE_PYQT6") == "1",
        "desktop-file-validate not installed",
    )
    def test_desktop_files_validate(self):
        for rel in ("usr/share/applications/hammunition-tray-qt.desktop", AUTOSTART):
            p = subprocess.run(
                ["desktop-file-validate", str(self.tree / rel)], capture_output=True, text=True
            )
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(p.stdout.strip(), "", p.stdout)

    def test_the_launcher_imports_from_the_installed_location_only(self):
        text = (self.tree / LAUNCHER).read_text()
        self.assertTrue(text.startswith("#!/usr/bin/python3 -I\n"), text.splitlines()[0])
        self.assertIn('"/usr/share/hammunition-tray-qt"', text)

    def test_the_launcher_writes_no_bytecode_into_the_package(self):
        # Measured in the Parrot container: run once as root, it left a
        # __pycache__ in /usr/share/hammunition-tray-qt that dpkg does not
        # own, so `apt remove` left the directory behind.
        text = (self.tree / LAUNCHER).read_text()
        self.assertLess(
            text.index("sys.dont_write_bytecode = True"), text.index("from hammunition_tray_qt")
        )

    def test_no_maintainer_scripts(self):
        members = self.control_members()
        for script in ("preinst", "postinst", "prerm", "postrm"):
            self.assertNotIn(script, members)


class PlasmaPackageUnchanged(unittest.TestCase):
    """The build grew a second package; the first must not notice."""

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
    def test_the_plasma_package_ships_no_qt_file(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out)
        subprocess.run(
            [str(ROOT / "packaging/debian/build.sh"), str(out)], check=True, stdout=subprocess.DEVNULL
        )
        [deb] = out.glob("hammunition-tray_*_all.deb")
        listing = subprocess.run(
            ["dpkg-deb", "--contents", str(deb)], capture_output=True, text=True, check=True
        ).stdout
        self.assertNotIn("hammunition-tray-qt", listing)
        self.assertNotIn("etc/", listing)


if __name__ == "__main__":
    unittest.main()
