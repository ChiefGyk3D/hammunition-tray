# A Debian package for the applet, so Hammunition can install it

**Status:** approach approved in conversation 2026-09-27 (option A); awaiting
the maintainer's read of this document.
**Why:** Hammunition installs its two sibling projects, Hill and Skid Finder,
through its catalog. The applet can only be installed by `install.sh`, per user.
Hammunition's engine installs trees only under `share/hammunition/<name>`, not
where Plasma looks, so the applet ships as a `.deb` and Hammunition carries it
exactly as it carries Hill: a digest-pinned `.deb` through apt.
**Priority:** Parrot OS first (Plasma 6 on Parrot 7). Other desktops and
distributions get their own versions later and are out of scope here.

## 1. The package

`hammunition-tray_<version>_all.deb`, built by `packaging/debian/build.sh`
with `dpkg-deb` from the tree. No compilation; `Architecture: all`.

| Installed path | From |
|---|---|
| `/usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices/` | `plasmoid/package/` |
| `/usr/share/icons/hicolor/scalable/apps/hammunition-devices.svg` | the awake icon |
| `/usr/share/doc/hammunition-tray/copyright`, `README.md` | the tree |

**Depends**, each measured on Parrot 7.3 as the package that ships a QML
module the applet imports:

- `plasma-workspace (>= 4:6)`: Plasma 6, the only one this applet targets.
- `qml6-module-org-kde-plasma-plasma5support`: ships separately from Plasma.
  Without it the widget installs and then fails to load.
- `qml6-module-org-kde-kirigami`.

It cannot depend on Hammunition, which is not a Debian package. The applet
already says when the helper is missing, and the package description says to
run `hammunition hardware apply`.

No maintainer scripts. The hicolor icon cache is refreshed by the
`hicolor-icon-theme` dpkg trigger, and Plasma finds a new applet directory on
its own.

**Per-user copies.** A user who installed with `install.sh` has a copy in
`~/.local/share/plasma/plasmoids/` that shadows the system one. The README says
to run `uninstall.sh` once the package is installed.

## 2. Version

`metadata.json` `Version` becomes `0.1.0` (from `0.1`), a `CHANGELOG.md` is
added with a `0.1.0` section, and the first tag is `v0.1.0`.

## 3. Release workflow

`.github/workflows/release.yml`, on a `v*` tag, following Hill's:

1. **verify:** the tag, `metadata.json`'s `Version` and a `CHANGELOG.md`
   section must agree, or the release stops. The tag is passed through the
   environment, never interpolated into shell.
2. **build:** `build.sh`, then install the `.deb` with apt in a
   `docker.io/parrotsec/core` container and check that each installed path
   exists and `metadata.json` parses there. Then `SHA256SUMS` is written.
3. **release:** `gh release create` with the `.deb` and `SHA256SUMS`.

Actions pinned by commit, resolved with `git ls-remote`, as in Hill.

## 4. Tests (the existing unittest suite, run by CI)

- `build.sh` produces a `.deb` whose `dpkg-deb --contents` lists exactly the
  paths in §1, and whose control file carries the three Depends.
- The version agreement check the release job runs is a script with its own
  test, so it can go red locally on a mismatched tag.
- Falsified: each goes red with the thing it watches broken on purpose.

## 5. Then, in Hammunition

A `hammunition-tray` manifest carrying the `v0.1.0` `.deb` by digest, KDE-only
said plainly in its notes, its page saying `hammunition hardware apply` comes
first. Installed on the field laptop through the engine before it merges.
Profile: `station`, beside Hill. That is a separate PR in Hammunition.

## 6. Out of scope

Other desktops (GNOME, Xfce, COSMIC), Plasma 5, other distributions' native
packages, and pinning the existing CI job's `actions/checkout@v4` by commit
(noted as a follow-up).
