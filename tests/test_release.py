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


GYST = "ChiefGyk3D/git-your-ship-together/.github/workflows/"
GYST_SHA = "804400181a9d3e2f78dfcda5161e2bd960bc011a"  # v1.15.0's commit, not its tag object

RELEASE = (ROOT / ".github/workflows/release.yml").read_text()
CI = (ROOT / ".github/workflows/ci.yml").read_text()
SECURITY = (ROOT / ".github/workflows/security.yml").read_text()
PARROT = (ROOT / "scripts/parrot-install-check.sh").read_text()


def release_inputs():
    import yaml

    return yaml.safe_load(RELEASE)["jobs"]["artifacts"]["with"]


class GystCallers(unittest.TestCase):
    """CI, release and security are GYST's reusable workflows, pinned by the
    commit (an annotated tag's own sha is a tag object, not a commit)."""

    def test_every_gyst_call_is_pinned_by_commit_with_the_version_comment(self):
        import re

        for name, text in (("ci", CI), ("release", RELEASE), ("security", SECURITY)):
            calls = re.findall(r"uses: " + re.escape(GYST) + r"(\S+)@(\S+) # (\S+)", text)
            self.assertTrue(calls, name)
            for workflow, sha, version in calls:
                self.assertEqual(sha, GYST_SHA, f"{name}: {workflow}")
                self.assertEqual(version, "v1.13.0")

    def test_every_other_action_is_pinned_by_a_40_hex_sha(self):
        import re

        for text in (CI, RELEASE, SECURITY):
            for ref in re.findall(r"uses: (?!ChiefGyk3D/git-your-ship-together)\S+@(\S+)", text):
                self.assertRegex(ref, r"^[0-9a-f]{40}$")

    def test_ci_calls_python_and_bash_ci_and_security_calls_security(self):
        self.assertIn(GYST + "python-ci.yml@", CI)
        self.assertIn(GYST + "bash-ci.yml@", CI)
        self.assertIn(GYST + "security.yml@", SECURITY)
        self.assertIn(GYST + "artifact-release.yml@", RELEASE)

    def test_no_workflow_hands_over_all_secrets_or_needs_doppler(self):
        for text in (CI, RELEASE, SECURITY):
            self.assertNotIn("secrets: inherit", text)
            self.assertNotIn("doppler-", text.replace("no Doppler", ""))


class Workflow(unittest.TestCase):
    """The release workflow's shape. It only runs for real on a pushed tag,
    so the parts that matter are pinned here where they can go red locally."""

    def test_a_manual_dry_run_exists(self):
        self.assertIn("workflow_dispatch:", RELEASE)

    def test_publishing_only_happens_for_a_tag(self):
        self.assertEqual(release_inputs()["publish"], "${{ startsWith(github.ref, 'refs/tags/v') }}")
        self.assertEqual(release_inputs()["tag-prefix"], "v")

    def test_a_pull_request_builds_and_verifies_but_the_publish_input_is_the_tag_test(self):
        self.assertIn("pull_request:", RELEASE)
        self.assertNotIn("publish: true", RELEASE)

    def test_the_gate_and_the_tests_run_before_the_build(self):
        build = release_inputs()["build-command"]
        self.assertLess(build.index("check_version.py"), build.index("pytest"))
        self.assertLess(build.index("pytest"), build.index("packaging/debian/build.sh dist"))

    def test_the_release_notes_are_the_changelog_section_and_must_not_be_empty_on_a_tag(self):
        notes = release_inputs()["release-notes-command"]
        self.assertIn("CHANGELOG.md", notes)
        self.assertIn("test -n \"$notes\"", notes)

    def test_the_debs_are_what_is_published_and_the_count_is_checked(self):
        self.assertEqual(release_inputs()["artifacts"], "dist/*.deb")
        verify = release_inputs()["verify-command"]
        self.assertIn("-eq 3", verify)
        self.assertIn("./scripts/parrot-install-check.sh dist", verify)

    def test_apt_in_the_container_is_non_interactive(self):
        self.assertIn("-e DEBIAN_FRONTEND=noninteractive", PARROT)

    def test_parrot_install_retries_fetch_failures_and_reports_exhaustion(self):
        build = PARROT
        self.assertIn("for attempt in 1 2 3", build)
        self.assertIn("sleep 10", build)
        self.assertIn("sleep 30", build)
        self.assertIn("PARROT_MIRROR_ATTEMPT", build)
        self.assertIn("https://parrotsec.org/docs/mirror-list", build)
        self.assertIn("https://mirror.parrot.sh/direct", build)
        self.assertIn("exit 75", build)
        self.assertIn("if [ \"$status\" -ne 75 ]; then", build)
        self.assertEqual(build.count("apt_fetch apt-get install"), 3)
        self.assertIn("Parrot install check was skipped due to the mirror after 3 attempts.", build)
        self.assertIn("test -f \"$d/metadata.json\"", build)

    def test_the_mirror_rewrite_does_not_double_the_direct_path(self):
        # deb.parrot.sh/direct/parrot became mirror.parrot.sh/direct/direct/parrot
        # and the second attempt died with "does not have a Release file".
        import re
        import subprocess

        m = re.search(r'-exec sed -i -E "([^"]+)"', PARROT)
        self.assertIsNotNone(m)
        for src in ("https://deb.parrot.sh/direct/parrot", "https://mirror.parrot.sh/direct/parrot"):
            out = subprocess.run(["sed", "-E", m.group(1)], input="deb " + src + " echo main\n",
                                 capture_output=True, text=True, check=True).stdout
            self.assertEqual(out, "deb https://mirror.parrot.sh/direct/parrot echo main\n")
        self.assertIn('! grep -Rqs "direct/direct" /etc/apt', PARROT)

    def test_the_parrot_hosts_are_named_for_the_egress_list(self):
        endpoints = release_inputs()["extra-allowed-endpoints"]
        for host in ("registry-1.docker.io:443", "deb.parrot.sh:443", "mirror.parrot.sh:443", "deb.debian.org:443"):
            self.assertIn(host, endpoints)

    def test_the_check_script_runs_under_bash_strict_mode(self):
        self.assertTrue(PARROT.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", PARROT.split("docker run")[0])
        self.assertTrue((ROOT / "scripts/parrot-install-check.sh").stat().st_mode & 0o111)


class QtInTheWorkflows(unittest.TestCase):
    """The second package is built, checked and installed like the first."""

    release = RELEASE + PARROT
    ci = CI

    def test_ci_runs_the_smoke_test_with_pyqt6_required_not_skipped(self):
        self.assertIn("python3-pyqt6", self.ci)
        self.assertIn('HAMMUNITION_REQUIRE_PYQT6: "1"', self.ci)

    def test_the_release_installs_runs_and_purges_the_qt_package_on_parrot(self):
        build = PARROT
        self.assertIn("apt-get install -y -qq /dist/hammunition-tray-qt_*_all.deb", build)
        self.assertIn("NotShowIn=KDE;", build)
        self.assertIn("QT_QPA_PLATFORM=offscreen", build)
        self.assertIn("apt-get purge -y -qq hammunition-tray-qt", build)
        self.assertIn("test ! -e /usr/share/hammunition-tray-qt", build)

    def test_ci_requires_node_for_the_time_parity_test_in_both_jobs(self):
        # Without it test_time_parity skips, and the applet's timelogic.js
        # would go untested on every pull request: once in the Python matrix
        # and once in the Qt job.
        self.assertIn("HAMMUNITION_REQUIRE_NODE=1 python -m pytest tests", self.ci)
        self.assertIn('HAMMUNITION_REQUIRE_NODE: "1"', self.ci)

    def test_shellcheck_covers_the_package_build_at_the_old_strictness(self):
        # bash-ci finds scripts by shebang; the scripts the old job named
        # must still have one, and the severity must not drop below style.
        for script in ("install.sh", "uninstall.sh", "packaging/debian/build.sh",
                       "packaging/debian/devctl/postinst", "packaging/debian/devctl/prerm",
                       "scripts/parrot-install-check.sh"):
            first = (ROOT / script).read_text().splitlines()[0]
            self.assertRegex(first, r"^#!.*\b(ba)?sh\b", script)
        self.assertIn("shellcheck-severity: style", self.ci)
        self.assertIn(GYST + "bash-ci.yml@", self.ci)

    def test_both_packages_are_counted_and_present_before_publishing(self):
        verify = release_inputs()["verify-command"]
        self.assertIn("hammunition-tray_", verify)
        self.assertIn("hammunition-tray-qt_", verify)
        self.assertIn("hammunition-devctl_", verify)


class HelperInTheRelease(unittest.TestCase):
    """The helper is versioned, built, checked and installed with the tray."""

    release = RELEASE
    ci = CI

    def test_the_helper_package_carries_the_trays_version(self):
        import tomllib

        meta = json.loads((ROOT / "plasmoid/package/metadata.json").read_text())
        project = tomllib.loads((ROOT / "devctl/pyproject.toml").read_text())["project"]
        self.assertEqual(project["version"], meta["KPlugin"]["Version"])
        self.assertEqual(project["scripts"], {"hammunition-devctl": "hammunition_devctl.devctl:main"})

    def test_ci_runs_the_helper_on_the_oldest_python_it_supports_and_type_checks_it(self):
        self.assertIn("python-versions: '[\"3.11\", \"3.13\"]'", self.ci)
        self.assertIn("mypy --strict --python-version 3.11 devctl/hammunition_devctl", self.ci)
        self.assertIn("mypy --strict --python-version 3.13 devctl/hammunition_devctl", self.ci)
        self.assertIn("python -m pip install ./devctl", self.ci)
        self.assertIn('test "$(hammunition-devctl --version)" = "hammunition-devctl contract 1"', self.ci)

    def test_ci_lints_the_maintainer_scripts(self):
        # Found by shebang, not listed: they must keep one.
        for script in ("postinst", "prerm"):
            self.assertTrue((ROOT / "packaging/debian/devctl" / script).read_text().startswith("#!"))

    def test_the_release_installs_the_helper_through_its_wrapper_and_removes_it(self):
        build = PARROT
        self.assertIn("apt-get install -y -qq /dist/hammunition-devctl_*_all.deb", build)
        self.assertIn("hammunition-devctl contract 1", build)
        self.assertIn("test ! -e /usr/local/libexec/hammunition-devctl", build)
        self.assertIn("-eq 3", release_inputs()["verify-command"])
