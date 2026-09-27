#!/usr/bin/env bash
# Build the Debian package: dpkg-deb over a staged tree, the same shape as
# Hammunition Hill's. There is nothing to compile; the job is "put these files
# in these places and declare what they need". Only tracked files ship, so a
# __pycache__ or an editor backup under plasmoid/package never reaches a user.
#
# The version is read from metadata.json, never passed in: a .deb whose
# filename disagrees with what Plasma shows is the confusion the release
# check exists to prevent.
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
 root itself. Install Hammunition and run 'hammunition hardware apply'
 first; without the helper the applet says so instead of showing switches.
EOF

deb="$outdir/hammunition-tray_${version}_all.deb"
dpkg-deb --root-owner-group --build "$stage" "$deb" >/dev/null
echo "$deb"
