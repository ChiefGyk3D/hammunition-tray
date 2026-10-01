"""What ``hammunition-devctl time state`` prints, in every state the tray
words differently. Shared by the Python logic tests and the parity test that
runs the applet's timelogic.js over the same objects.

The shape is the engine's ``hammunition.gpstime.state.JSON_KEYS`` (Hammunition
0.18.0, D-058). Each case is a full object, as the helper prints it, so a key
the tray stops reading or starts misreading shows up here."""

import json

BASE = {
    "mode": "auto",
    "mode_set": True,
    "daemon": "ntpsec",
    "gps": "awake",
    "following": "gps",
    "offset_ms": 3.25,
    "last_sync": "2026-09-28T14:44:47.433000+00:00",
    "last_source": "gps",
    "holdover_seconds": None,
    "rtc": True,
    "grants": True,
    "dhcp_config": False,
    "problems": [],
}


def state(**kw):
    row = dict(BASE)
    row.update(kw)
    return row


# name -> the helper's object
STATES = {
    "follows-gps": state(),
    "follows-network": state(following="network", offset_ms=0.25, last_source="network"),
    "follows-network-negative-tie": state(following="network", offset_ms=-0.25),
    "follows-network-tiny-negative": state(following="network", offset_ms=-0.04),
    "follows-gps-no-offset": state(offset_ms=None),
    "holdover": state(following="none", offset_ms=None, holdover_seconds=7500),
    "holdover-days": state(following="none", offset_ms=None, holdover_seconds=90_000),
    "holdover-just-now": state(following="none", offset_ms=None, holdover_seconds=12),
    "never-synchronised": state(
        following="none", offset_ms=None, last_sync=None, last_source=None
    ),
    # ntpq got no answer: the engine says so in problems.
    "ntpd-silent": state(
        following="unknown",
        offset_ms=None,
        last_sync=None,
        last_source=None,
        problems=[
            "ntpq got no answer from ntpd; `systemctl status ntpsec` says whether it is running"
        ],
    ),
    # Debian, Ubuntu, Kali: systemd-timesyncd, which cannot read a GPS.
    "timesyncd": state(
        mode_set=False,
        daemon=None,
        following="unknown",
        offset_ms=None,
        last_sync=None,
        last_source=None,
        grants=False,
    ),
    # `apt remove ntpsec` left /etc/ntpsec/ntp.conf behind: still null.
    "ntpsec-removed-conffile-left": state(
        mode="gps-only",
        daemon=None,
        following="unknown",
        offset_ms=None,
        last_sync=None,
        last_source=None,
        grants=False,
    ),
    "parked-auto": state(gps="parked", following="network", offset_ms=0.5),
    "parked-gps-only": state(
        mode="gps-only", gps="parked", following="none", offset_ms=None, holdover_seconds=600
    ),
    "parked-ntp-only": state(mode="ntp-only", gps="parked", following="network", offset_ms=1.0),
    "absent-gps-only": state(
        mode="gps-only", gps="absent", following="none", offset_ms=None, holdover_seconds=60
    ),
    "absent-auto": state(gps="absent", following="network", offset_ms=0.1),
    # A receiver awake but ntpd without its grants: not "run hardware apply".
    "awake-no-grants": state(grants=False, following="network", offset_ms=0.3),
    "awake-no-grants-ntp-only": state(
        mode="ntp-only", grants=False, following="network", offset_ms=0.3
    ),
    # No gpsd: apply declines the grants, so they stay false for good.
    "no-gpsd": state(gps="absent", grants=False, following="network", offset_ms=0.3),
    "dhcp": state(dhcp_config=True, following="network", offset_ms=0.2),
    "no-rtc": state(rtc=False),
    "default-mode-never-set": state(mode_set=False),
    "prefer-gps": state(mode="prefer-gps"),
    "mode-file-unreadable": state(
        mode_set=False, problems=["/etc/hammunition/time.yaml: not a time mode file"]
    ),
    # A mode a newer engine might add: shown, never offered.
    "unknown-mode": state(mode="gps-pps"),
}

# (exit code, stdout, stderr) -> what the poll means
POLLS = {
    "ok": (0, json.dumps(BASE) + "\n", ""),
    # An engine older than 0.18.0: argparse refuses the verb.
    "old-engine": (
        2,
        "",
        "usage: hammunition-devctl [-h] {park,wake,state} ...\n"
        "hammunition-devctl: error: argument verb: invalid choice: 'time' "
        "(choose from 'park', 'wake', 'state')\n",
    ),
    "missing": (127, "", "sh: 1: /usr/local/libexec/hammunition-devctl: not found\n"),
    "failed-with-stderr": (1, "", "error: boom\n"),
    "failed-silently": (1, "", ""),
    "not-json": (0, "note: something else answered\n", ""),
    "an-array": (0, "[]\n", ""),
    "no-mode": (0, json.dumps({"daemon": "ntpsec"}), ""),
    "null": (0, "null", ""),
}
