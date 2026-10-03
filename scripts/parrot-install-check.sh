#!/usr/bin/env bash
# Install the three .debs in a Parrot container, check their files, and
# remove them cleanly. Run by the release workflow's verify-command, with the
# directory holding the .debs as the one argument (default: dist).
#
# Parrot's mirrors fail now and then. A fetch failure exits the container
# with 75; the check is retried (the second and third attempts use the
# official mirror https://mirror.parrot.sh/direct) and, when all three fail on
# the mirror, reported in the step summary and tolerated, so a mirror outage
# does not block a release. Any other failure is a failure.
set -euo pipefail
dist="$(cd "${1:-dist}" && pwd)"
set -euo pipefail
for attempt in 1 2 3; do
  if docker run --rm \
    -e DEBIAN_FRONTEND=noninteractive \
    -e PARROT_MIRROR_ATTEMPT="$attempt" \
    -v "$dist:/dist:ro" \
    docker.io/parrotsec/core:latest bash -c '
  set -euxo pipefail
  if [ "$PARROT_MIRROR_ATTEMPT" -ge 2 ]; then
    # Official Parrot mirror list: https://parrotsec.org/docs/mirror-list
    find /etc/apt -type f \( -name "*.list" -o -name "*.sources" \) \
      -exec sed -i -E "s@https?://[^/[:space:]]*parrot[^/[:space:]]*(/direct)?@https://mirror.parrot.sh/direct@g" {} +
    grep -Rqs "https://mirror.parrot.sh/direct/parrot" /etc/apt
    ! grep -Rqs "direct/direct" /etc/apt
  fi
  apt_fetch() {
    local log status
    log="$(mktemp)"
    if "$@" 2>&1 | tee "$log"; then
      rm -f "$log"
      return 0
    else
      status=$?
    fi
    if grep -Eiq "Failed to fetch|Could not resolve|Could not connect|Connection failed|Network is unreachable|Temporary failure resolving|Connection timed out|TLS connection was non-properly terminated" "$log"; then
      rm -f "$log"
      exit 75
    fi
    rm -f "$log"
    return "$status"
  }
  apt_fetch apt-get update -qq -o APT::Update::Error-Mode=any
  apt_fetch apt-get install -y -qq /dist/hammunition-tray_*_all.deb
  d=/usr/share/plasma/plasmoids/com.chiefgyk3d.hammunition.devices
  test -f "$d/metadata.json"
  python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$d/metadata.json"
  test -f /usr/share/icons/hicolor/scalable/apps/hammunition-devices.svg
  apt-get remove -y -qq hammunition-tray
  test ! -e "$d"
  apt_fetch apt-get install -y -qq /dist/hammunition-tray-qt_*_all.deb
  test -x /usr/bin/hammunition-tray-qt
  test -f /usr/share/icons/hicolor/scalable/apps/hammunition-tray-qt-awake.svg
  grep -qx "NotShowIn=KDE;" /etc/xdg/autostart/hammunition-tray-qt.desktop
  # No tray in a container: one line on stderr and exit 0, which
  # also proves the launcher imports the installed module.
  out="$(QT_QPA_PLATFORM=offscreen timeout 60 hammunition-tray-qt 2>&1)"
  echo "$out" | grep -q "no system tray"
  apt-get remove -y -qq hammunition-tray-qt
  test ! -e /usr/bin/hammunition-tray-qt
  test ! -e /usr/share/hammunition-tray-qt
  # The helper: its files, the wrapper its postinst writes, the
  # contract number it answers through that wrapper, and a clean removal.
  apt_fetch apt-get install -y -qq /dist/hammunition-devctl_*_all.deb
  test -f /usr/share/polkit-1/actions/com.chiefgyk3d.hammunition.devctl.policy
  test "$(/usr/local/libexec/hammunition-devctl --version)" = "hammunition-devctl contract 1"
  /usr/local/libexec/hammunition-devctl services state | grep -qF "\"kind\": \"services\""
  apt-get remove -y -qq hammunition-devctl
  test ! -e /usr/local/libexec/hammunition-devctl
  test ! -e /usr/share/hammunition-devctl
  apt-get purge -y -qq hammunition-tray-qt
  test ! -e /etc/xdg/autostart/hammunition-tray-qt.desktop
    '; then
    exit 0
  else
    status=$?
  fi
  if [ "$status" -ne 75 ]; then
    exit "$status"
  fi
  if [ "$attempt" -eq 3 ]; then
    {
      echo "### Parrot install check failed"
      echo "Parrot install check was skipped due to the mirror after 3 attempts."
    } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    exit 0
  fi
  if [ "$attempt" -eq 1 ]; then
    sleep 10
  else
    sleep 30
  fi
done
