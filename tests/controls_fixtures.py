"""What ``hammunition-devctl services state`` and ``radio state`` print, in
every state the tray words differently. Shared by the Python logic tests and
the parity test that runs the applet's controlslogic.js over the same
documents.

The shapes are design D2 (helper contract version 1), reconciled against the
helper branch's docs/contract.md; where the two ever differ the contract
wins. Each case is a full document, as the helper prints it, so a key the
tray stops reading or starts misreading shows up here.
"""

import json
from copy import deepcopy


def svc(name, **kw):
    row = {
        "name": name,
        "unit": f"hammunition-{name}.service",
        "scope": "user",
        "description": f"the {name} service",
        "active": "active",
        "enabled": "enabled",
        "root": False,
    }
    row.update(kw)
    return row


def services_doc(*rows, linger=None, **kw):
    doc = {
        "kind": "services",
        "version": 1,
        "services": list(rows),
        "linger": linger or {"state": "off", "ours": False},
    }
    doc.update(kw)
    return doc


# Design D2's example, verbatim.
SERVICES_D2 = services_doc(
    {
        "name": "gps-tether",
        "unit": "hammunition-gps-tether.service",
        "scope": "user",
        "description": "GPS position for QMapShack and the browser map on 127.0.0.1",
        "active": "active",
        "enabled": "enabled",
        "root": False,
    },
    {
        "name": "gpsd",
        "unit": "gpsd.socket",
        "scope": "system",
        "description": "the GPS daemon (socket-activated)",
        "active": "active",
        "enabled": "enabled",
        "root": True,
    },
    {
        "name": "time",
        "unit": "ntpsec.service",
        "scope": "system",
        "description": "the clock",
        "active": "active",
        "enabled": "enabled",
        "root": True,
    },
    {
        "name": "gps-resume",
        "unit": "hammunition-gps-resume.service",
        "scope": "system",
        "description": "re-adds the receiver to gpsd after sleep",
        "active": "inactive",
        "enabled": "not-found",
        "root": True,
    },
    {
        "name": "rig",
        "unit": "hammunition-rigctld.service",
        "scope": "user",
        "description": "rigctld for this operator",
        "active": "inactive",
        "enabled": "not-found",
        "root": False,
    },
)


def radio(name, **kw):
    row = {"name": name, "present": True, "enabled": True, "method": "nmcli", "detail": ""}
    row.update(kw)
    return row


def radios_doc(*rows, **kw):
    doc = {"kind": "radios", "version": 1, "radios": list(rows)}
    doc.update(kw)
    return doc


RADIOS_D2 = radios_doc(
    {
        "name": "wwan",
        "present": True,
        "enabled": True,
        "method": "nmcli",
        "detail": "cdc-wdm0",
    },
    {"name": "wifi", "present": True, "enabled": True, "method": "nmcli", "detail": "wlan0"},
    {"name": "bluetooth", "present": True, "enabled": True, "method": "bluetoothctl", "detail": ""},
)


def doc_with(base, key, **changes):
    """A copy of a document with the first row's fields changed."""
    out = deepcopy(base)
    out[key][0].update(changes)
    return out


# name -> the helper's services document
SERVICES = {
    "d2": SERVICES_D2,
    "empty": services_doc(),
    "running": services_doc(svc("gps-tether")),
    "stopped": services_doc(svc("gps-tether", active="inactive")),
    "starting": services_doc(svc("gps-tether", active="activating")),
    "failed": services_doc(svc("gps-tether", active="failed")),
    "unknown-active": services_doc(svc("gps-tether", active="unknown")),
    "disabled-at-login": services_doc(svc("gps-tether", enabled="disabled")),
    "static": services_doc(svc("gps-tether", enabled="static")),
    "unknown-enabled": services_doc(svc("gps-tether", enabled="unknown")),
    "not-installed": services_doc(svc("rig", active="inactive", enabled="not-found")),
    # A value a newer helper might add: read as unknown, never offered.
    "future-states": services_doc(svc("gps-tether", active="reloading", enabled="masked")),
    "system": services_doc(svc("gpsd", scope="system", root=True, unit="gpsd.socket")),
    "newer-version": services_doc(svc("gps-tether"), version=2, extra_key="ignored"),
}

RADIOS = {
    "d2": RADIOS_D2,
    "empty": radios_doc(),
    "on": radios_doc(radio("wwan")),
    "off": radios_doc(radio("wwan", enabled=False, detail="cdc-wdm0")),
    "tool-missing": radios_doc(radio("bluetooth", present=False, enabled=False, method="bluetoothctl", detail="bluetoothctl is not installed")),
    "tool-missing-no-detail": radios_doc(radio("wifi", present=False, enabled=False, detail="")),
    "unknown-radio": radios_doc(radio("lora")),
    "newer-version": radios_doc(radio("wifi"), version=2, extra_key="ignored"),
}

_OLD = (
    "usage: hammunition-devctl [-h] {park,wake,state,linger,time} ...\n"
    "hammunition-devctl: error: argument verb: invalid choice: '%s' "
    "(choose from 'park', 'wake', 'state', 'linger', 'time')\n"
)

# (exit code, stdout, stderr) -> what the poll means
SERVICES_POLLS = {
    "ok": (0, json.dumps(SERVICES_D2) + "\n", ""),
    # A helper from before this contract: argparse refuses the verb.
    "old-helper": (2, "", _OLD % "services"),
    "missing": (127, "", "sh: 1: /usr/local/libexec/hammunition-devctl: not found\n"),
    "failed-with-stderr": (1, "", "error: boom\n"),
    "failed-silently": (1, "", ""),
    # Exit 2 that is the helper refusing, not argparse not knowing the verb.
    "refused": (2, "", "error: the Hammunition engine is not installed\n"),
    "not-json": (0, "note: something else answered\n", ""),
    "an-array": (0, "[]\n", ""),
    "null": (0, "null", ""),
    "wrong-kind": (0, json.dumps(RADIOS_D2), ""),
    "no-rows": (0, json.dumps({"kind": "services", "version": 1}), ""),
    "row-not-object": (0, json.dumps(services_doc("gps-tether")), ""),
    "row-without-name": (0, json.dumps(services_doc({"scope": "user"})), ""),
    "row-bad-scope": (0, json.dumps(services_doc(svc("x", scope="machine"))), ""),
    # Below the floor: a contract this tray does not speak.
    "version-0": (0, json.dumps(services_doc(version=0)), ""),
    "no-version": (0, json.dumps({"kind": "services", "services": []}), ""),
    "newer-version": (0, json.dumps(SERVICES["newer-version"]), ""),
}

RADIOS_POLLS = {
    "ok": (0, json.dumps(RADIOS_D2) + "\n", ""),
    "old-helper": (2, "", _OLD % "radio"),
    "missing": (127, "", "sh: 1: /usr/local/libexec/hammunition-devctl: not found\n"),
    "failed-with-stderr": (1, "", "error: boom\n"),
    "failed-silently": (1, "", ""),
    "refused": (2, "", "error: the Hammunition engine is not installed\n"),
    "not-json": (0, "note: something else answered\n", ""),
    "an-array": (0, "[]\n", ""),
    "null": (0, "null", ""),
    "wrong-kind": (0, json.dumps(SERVICES_D2), ""),
    "no-rows": (0, json.dumps({"kind": "radios", "version": 1}), ""),
    "row-without-name": (0, json.dumps(radios_doc({"present": True})), ""),
    "version-0": (0, json.dumps(radios_doc(version=0)), ""),
    "newer-version": (0, json.dumps(RADIOS["newer-version"]), ""),
}
