# Debian package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `v*` tag publishes `hammunition-tray_<version>_all.deb` with `SHA256SUMS`, proven to install on Parrot, and Hammunition carries it by digest in the `station` profile.

**Architecture:** `dpkg-deb` over a staged tree, the same shape as Hammunition Hill's `packaging/debian/build.sh`; no compilation. A release workflow refuses a tag that disagrees with `metadata.json` or the changelog, installs the `.deb` in a Parrot container, then publishes. A manifest in Hammunition pins the release asset.

**Tech Stack:** bash, `dpkg-deb`, Python 3 `unittest` (this repo's suite), GitHub Actions, rootless Podman locally; Hammunition's YAML catalog.

**Spec:** `docs/specs/2026-09-27-debian-package-design.md`

## Global Constraints

- Package name `hammunition-tray`, `Architecture: all`, version from `metadata.json`'s `KPlugin.Version`, never passed in.
- Installed paths, exactly: `/usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices/…` (the whole `plasmoid/package/` tree), `/usr/share/icons/hicolor/scalable/apps/hammunition-devices.svg`, `/usr/share/doc/hammunition-tray/copyright`, `/usr/share/doc/hammunition-tray/README.md`.
- `Depends: plasma-workspace (>= 4:6), qml6-module-org-kde-plasma-plasma5support, qml6-module-org-kde-kirigami` (measured on Parrot 7.3).
- No maintainer scripts.
- First version `0.1.0`; first tag `v0.1.0`.
- Actions pinned by commit, as resolved 2026-09-27 with `git ls-remote`: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`, `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1`. Re-resolve if more than a week has passed.
- A tag reaches shell only through `env:`, never `${{ }}` inside `run:`.
- Parrot first; other desktops and distributions are out of scope.
- Commits authored as `19499446+ChiefGyk3D@users.noreply.github.com`, ending with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A user who already ran `install.sh`.** Their `~/.local` copy shadows the system one, so a `.deb` upgrade appears to do nothing. Expected: the README says to run `uninstall.sh` once; Task 4 adds it, and Task 2's test checks the package installs nothing into a home directory.
2. **A tree with stray files.** `__pycache__` from the test suite or an editor backup under `plasmoid/package/` would ship. Expected: the build copies only tracked files, and Task 2's contents test fails on anything unlisted.
3. **Plasma running while the package installs or upgrades.** Plasma caches QML; the new version appears only after `systemctl --user restart plasma-plasmashell` or a new login. Expected: the README says so, and Hammunition's manifest carries it in `known_problems` (Task 5).
4. **Hammunition's helper missing.** The `.deb` cannot depend on Hammunition. Expected: the applet's existing "Device control is not installed" message; the package description names `hammunition hardware apply`; Task 2 asserts the description says it.
5. **A tag pushed on a commit whose metadata says another version.** Expected: the release stops before building. Task 1's script is tested against a mismatch.

---

### Task 1: Version 0.1.0, a changelog, and the version-agreement check

**Files:**
- Modify: `plasmoid/package/metadata.json` (`"Version": "0.1.0"`)
- Create: `CHANGELOG.md`, `scripts/check_version.py`
- Test: `tests/test_release.py`

**Interfaces:**
- Produces: `python3 scripts/check_version.py vX.Y.Z` exits 0 and prints the version when the tag, `metadata.json` and a `## [X.Y.Z]` changelog heading agree; exits 1 naming what disagrees otherwise. Importable function `check(tag: str, root: Path) -> str` raising `ValueError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_release.py`:

```python
"""The release job's version gate, runnable locally."""

import json
import os
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest discover -s tests`
Expected: ImportError for `check_version`.

- [ ] **Step 3: Implement**

`scripts/check_version.py`:

```python
#!/usr/bin/env python3
"""Refuse a release tag that disagrees with the tree it points at.

The tag is the one release input a human types. A v0.2.0 tag on a package
that says 0.1.0 publishes a version number that means two things."""

import json
import re
import sys
from pathlib import Path


def check(tag: str, root: Path) -> str:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"tag {tag!r} is not vMAJOR.MINOR.PATCH")
    wanted = tag[1:]
    meta = json.loads((root / "plasmoid/package/metadata.json").read_text())
    have = meta["KPlugin"]["Version"]
    if have != wanted:
        raise ValueError(f"tag {tag} but metadata.json says {have}")
    if not re.search(rf"^## \[{re.escape(wanted)}\]", (root / "CHANGELOG.md").read_text(), re.M):
        raise ValueError(f"CHANGELOG.md has no '## [{wanted}]' section")
    return wanted


if __name__ == "__main__":
    try:
        print(check(sys.argv[1], Path(__file__).resolve().parent.parent))
    except (IndexError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
```

`metadata.json`: `"Version": "0.1.0"`. `CHANGELOG.md`:

```markdown
# Changelog

## [0.1.0] - 2026-09-27

- A switch per parkable device, through Hammunition's polkit-gated helper.
- The penguin icon on Hammunition Hill's disc, grey when anything is parked.
- A Debian package, so Hammunition can install the applet.
```

- [ ] **Step 4: Run and commit**

Run: `python3 -m unittest discover -s tests` (all pass), then break it once: set `metadata.json` to `0.1.1`, confirm `test_the_repository_itself_agrees_with_its_own_version` fails, restore.

```bash
git add plasmoid/package/metadata.json CHANGELOG.md scripts/check_version.py tests/test_release.py
git commit -m "Version 0.1.0, a changelog, and the check a release tag must pass

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `packaging/debian/build.sh`

**Files:**
- Create: `packaging/debian/build.sh`, `packaging/debian/copyright`
- Test: `tests/test_debian_package.py`

**Interfaces:**
- Consumes: `metadata.json`'s version.
- Produces: `packaging/debian/build.sh [OUTDIR]` writes `OUTDIR/hammunition-tray_<version>_all.deb` (default `dist/`) and prints its path.

- [ ] **Step 1: Write the failing tests**

`tests/test_debian_package.py`:

```python
"""The .deb carries exactly what the spec lists, and declares what it needs."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPLET = "usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices"


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
class DebianPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        subprocess.run([str(ROOT / "packaging/debian/build.sh"), str(cls.out)], check=True)
        version = json.loads((ROOT / "plasmoid/package/metadata.json").read_text())["KPlugin"]["Version"]
        cls.deb = cls.out / f"hammunition-tray_{version}_all.deb"

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
            line.split()[-1].lstrip("./")
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
        ):
            self.assertIn(dep, depends)
        self.assertIn("hammunition hardware apply", self.field("Description"))

    def test_exactly_the_listed_files(self):
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "plasmoid/package"],
            capture_output=True, text=True, check=True,
        ).stdout.split()
        expected = {APPLET + "/" + t[len("plasmoid/package/"):] for t in tracked}
        expected |= {
            "usr/share/icons/hicolor/scalable/apps/hammunition-devices.svg",
            "usr/share/doc/hammunition-tray/copyright",
            "usr/share/doc/hammunition-tray/README.md",
        }
        self.assertEqual(self.files(), expected)

    def test_no_maintainer_scripts(self):
        control = subprocess.run(
            ["dpkg-deb", "--ctrl-tarfile", str(self.deb)], capture_output=True, check=True
        ).stdout
        listing = subprocess.run(
            ["tar", "-t"], input=control, capture_output=True, check=True
        ).stdout.decode()
        for script in ("preinst", "postinst", "prerm", "postrm"):
            self.assertNotIn(script, listing)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_debian_package`
Expected: error, `build.sh` does not exist.

- [ ] **Step 3: Implement**

`packaging/debian/build.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# Build the Debian package: dpkg-deb over a staged tree, the same shape as
# Hammunition Hill's. There is nothing to compile; the job is "put these files
# in these places and declare what they need". Only tracked files ship, so a
# __pycache__ or an editor backup under plasmoid/package never reaches a user.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
outdir="${1:-$repo/dist}"
mkdir -p "$outdir"

version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["KPlugin"]["Version"])' \
    "$repo/plasmoid/package/metadata.json")"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

applet="$stage/usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices"
mkdir -p "$applet" "$stage/usr/share/icons/hicolor/scalable/apps" \
         "$stage/usr/share/doc/hammunition-tray" "$stage/DEBIAN"

git -C "$repo" ls-files -z plasmoid/package | while IFS= read -r -d '' f; do
    install -D -m 0644 "$repo/$f" "$applet/${f#plasmoid/package/}"
done
install -m 0644 "$repo/plasmoid/package/contents/icons/hammunition-devices-awake.svg" \
    "$stage/usr/share/icons/hicolor/scalable/apps/hammunition-devices.svg"
install -m 0644 "$here/copyright" "$stage/usr/share/doc/hammunition-tray/copyright"
install -m 0644 "$repo/README.md" "$stage/usr/share/doc/hammunition-tray/README.md"

size="$(du -sk --exclude=DEBIAN "$stage" | cut -f1)"
cat > "$stage/DEBIAN/control" <<EOF
Package: hammunition-tray
Version: $version
Section: kde
Priority: optional
Architecture: all
Installed-Size: $size
Depends: plasma-workspace (>= 4:6), qml6-module-org-kde-plasma-plasma5support, qml6-module-org-kde-kirigami
Maintainer: ChiefGyk3D <19499446+ChiefGyk3D@users.noreply.github.com>
Homepage: https://github.com/ChiefGyk3D/hammunition-tray
Description: KDE Plasma tray switches for Hammunition's parkable radio devices
 A switch per parkable device (a GPS receiver, a modem) that Hammunition has
 catalogued. It calls Hammunition's polkit-gated helper and runs nothing as
 root itself. Install Hammunition and run \`hammunition hardware apply\`
 first; without the helper the applet says so instead of showing switches.
EOF

deb="$outdir/hammunition-tray_${version}_all.deb"
dpkg-deb --root-owner-group --build "$stage" "$deb" >/dev/null
echo "$deb"
```

`packaging/debian/copyright`: DEP-5 format naming `Files: *`, `Copyright: 2026 ChiefGyk3D`, `License: GPL-3.0-or-later`, with the standard GPL-3 pointer to `/usr/share/common-licenses/GPL-3`.

- [ ] **Step 4: Run, falsify, commit**

Run: `python3 -m unittest discover -s tests` (all pass). Falsify: `touch plasmoid/package/contents/ui/stray.qml && git add -N` it; `test_exactly_the_listed_files` must still pass (tracked means it ships); now instead create an untracked `plasmoid/package/contents/ui/__pycache__/x.pyc`, confirm the package does not contain it, then delete both.

```bash
git add packaging tests/test_debian_package.py
git commit -m "Debian package: the applet, the icon, measured Depends, no maintainer scripts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The release workflow, and the package built in CI

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `.github/workflows/ci.yml` (the `applet package` job gets `sudo apt-get install -y dpkg-dev` if `dpkg-deb` is absent on the runner; it is present on `ubuntu-latest`, so check first and add nothing if so)

- [ ] **Step 1: Write the workflow**

```yaml
# Cut a release when a v* tag is pushed. The first job refuses a tag that
# disagrees with the tree; the second builds the .deb and installs it on
# Parrot before anything is published.
name: release

on:
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - name: the tag, metadata.json and the changelog agree
        env:
          TAG: ${{ github.ref_name }}
        run: python3 scripts/check_version.py "$TAG"

  build:
    needs: verify
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - run: python3 -m unittest discover -s tests -v
      - run: ./packaging/debian/build.sh dist
      - name: installs on Parrot, files in place
        run: |
          set -euo pipefail
          docker run --rm -v "$PWD/dist:/dist:ro" docker.io/parrotsec/core:latest bash -c '
            set -eux
            apt-get update -qq
            apt-get install -y -qq /dist/hammunition-tray_*_all.deb
            test -f /usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices/metadata.json
            python3 -c "import json; json.load(open(\"/usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices/metadata.json\"))"
            test -f /usr/share/icons/hicolor/scalable/apps/hammunition-devices.svg
            apt-get remove -y -qq hammunition-tray
            test ! -e /usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices
          '
      - run: cd dist && sha256sum ./* > SHA256SUMS && cat SHA256SUMS
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: dist
          path: dist/
          if-no-files-found: error

  release:
    needs: build
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@<resolve with git ls-remote at execution> # v7.x
        with:
          name: dist
          path: dist
      - name: publish
        env:
          GH_TOKEN: ${{ github.token }}
          TAG: ${{ github.ref_name }}
          REPO: ${{ github.repository }}
        run: gh release create "$TAG" dist/* --repo "$REPO" --title "hammunition-tray $TAG" --notes-file <(sed -n "/^## \[${TAG#v}\]/,/^## \[/p" CHANGELOG.md | sed '$d')
```

The `download-artifact` pin is resolved at execution with `git ls-remote --tags https://github.com/actions/download-artifact 'refs/tags/v7*'` and written as a full SHA with its tag comment; it is the one action not already pinned in Hill. The `release` job does not check out the repo, so `--notes-file` reads a changelog it does not have: add a checkout step (pinned as above, `persist-credentials: false`) before `publish`.

- [ ] **Step 2: Run the same steps locally**

Run: `packaging/debian/build.sh dist && podman run --rm -v "$PWD/dist:/dist:ro,Z" docker.io/parrotsec/core:latest bash -c '<the script above>'`
Expected: every `test` passes, exit 0.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml .github/workflows/ci.yml
git commit -m "Release workflow: verify the tag, install the .deb on Parrot, publish with checksums

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: README, then the first release (maintainer)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README**

An "Install" section in this order: through Hammunition (`hammunition install hammunition-tray`, once Task 5 has merged), the `.deb` from the releases page (`sudo apt install ./hammunition-tray_0.1.0_all.deb`), then `install.sh` for a per-user copy. A note: a per-user copy from `install.sh` shadows the package, so run `./uninstall.sh` once after installing the `.deb`; and after any install or upgrade, `systemctl --user restart plasma-plasmashell` or log out and in.

- [ ] **Step 2: Commit, open the PR, merge after green (maintainer)**

```bash
git add README.md docs/plans
git commit -m "README: install from the .deb, or through Hammunition

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: Tag (maintainer's go-ahead)**

`git tag -a v0.1.0 -m "hammunition-tray 0.1.0" && git push origin v0.1.0`. Watch the `release` run; confirm the release has the `.deb` and `SHA256SUMS`, download both, and check `sha256sum -c SHA256SUMS`.

---

### Task 5: The Hammunition manifest (Hammunition repository)

**Files (in Hammunition):**
- Create: `catalog/packages/hammunition-tray.yaml`
- Modify: `catalog/profiles/station.yaml` (add `hammunition-tray` beside `hammunition-hill`), `README.md` (family table row; the package count), `CLAUDE.md` (the package count)
- Regenerate: every generator the tests list (`.venv/bin/python -m pytest -q tests/test_docs_generated.py` names any that are stale)

- [ ] **Step 1: The manifest**

Modelled on `catalog/packages/hammunition-hill.yaml`: the header comment discloses the maintainer's own upstream and records the digest from the downloaded `.deb` and `SHA256SUMS`, and `dpkg-deb -f` fields as measured. `install: method: binary, format: deb, deb_package: hammunition-tray`, `artifact.url` the v0.1.0 release asset, `sha256` as measured. `categories` from the vocabulary file that fits a device-control applet (read `catalog/categories.yaml`; `device-support` is the likely tag). No launchers: Plasma lists the widget itself. `update.probe: github_release`. `documentation.prerequisites`: KDE Plasma 6, and `hammunition hardware apply` first. `known_problems`: KDE only; Plasma caches QML, so restart plasmashell or log in again after install or upgrade; a per-user copy from the repo's `install.sh` shadows it.

- [ ] **Step 2: Profile, counts, generated pages**

Add to `station`. Bump the README's `Package manifests` count and CLAUDE.md's `packages/` count by one; the README family row's "How you get it" becomes the manifest link. Regenerate, then run the full gate set.

- [ ] **Step 3: Install on the field laptop through the engine (maintainer runs the sudo part)**

`.venv/bin/hammunition install hammunition-tray --dry-run`, then for real; confirm `/usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices/metadata.json` exists, remove the per-user copy (`~/src/hammunition-tray/uninstall.sh`), restart plasmashell, and see the widget come from the system copy. Then `hammunition uninstall hammunition-tray` and confirm it is gone, and install again. Record it in the manifest's header comment.

- [ ] **Step 4: Commit and PR**

```bash
git add catalog docs README.md CLAUDE.md
git commit -m "Carry hammunition-tray: the family's Plasma applet, a pinned .deb in station

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Push, open the PR, wait for CI, and dispatch the weekly jobs (`gh workflow run ci.yml --ref <branch>`) since it adds a pin.
