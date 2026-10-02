#!/usr/bin/env bash
# Install the Hammunition Devices applet for the current user, and the device
# helper it talks to for the machine.
#
# The script is deliberately NOT run as root. The applet half installs into
# the invoking user's $HOME/.local/share/plasma/plasmoids with kpackagetool6;
# a root install would put the package somewhere the operator's Plasma session
# does not read. The helper half needs root for three things, and says so
# before it does them: it asks `sudo` for exactly the `install` commands it
# prints, once, after you confirm.
#
#   /usr/local/lib/hammunition-devctl/          the helper's code, root-owned
#   /usr/local/libexec/hammunition-devctl       a /bin/sh wrapper polkit authorises
#   /usr/share/polkit-1/actions/com.chiefgyk3d.hammunition.devctl.policy
#
# The helper's code is COPIED to /usr/local/lib, never run from this checkout:
# the wrapper runs as root, and root must not run code that your account (or
# anyone's) can still edit. See docs/contract.md.
#
#   ./install.sh                      applet, then the helper (asks first)
#   ./install.sh --no-helper          applet only
#   ./install.sh --helper-only        the helper only (no Plasma needed)
#   ./install.sh --interpreter PATH   the Python the wrapper runs (default
#                                     /usr/bin/python3). Point it at the
#                                     Hammunition engine's venv python so the
#                                     helper's `time` verbs can import it.
#   ./install.sh --force-helper       replace a wrapper some other installer
#                                     wrote (the engine's `hardware apply` does)
#   ./install.sh --yes                do not ask before running sudo
#
# For tests and packaging only: HAMMUNITION_DEVCTL_ROOT=DIR puts every helper
# file under DIR instead of /, and HAMMUNITION_DEVCTL_SUDO="" runs the
# `install` commands without sudo (any other value replaces the sudo command).
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
    echo "Do not run this as root. The applet installs into your own" >&2
    echo "$HOME/.local/share/plasma/plasmoids; the helper step asks for sudo" >&2
    echo "itself, once, for the files it lists." >&2
    exit 1
fi

want_applet=1
want_helper=1
force_helper=0
assume_yes=0
interpreter=/usr/bin/python3

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-helper) want_helper=0 ;;
        --helper-only) want_applet=0 ;;
        --force-helper) force_helper=1 ;;
        --yes | -y) assume_yes=1 ;;
        --interpreter)
            [[ $# -ge 2 ]] || { echo "--interpreter needs a path" >&2; exit 2; }
            interpreter="$2"
            shift
            ;;
        -h | --help)
            sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

if [[ ${want_applet} -eq 0 && ${want_helper} -eq 0 ]]; then
    echo "Nothing to do: --no-helper and --helper-only together." >&2
    exit 2
fi
case "${interpreter}" in
    /*) ;;
    *) echo "--interpreter must be an absolute path, got: ${interpreter}" >&2; exit 2 ;;
esac
if [[ ${want_helper} -eq 1 && ! -x "${interpreter}" ]]; then
    echo "--interpreter ${interpreter} is not an executable file; the wrapper would exec nothing." >&2
    exit 2
fi

src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install_applet() {
    local pkg="${src}/plasmoid/package"

    command -v kpackagetool6 >/dev/null || {
        echo "kpackagetool6 is not on PATH. It ships with Plasma 6" >&2
        echo "(Debian-family: plasma-framework / kf6-kpackage tooling)." >&2
        echo "On another desktop, use ./install.sh --helper-only and the" >&2
        echo "Qt tray package instead." >&2
        exit 1
    }

    if kpackagetool6 --type Plasma/Applet --list 2>/dev/null | grep -qx "com.chiefgyk3d.hammunition.devices"; then
        kpackagetool6 --type Plasma/Applet --upgrade "${pkg}"
    else
        kpackagetool6 --type Plasma/Applet --install "${pkg}"
    fi

    # The widget list and the tray's settings look the icon up by name, from
    # metadata.json, so it goes into the user's own icon directory as well.
    # The applet itself loads the SVGs from its package and does not need this.
    local icon_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
    install -D -m 0644 "${pkg}/contents/icons/hammunition-devices-awake.svg" \
        "${icon_dir}/hammunition-devices.svg"

    echo
    echo "Installed. Add 'Hammunition Devices' to your panel or system tray."
}

# The first component of PATH (as given, then resolved) that an unprivileged
# account owns, or nothing. A wrapper that runs a Python from such a tree runs
# whatever that account puts there, as root.
non_root_owned_component() {
    local given="$1" p
    for p in "${given}" "$(realpath -- "${given}" 2>/dev/null || echo "${given}")"; do
        while [[ -n "${p}" && "${p}" != "/" && "${p}" != "." ]]; do
            if [[ "$(stat -c %u -- "${p}" 2>/dev/null || echo 0)" != "0" ]]; then
                echo "${p}"
                return 0
            fi
            p="$(dirname -- "${p}")"
        done
    done
}

# True when the hammunition-devctl .deb installed the helper: it carries the
# same mark, so without this the two routes would overwrite each other's files.
package_owns_helper() {
    local root="$1" policy="$2"
    [[ -d "${root}/usr/share/hammunition-devctl" ]] && return 0
    command -v dpkg-query >/dev/null && dpkg-query -S "${root}${policy}" >/dev/null 2>&1
}

install_helper() {
    local root="${HAMMUNITION_DEVCTL_ROOT:-}"
    local libdir="/usr/local/lib/hammunition-devctl"
    local wrapper="/usr/local/libexec/hammunition-devctl"
    local policy="/usr/share/polkit-1/actions/com.chiefgyk3d.hammunition.devctl.policy"
    local mark="# Installed by hammunition-tray (hammunition-devctl, D-056)."
    local -a as_root
    read -r -a as_root <<<"${HAMMUNITION_DEVCTL_SUDO-sudo}"

    command -v python3 >/dev/null || { echo "python3 is not on PATH." >&2; exit 1; }
    if package_owns_helper "${root}" "${policy}"; then
        echo
        echo "The helper is installed by the hammunition-devctl package (apt); not"
        echo "replaced. Upgrade or remove it with apt."
        return 0
    fi
    local risky
    risky="$(non_root_owned_component "${interpreter}")"
    if [[ -n "${risky}" ]]; then
        echo "Note: ${risky} is owned by a non-root account, and the wrapper will run" >&2
        echo "${interpreter} as root through polkit: whoever owns that tree can run" >&2
        echo "code as root by editing it. The documented engine install (a venv under" >&2
        echo "\$HOME) is this shape; the helper refuses a tree any account can write." >&2
    fi
    if ! "${interpreter}" -c 'import yaml' 2>/dev/null; then
        echo "Note: ${interpreter} cannot import yaml (python3-yaml); the helper" >&2
        echo "needs it to read its data files. Install python3-yaml, or point" >&2
        echo "--interpreter at a Python that has it." >&2
    fi

    if [[ -e "${root}${wrapper}" ]] && ! grep -qxF "${mark}" "${root}${wrapper}" && [[ ${force_helper} -eq 0 ]]; then
        echo
        echo "The helper at ${wrapper} was written by another installer (the"
        echo "Hammunition engine's 'hardware apply' does). Left alone."
        echo "Re-run with --force-helper to replace it with this one."
        return 0
    fi

    tmp="$(mktemp -d)"
    trap 'rm -rf "${tmp:-}"' EXIT
    python3 "${src}/scripts/render_helper_files.py" wrapper "${interpreter}" "${libdir}/hammunition-devctl" >"${tmp}/wrapper"
    python3 "${src}/scripts/render_helper_files.py" policy >"${tmp}/policy"

    local -a pyfiles=()
    local f
    for f in "${src}"/devctl/hammunition_devctl/*.py; do
        pyfiles+=("${f}")
    done

    echo
    echo "The device helper needs these root-owned files (docs/contract.md):"
    echo "  ${root}${libdir}/hammunition-devctl           (entry, 0755)"
    echo "  ${root}${libdir}/hammunition_devctl/*.py      (${#pyfiles[@]} files, 0644)"
    echo "  ${root}${wrapper}      (wrapper running ${interpreter}, 0755)"
    echo "  ${root}${policy}"
    echo "It is copied, not linked: root never runs code from this checkout."

    if [[ ${assume_yes} -eq 0 ]]; then
        if [[ ! -t 0 ]]; then
            echo "Not a terminal and no --yes: helper NOT installed. Re-run with --yes." >&2
            return 0
        fi
        read -r -p "Install them now${as_root[0]:+ with ${as_root[0]}}? [y/N] " answer
        [[ ${answer} == [yY]* ]] || { echo "Helper not installed."; return 0; }
    fi

    # A module an older version shipped and this one does not must not survive.
    "${as_root[@]}" rm -rf -- "${root}${libdir}/hammunition_devctl"
    "${as_root[@]}" install -d -m 0755 "${root}${libdir}" "${root}${libdir}/hammunition_devctl" \
        "$(dirname "${root}${wrapper}")" "$(dirname "${root}${policy}")"
    "${as_root[@]}" install -m 0755 "${src}/devctl/hammunition-devctl" "${root}${libdir}/hammunition-devctl"
    "${as_root[@]}" install -m 0644 "${pyfiles[@]}" "${root}${libdir}/hammunition_devctl/"
    "${as_root[@]}" install -m 0755 "${tmp}/wrapper" "${root}${wrapper}"
    "${as_root[@]}" install -m 0644 "${tmp}/policy" "${root}${policy}"

    echo "Helper installed. Check it: ${wrapper} --version"
}

if [[ ${want_applet} -eq 1 ]]; then
    install_applet
fi
if [[ ${want_helper} -eq 1 ]]; then
    install_helper
fi
