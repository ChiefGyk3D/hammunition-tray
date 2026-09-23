#!/usr/bin/env bash
# Install the Hammunition Devices applet for the current user.
#
# Deliberately NOT run as root. kpackagetool6 installs into the invoking
# user's $HOME/.local/share/plasma/plasmoids, and a root install would put the
# package somewhere the operator's Plasma session does not read while
# leaving root-owned files in their home if they ever ran it wrong.
# The applet needs no privilege of its own: it polls an unprivileged
# command and asks polkit for the one operation that does.
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
    echo "Do not run this as root. The applet installs into your own" >&2
    echo "$HOME/.local/share/plasma/plasmoids and needs no privilege." >&2
    exit 1
fi

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pkg="${src}/plasmoid/package"

command -v kpackagetool6 >/dev/null || {
    echo "kpackagetool6 is not on PATH. It ships with Plasma 6" >&2
    echo "(Debian-family: plasma-framework / kf6-kpackage tooling)." >&2
    exit 1
}

if kpackagetool6 --type Plasma/Applet --list 2>/dev/null | grep -qx "com.chiefgyk3d.hammunition.devices"; then
    kpackagetool6 --type Plasma/Applet --upgrade "${pkg}"
else
    kpackagetool6 --type Plasma/Applet --install "${pkg}"
fi

echo
echo "Installed. Add 'Hammunition Devices' to your panel or system tray."
if [[ ! -x /usr/local/libexec/hammunition-devctl ]]; then
    echo
    echo "Note: Hammunition's device helper is not installed yet, so the"
    echo "applet will say so rather than showing switches. Install it with:"
    echo "    hammunition hardware apply"
fi
