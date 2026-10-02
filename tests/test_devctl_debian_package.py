"""The third .deb, hammunition-devctl: exactly its files, their modes, what it
depends on, and what its maintainer scripts do (run against a scratch root,
never /usr/local)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARE = "usr/share/hammunition-devctl"
MARK = "# Installed by hammunition-tray (hammunition-devctl, D-056)."


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
class DevctlDebianPackage(unittest.TestCase):
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
        cls.deb = cls.out / f"hammunition-devctl_{cls.version}_all.deb"
        cls.tree = cls.out / "x"
        subprocess.run(["dpkg-deb", "-x", str(cls.deb), str(cls.tree)], check=True)
        cls.control = cls.out / "c"
        subprocess.run(["dpkg-deb", "-e", str(cls.deb), str(cls.control)], check=True)

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

    def test_all_three_packages_are_built_at_one_version(self):
        for name in ("hammunition-tray", "hammunition-tray-qt", "hammunition-devctl"):
            self.assertTrue((self.out / f"{name}_{self.version}_all.deb").exists(), name)

    def test_control_fields(self):
        self.assertEqual(self.field("Package"), "hammunition-devctl")
        self.assertEqual(self.field("Architecture"), "all")
        self.assertEqual(self.field("Depends"), "python3 (>= 3.11), python3-yaml")
        self.assertIn("contract", self.field("Description"))

    def test_the_front_ends_recommend_it(self):
        for name in ("hammunition-tray", "hammunition-tray-qt"):
            out = subprocess.run(
                ["dpkg-deb", "-f", str(self.out / f"{name}_{self.version}_all.deb"), "Recommends"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(out, "hammunition-devctl", name)

    def test_exactly_the_listed_files(self):
        pkg = sorted(p.name for p in (ROOT / "devctl/hammunition_devctl").glob("*.py"))
        expected = {f"{SHARE}/hammunition_devctl/{name}" for name in pkg}
        expected |= {
            f"{SHARE}/hammunition-devctl",
            f"{SHARE}/wrapper",
            "usr/share/polkit-1/actions/com.chiefgyk3d.hammunition.devctl.policy",
            "usr/share/doc/hammunition-devctl/copyright",
            "usr/share/doc/hammunition-devctl/README.md",
            "usr/share/doc/hammunition-devctl/contract.md",
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
            elif path == f"./{SHARE}/hammunition-devctl":
                want = "-rwxr-xr-x"
            else:
                want = "-rw-r--r--"
            self.assertEqual(mode, want, line)

    def test_the_maintainer_scripts_are_executable_and_posix_sh(self):
        for name in ("postinst", "prerm"):
            path = self.control / name
            self.assertTrue(os.access(path, os.X_OK), name)
            self.assertEqual(path.read_text().splitlines()[0], "#!/bin/sh")
            subprocess.run(["sh", "-n", str(path)], check=True)

    def test_the_wrapper_and_the_policy_are_the_ones_install_sh_writes(self):
        sys_wrapper = (self.tree / SHARE / "wrapper").read_text()
        rendered = subprocess.run(
            [
                "python3",
                str(ROOT / "scripts/render_helper_files.py"),
                "wrapper",
                "/usr/bin/python3",
                f"/{SHARE}/hammunition-devctl",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(sys_wrapper, rendered)
        self.assertEqual(sys_wrapper.splitlines()[1], MARK)
        policy = (
            self.tree / "usr/share/polkit-1/actions/com.chiefgyk3d.hammunition.devctl.policy"
        ).read_text()
        self.assertIn("/usr/local/libexec/hammunition-devctl", policy)

    def _run_script(self, name, scratch, *args):
        """Run a maintainer script with its three absolute paths redirected into
        ``scratch``, so what it does to /usr/local can be seen without root."""
        text = (self.control / name).read_text()
        text = text.replace("/usr/local/libexec", str(scratch / "libexec"))
        text = text.replace(f"/{SHARE}/wrapper", str(self.tree / SHARE / "wrapper"))
        script = scratch / name
        script.write_text(text)
        return subprocess.run(
            ["sh", str(script), *args], capture_output=True, text=True, check=False
        )

    def test_postinst_writes_the_wrapper_and_prerm_removes_it(self):
        scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, scratch)
        done = self._run_script("postinst", scratch, "configure")
        self.assertEqual(done.returncode, 0, done.stderr)
        dest = scratch / "libexec" / "hammunition-devctl"
        self.assertEqual(oct(dest.stat().st_mode & 0o777), "0o755")
        self.assertEqual(dest.read_text().splitlines()[1], MARK)
        # idempotent
        self.assertEqual(self._run_script("postinst", scratch, "configure").returncode, 0)
        self.assertEqual(dest.read_text().splitlines()[1], MARK)
        self.assertEqual(self._run_script("prerm", scratch, "remove").returncode, 0)
        self.assertFalse(dest.exists())

    def test_a_foreign_wrapper_survives_both_scripts(self):
        scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, scratch)
        dest = scratch / "libexec" / "hammunition-devctl"
        dest.parent.mkdir()
        dest.write_text("#!/bin/sh\n# Installed by `hammunition hardware apply` (D-056).\n")
        done = self._run_script("postinst", scratch, "configure")
        self.assertEqual(done.returncode, 0)
        self.assertIn("another installer", done.stderr)
        self.assertIn("hardware apply", dest.read_text())
        self._run_script("prerm", scratch, "remove")
        self.assertTrue(dest.exists())

    def test_an_upgrade_keeps_the_wrapper(self):
        scratch = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, scratch)
        self._run_script("postinst", scratch, "configure")
        self._run_script("prerm", scratch, "upgrade", "0.5.0")
        self.assertTrue((scratch / "libexec" / "hammunition-devctl").exists())

    def test_the_installed_tree_runs_and_answers_its_version(self):
        done = subprocess.run(
            ["python3", "-I", str(self.tree / SHARE / "hammunition-devctl"), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.stdout, "hammunition-devctl contract 1\n", done.stderr)


if __name__ == "__main__":
    unittest.main()
