"""The release job's version gate, runnable locally."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_version import check  # noqa: E402


class VersionGate(unittest.TestCase):
    def tree(self, version="0.1.0", changelog="## [0.1.0] - 2026-09-27\n"):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        meta = d / "plasmoid" / "package"
        meta.mkdir(parents=True)
        (meta / "metadata.json").write_text(json.dumps({"KPlugin": {"Version": version}}))
        (d / "CHANGELOG.md").write_text("# Changelog\n\n" + changelog)
        return d

    def test_agreeing_tag_passes(self):
        self.assertEqual(check("v0.1.0", self.tree()), "0.1.0")

    def test_tag_that_disagrees_with_metadata_fails(self):
        with self.assertRaisesRegex(ValueError, "metadata.json says 0.1.0"):
            check("v0.2.0", self.tree())

    def test_missing_changelog_section_fails(self):
        with self.assertRaisesRegex(ValueError, "CHANGELOG.md has no"):
            check("v0.1.0", self.tree(changelog="## [0.0.9]\n"))

    def test_tag_without_v_fails(self):
        with self.assertRaises(ValueError):
            check("0.1.0", self.tree())

    def test_the_repository_itself_agrees_with_its_own_version(self):
        meta = json.loads((ROOT / "plasmoid/package/metadata.json").read_text())
        version = meta["KPlugin"]["Version"]
        self.assertEqual(check("v" + version, ROOT), version)


if __name__ == "__main__":
    unittest.main()


class Workflow(unittest.TestCase):
    """The release workflow's shape. It only runs for real on a pushed tag,
    so the parts that matter are pinned here where they can go red locally."""

    text = (ROOT / ".github/workflows/release.yml").read_text()

    def test_a_manual_dry_run_exists(self):
        self.assertIn("workflow_dispatch:", self.text)

    def test_publishing_only_happens_for_a_tag(self):
        release = self.text[self.text.index("\n  release:"):]
        self.assertIn("if: startsWith(github.ref, 'refs/tags/v')", release)

    def test_apt_in_the_container_is_non_interactive(self):
        self.assertIn("-e DEBIAN_FRONTEND=noninteractive", self.text)


class QtInTheWorkflows(unittest.TestCase):
    """The second package is built, checked and installed like the first."""

    release = (ROOT / ".github/workflows/release.yml").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()

    def test_ci_runs_the_smoke_test_with_pyqt6_required_not_skipped(self):
        self.assertIn("python3-pyqt6", self.ci)
        self.assertIn('HAMMUNITION_REQUIRE_PYQT6: "1"', self.ci)

    def test_the_release_installs_runs_and_purges_the_qt_package_on_parrot(self):
        build = self.release[self.release.index("\n  build:"):self.release.index("\n  release:")]
        self.assertIn("apt-get install -y -qq /dist/hammunition-tray-qt_*_all.deb", build)
        self.assertIn("NotShowIn=KDE;", build)
        self.assertIn("QT_QPA_PLATFORM=offscreen", build)
        self.assertIn("apt-get purge -y -qq hammunition-tray-qt", build)
        self.assertIn("test ! -e /usr/share/hammunition-tray-qt", build)

    def test_ci_requires_node_for_the_time_parity_test_in_both_jobs(self):
        # Without it test_time_parity skips, and the applet's timelogic.js
        # would go untested on every pull request.
        self.assertEqual(self.ci.count('HAMMUNITION_REQUIRE_NODE: "1"'), 2)

    def test_shellcheck_covers_the_package_build(self):
        self.assertIn("shellcheck install.sh uninstall.sh packaging/debian/build.sh", self.ci)

    def test_both_packages_are_checksummed(self):
        build = self.release[self.release.index("\n  build:"):self.release.index("\n  release:")]
        checks = build[build.index("name: checksums"):]
        self.assertIn("hammunition-tray_", checks)
        self.assertIn("hammunition-tray-qt_", checks)


class HelperInTheRelease(unittest.TestCase):
    """The helper is versioned, built, checked and installed with the tray."""

    release = (ROOT / ".github/workflows/release.yml").read_text()
    ci = (ROOT / ".github/workflows/ci.yml").read_text()

    def test_the_helper_package_carries_the_trays_version(self):
        import tomllib

        meta = json.loads((ROOT / "plasmoid/package/metadata.json").read_text())
        project = tomllib.loads((ROOT / "devctl/pyproject.toml").read_text())["project"]
        self.assertEqual(project["version"], meta["KPlugin"]["Version"])
        self.assertEqual(project["scripts"], {"hammunition-devctl": "hammunition_devctl.devctl:main"})

    def test_ci_runs_the_helper_on_the_oldest_python_it_supports_and_type_checks_it(self):
        self.assertIn('python: ["3.11", "3.13"]', self.ci)
        self.assertIn("mypy --strict devctl/hammunition_devctl", self.ci)
        self.assertIn("python -m pip install ./devctl", self.ci)

    def test_ci_lints_the_maintainer_scripts(self):
        self.assertIn("packaging/debian/devctl/postinst packaging/debian/devctl/prerm", self.ci)

    def test_the_release_installs_the_helper_through_its_wrapper_and_removes_it(self):
        build = self.release[self.release.index("\n  build:"):self.release.index("\n  release:")]
        self.assertIn("apt-get install -y -qq /dist/hammunition-devctl_*_all.deb", build)
        self.assertIn("hammunition-devctl contract 1", build)
        self.assertIn("test ! -e /usr/local/libexec/hammunition-devctl", build)
        self.assertIn("-eq 3", build)
