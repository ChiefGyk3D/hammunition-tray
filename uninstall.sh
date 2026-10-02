#!/usr/bin/env bash
# Remove the Hammunition Devices applet for the current user.
#
#   ./uninstall.sh            the applet only
#   ./uninstall.sh --helper   also the device helper this repository installed
#   ./uninstall.sh --helper-only
#   ./uninstall.sh --yes      do not ask before running sudo
#
# The helper is removed only when the wrapper at
# /usr/local/libexec/hammunition-devctl carries this repository's mark. A
# wrapper the Hammunition engine's `hardware apply` wrote is not ours, and
# neither is the polkit action beside it, so both are left; `hammunition
# hardware unapply` removes those. The helper's data files under
# /etc/hammunition and the kept-off rules are never touched here.
#
# For tests and packaging only: HAMMUNITION_DEVCTL_ROOT=DIR and
# HAMMUNITION_DEVCTL_SUDO="" as in install.sh.
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
    echo "Do not run this as root; the applet lives in your own home." >&2
    exit 1
fi

want_applet=1
want_helper=0
assume_yes=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --helper) want_helper=1 ;;
        --helper-only) want_helper=1; want_applet=0 ;;
        --yes | -y) assume_yes=1 ;;
        -h | --help)
            sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

remove_applet() {
    command -v kpackagetool6 >/dev/null || { echo "kpackagetool6 is not on PATH." >&2; exit 1; }

    kpackagetool6 --type Plasma/Applet --remove com.chiefgyk3d.hammunition.devices
    rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/hammunition-devices.svg"
    echo "Applet removed."
}

# True when the hammunition-devctl .deb installed the helper (see install.sh).
package_owns_helper() {
    local root="$1" policy="$2"
    [[ -d "${root}/usr/share/hammunition-devctl" ]] && return 0
    command -v dpkg-query >/dev/null && dpkg-query -S "${root}${policy}" >/dev/null 2>&1
}

remove_helper() {
    local root="${HAMMUNITION_DEVCTL_ROOT:-}"
    local libdir="/usr/local/lib/hammunition-devctl"
    local wrapper="/usr/local/libexec/hammunition-devctl"
    local policy="/usr/share/polkit-1/actions/com.chiefgyk3d.hammunition.devctl.policy"
    local mark="# Installed by hammunition-tray (hammunition-devctl, D-056)."
    local -a as_root
    read -r -a as_root <<<"${HAMMUNITION_DEVCTL_SUDO-sudo}"

    if package_owns_helper "${root}" "${policy}"; then
        echo "The helper is installed by the hammunition-devctl package (apt); remove it"
        echo "with \`sudo apt remove hammunition-devctl\`. Left alone."
        return 0
    fi
    if [[ ! -e "${root}${wrapper}" ]]; then
        echo "No helper at ${wrapper}; nothing to remove."
        return 0
    fi
    if ! grep -qxF "${mark}" "${root}${wrapper}"; then
        echo "${wrapper} was not written by this repository (the engine's"
        echo "'hardware apply' writes one too). Left alone, and so is the polkit"
        echo "action: \`hammunition hardware unapply\` removes both."
        return 0
    fi

    echo "Removing, as root:"
    echo "  ${root}${wrapper}"
    echo "  ${root}${policy}"
    echo "  ${root}${libdir}/"
    if [[ ${assume_yes} -eq 0 ]]; then
        if [[ ! -t 0 ]]; then
            echo "Not a terminal and no --yes: helper NOT removed. Re-run with --yes." >&2
            return 0
        fi
        read -r -p "Remove them now? [y/N] " answer
        [[ ${answer} == [yY]* ]] || { echo "Helper kept."; return 0; }
    fi

    "${as_root[@]}" rm -f -- "${root}${wrapper}" "${root}${policy}"
    "${as_root[@]}" rm -rf -- "${root}${libdir}"
    echo "Helper removed."
}

if [[ ${want_applet} -eq 1 ]]; then
    remove_applet
    if [[ ${want_helper} -eq 0 ]]; then
        echo "The helper and polkit action are untouched; use --helper to remove"
        echo "this repository's, or \`hammunition hardware unapply\` for the engine's."
    fi
fi
if [[ ${want_helper} -eq 1 ]]; then
    remove_helper
fi
