#!/usr/bin/env bash
# Build the Debian packages: dpkg-deb over a staged tree, the same shape as
# Hammunition Hill's. There is nothing to compile; the job is "put these files
# in these places and declare what they need". Only tracked files ship, so a
# __pycache__ or an editor backup under plasmoid/package or qt/ never reaches
# a user.
#
# Two packages, one version: hammunition-tray (the Plasma applet) and
# hammunition-tray-qt (the same switch for Xfce, LXQt, LXDE, MATE and
# Cinnamon). Each path is printed on its own line, the applet's first.
#
# The version is read from metadata.json, never passed in: a .deb whose
# filename disagrees with what Plasma shows is the confusion the release
# check exists to prevent.
set -euo pipefail
# Modes in the package must not depend on whoever builds it: under a 0002
# umask the staged directories came out group-writable, and apt installs
# them as root exactly as packed. mktemp -d is 0700 regardless, hence the
# chmod below as well.
umask 022

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
outdir="${1:-$repo/dist}"
mkdir -p "$outdir"

version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["KPlugin"]["Version"])' \
    "$repo/plasmoid/package/metadata.json")"

stage="$(mktemp -d)"
qstage="$(mktemp -d)"
trap 'rm -rf "$stage" "$qstage"' EXIT
chmod 0755 "$stage" "$qstage"

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
Depends: plasma-workspace (>= 4:6), qml6-module-org-kde-plasma-plasma5support, qml6-module-org-kde-kirigami, qml6-module-org-kde-notifications
Maintainer: ChiefGyk3D <19499446+ChiefGyk3D@users.noreply.github.com>
Homepage: https://github.com/ChiefGyk3D/hammunition-tray
Description: KDE Plasma tray switches for Hammunition's parkable radio devices
 A switch per parkable device (a GPS receiver, a modem) that Hammunition has
 catalogued. It calls Hammunition's polkit-gated helper and runs nothing as
 root itself. Install Hammunition and run 'hammunition hardware apply'
 first; without the helper the applet says so instead of showing switches.
EOF

deb="$outdir/hammunition-tray_${version}_all.deb"
dpkg-deb --root-owner-group --build "$stage" "$deb" >/dev/null
echo "$deb"

# --- hammunition-tray-qt ---------------------------------------------------

lib="$qstage/usr/share/hammunition-tray-qt"
qdoc="$qstage/usr/share/doc/hammunition-tray-qt"
qicons="$qstage/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$lib" "$qicons" "$qdoc" "$qstage/usr/bin" \
         "$qstage/usr/share/applications" "$qstage/etc/xdg/autostart" "$qstage/DEBIAN"

git -C "$repo" ls-files -z qt/hammunition_tray_qt | while IFS= read -r -d '' f; do
    install -D -m 0644 "$repo/$f" "$lib/${f#qt/}"
done
install -m 0755 "$repo/qt/hammunition-tray-qt" "$qstage/usr/bin/hammunition-tray-qt"
install -m 0644 "$repo/qt/hammunition-tray-qt.desktop" \
    "$qstage/usr/share/applications/hammunition-tray-qt.desktop"
install -m 0644 "$repo/qt/hammunition-tray-qt-autostart.desktop" \
    "$qstage/etc/xdg/autostart/hammunition-tray-qt.desktop"
# Distinct names from the applet's hammunition-devices, so the two packages
# never own the same file and either installs without the other.
for state in awake parked; do
    install -m 0644 "$repo/plasmoid/package/contents/icons/hammunition-devices-$state.svg" \
        "$qicons/hammunition-tray-qt-$state.svg"
done
install -m 0644 "$here/copyright" "$qdoc/copyright"
install -m 0644 "$repo/README.md" "$qdoc/README.md"

# Under /etc, so dpkg keeps an operator's own edit to it across upgrades.
# Removed but not purged it stays, and its TryExec stops login trying to
# start a program that has gone.
echo "/etc/xdg/autostart/hammunition-tray-qt.desktop" > "$qstage/DEBIAN/conffiles"

qsize="$(du -sk --exclude=DEBIAN "$qstage" | cut -f1)"
cat > "$qstage/DEBIAN/control" <<CONTROL
Package: hammunition-tray-qt
Version: $version
Section: utils
Priority: optional
Architecture: all
Installed-Size: $qsize
Depends: python3 (>= 3.11), python3-pyqt6, pkexec | policykit-1
Maintainer: ChiefGyk3D <19499446+ChiefGyk3D@users.noreply.github.com>
Homepage: https://github.com/ChiefGyk3D/hammunition-tray
Description: Tray switches for Hammunition's parkable radio devices, outside Plasma
 The Plasma applet's switch for every other desktop with a system tray:
 Xfce, LXQt, LXDE, MATE and Cinnamon. A menu item per parkable device (a
 GPS receiver, a modem) that Hammunition has catalogued, through
 Hammunition's polkit-gated helper; nothing here runs as root. Install
 Hammunition and run 'hammunition hardware apply' first; without the
 helper the tray says so instead of showing switches. It starts at login
 everywhere except Plasma, which has the applet.
CONTROL

qdeb="$outdir/hammunition-tray-qt_${version}_all.deb"
dpkg-deb --root-owner-group --build "$qstage" "$qdeb" >/dev/null
echo "$qdeb"
