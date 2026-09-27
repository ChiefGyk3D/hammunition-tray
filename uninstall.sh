#!/usr/bin/env bash
# Remove the Hammunition Devices applet for the current user.
#
# This removes the applet only. It does not touch the helper or the polkit
# action Hammunition installed -- those are the engine's, and
# `hammunition hardware unapply` is what removes them.
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
    echo "Do not run this as root; the applet lives in your own home." >&2
    exit 1
fi

command -v kpackagetool6 >/dev/null || { echo "kpackagetool6 is not on PATH." >&2; exit 1; }

kpackagetool6 --type Plasma/Applet --remove com.chiefgyk3d.hammunition.devices
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/hammunition-devices.svg"
echo "Removed. The helper and polkit action are untouched; use"
echo "\`hammunition hardware unapply\` if you want those gone too."
