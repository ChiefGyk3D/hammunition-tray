.pragma library
/*
 * Hammunition Devices - Plasma 6 applet
 * Copyright (C) 2026 ChiefGyk3D
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Controls panel's Services and Radios groups (helper contract v1), with
 * nothing of QML in them. This is qt/hammunition_tray_qt/controls.py
 * restated; the Qt tray runs that one. tests/test_controls_parity.py runs
 * both over the same helper documents and fails on any difference, so every
 * sentence and rule here must match it.
 *
 * Nothing here runs a command, but the applet builds a shell string from
 * what these functions return, so a name that came from the helper's output
 * is checked against the shape the helper itself accepts before it can reach
 * an argv.
 *
 * A library script has no QML context, so it cannot reach i18n itself: every
 * function that words something takes main.qml's `tr`, which is i18n.
 */

// The helper contract version this applet speaks. A document that says less
// is "update hammunition-tray", never an error; one that says more is read
// as far as this applet understands it. Recorded here and in controls.py,
// and nowhere else.
var CONTRACT_FLOOR = 1;

var SERVICE_VERBS = ["start", "stop", "enable", "disable"];
// The only radios the helper switches (`radio on|off wwan|wifi|bluetooth`).
var RADIO_NAMES = ["wwan", "wifi", "bluetooth"];

var ACTIVE = ["active", "inactive", "failed", "activating", "unknown"];
var ENABLED = ["enabled", "disabled", "static", "not-found", "unknown"];
var SCOPES = ["user", "system"];

// The helper's own shape for a name from its allow-list files.
var NAME = /^[a-z0-9][a-z0-9-]{0,63}$/;

// Every fixed sentence, by name; controls.py's STRINGS is the same table.
function strings(tr) {
    return {
        heading: tr("Controls"),
        group_devices: tr("Devices"),
        group_services: tr("Services"),
        group_radios: tr("Radios"),
        update: tr("update hammunition-tray"),
        login_label: tr("Start at login"),
        reading_services: tr("Reading services…"),
        reading_radios: tr("Reading radios…"),
        no_services: tr("No services are listed"),
        no_radios: tr("No radios are listed"),
        services_read_error: tr("Could not read the services list"),
        services_parse_error: tr("Could not parse the services list"),
        radios_read_error: tr("Could not read the radios list"),
        radios_parse_error: tr("Could not parse the radios list"),
        helper_run_error: tr("Could not run the device helper")
    };
}

function text(row, key) {
    var v = row[key];
    return typeof v === "string" ? v : "";
}

function document_(stdout, kind) {
    var doc = JSON.parse(stdout);
    if (doc === null || typeof doc !== "object" || Array.isArray(doc) || doc.kind !== kind)
        throw new Error("not a " + kind + " document");
    return doc;
}

function version(doc) {
    var v = doc.version;
    return typeof v === "number" && Math.floor(v) === v ? v : 0;
}

// Throws on anything but the document the helper always prints.
function parseServices(stdout) {
    var doc = document_(stdout, "services");
    if (!Array.isArray(doc.services)) throw new Error("no services list");
    var rows = doc.services.map(function (row) {
        if (row === null || typeof row !== "object" || Array.isArray(row))
            throw new Error("a row is not an object");
        if (typeof row.name !== "string" || row.name === "" || SCOPES.indexOf(row.scope) === -1)
            throw new Error("a row has no name or a scope this applet does not know");
        var active = text(row, "active");
        var enabled = text(row, "enabled");
        return {
            name: row.name,
            unit: text(row, "unit"),
            scope: row.scope,
            description: text(row, "description"),
            // A state a newer helper might add reads as unknown, which
            // nothing offers a switch for.
            active: ACTIVE.indexOf(active) === -1 ? "unknown" : active,
            enabled: ENABLED.indexOf(enabled) === -1 ? "unknown" : enabled,
            root: row.root === true
        };
    });
    var state = doc.linger !== null && typeof doc.linger === "object" ? doc.linger.state : null;
    return { rows: rows, linger_state: typeof state === "string" ? state : null };
}

function parseRadios(stdout) {
    var doc = document_(stdout, "radios");
    if (!Array.isArray(doc.radios)) throw new Error("no radios list");
    return doc.radios.map(function (row) {
        if (row === null || typeof row !== "object" || Array.isArray(row))
            throw new Error("a row is not an object");
        if (typeof row.name !== "string" || row.name === "") throw new Error("a row has no name");
        return {
            name: row.name,
            present: row.present === true,
            enabled: row.enabled === true,
            method: text(row, "method"),
            detail: text(row, "detail")
        };
    });
}

function argparseRefusal(stderr) {
    var low = (stderr || "").toLowerCase();
    return low.indexOf("invalid choice") !== -1 || low.indexOf("usage:") !== -1;
}

// {doc, unsupported, error, keep}: keep means the last good rows stay on
// screen, as the device list does after a failed read. kind is "services" or
// "radios".
function pollOutcome(kind, code, stdout, stderr, tr) {
    var s = strings(tr);
    var readError = kind === "services" ? s.services_read_error : s.radios_read_error;
    var parseError = kind === "services" ? s.services_parse_error : s.radios_parse_error;
    // Not there: the device poll says so, and the groups hide with it.
    if (code === 127) return { doc: null, unsupported: false, error: "", keep: false };
    // A helper without this verb: argparse refuses it, exit 2, "invalid
    // choice". Said once, as the group's one line, never as an error on
    // every poll. The helper's own refusals are exit 2 too, and those are
    // errors, not a request to update.
    if (code === 2 && argparseRefusal(stderr)) return { doc: null, unsupported: true, error: "", keep: false };
    if (code !== 0) {
        var err = (stderr || "").trim();
        return { doc: null, unsupported: false, error: err !== "" ? err : readError, keep: true };
    }
    var doc, parsed;
    try {
        var body = (stdout || "").trim();
        doc = kind === "services" ? parseServices(body) : parseRadios(body);
        parsed = JSON.parse(body);
    } catch (e) {
        return { doc: null, unsupported: false, error: parseError, keep: true };
    }
    if (version(parsed) < CONTRACT_FLOOR)
        return { doc: null, unsupported: true, error: "", keep: false };
    return { doc: doc, unsupported: false, error: "", keep: false };
}

function installed(row) {
    return row.enabled !== "not-found";
}

function runChecked(row) {
    return row.active === "active" || row.active === "activating";
}

function runVerb(row) {
    return runChecked(row) ? "stop" : "start";
}

function runEnabled(row, acting) {
    return !acting && installed(row) && row.active !== "unknown";
}

function loginChecked(row) {
    return row.enabled === "enabled";
}

function loginVerb(row) {
    return loginChecked(row) ? "disable" : "enable";
}

// `static` units have no [Install] section: there is nothing to enable.
function loginEnabled(row, acting) {
    return !acting && (row.enabled === "enabled" || row.enabled === "disabled");
}

function serviceLabel(row) {
    return row.name;
}

function serviceDetail(row, tr) {
    if (!installed(row)) return tr("%1: not installed", row.description);
    if (row.active === "failed") return tr("%1: failed", row.description);
    if (row.active === "activating") return tr("%1: starting", row.description);
    return row.description;
}

function radioLabel(row, tr) {
    switch (row.name) {
    case "wwan": return tr("Mobile broadband (WWAN)");
    case "wifi": return tr("Wi-Fi");
    case "bluetooth": return tr("Bluetooth");
    }
    return row.name;
}

function radioDetail(row, tr) {
    if (!row.present)
        return row.detail !== "" ? tr("not available: %1", row.detail) : tr("not available");
    return row.detail;
}

function radioVerb(row) {
    return row.enabled ? "off" : "on";
}

function radioEnabled(row, acting) {
    return !acting && row.present && RADIO_NAMES.indexOf(row.name) !== -1;
}

function usesPkexec(row) {
    return row.scope === "system";
}

// The argv words, program first. User scope runs the helper directly, system
// scope goes through pkexec by its path; anything the helper would not
// accept throws, so nothing odd reaches the shell string main.qml builds.
function serviceArgv(pkexec, helper, row, verb) {
    if (SERVICE_VERBS.indexOf(verb) === -1) throw new Error("refusing service verb");
    if (!NAME.test(row.name)) throw new Error("refusing service name");
    if (row.scope === "user") return [helper, "services", verb, row.name];
    if (row.scope === "system") return [pkexec, helper, "services", verb, row.name];
    throw new Error("refusing service scope");
}

function radioArgv(helper, row, on) {
    if (RADIO_NAMES.indexOf(row.name) === -1) throw new Error("refusing radio");
    return [helper, "radio", on ? "on" : "off", row.name];
}

// The one line for a verb run without pkexec that did not succeed, or "".
// The helper's first non-empty stderr line is its reason.
// May a poll that has just landed end the operator's pending requests? Only
// one that started after the last verb finished (see controls.py).
function pendingFresh(startedEpoch, epoch, acting) {
    return !acting && (startedEpoch === null || startedEpoch === epoch);
}

function directError(code, stderr, tr) {
    if (code === 0) return "";
    var lines = (stderr || "").split("\n");
    for (var i = 0; i < lines.length; i++) {
        var line = lines[i].trim();
        if (line !== "") return line;
    }
    return tr("Action failed (exit %1)", code);
}

// What the operator just asked for, until a poll says otherwise: a map from
// "service:NAME:active" | "service:NAME:enabled" | "radio:NAME:enabled" to
// the value that request expects.
function servicePending(verb, name) {
    switch (verb) {
    case "start": return ["service:" + name + ":active", "active"];
    case "stop": return ["service:" + name + ":active", "inactive"];
    case "enable": return ["service:" + name + ":enabled", "enabled"];
    case "disable": return ["service:" + name + ":enabled", "disabled"];
    }
    throw new Error("refusing service verb");
}

function radioPending(name, on) {
    return ["radio:" + name + ":enabled", on];
}

function copy(row) {
    var out = {};
    for (var k in row) out[k] = row[k];
    return out;
}

// The rows as the operator would see them if every pending request had
// worked. The real rows are never changed.
function effectiveServices(rows, pending) {
    return rows.map(function (row) {
        var out = copy(row);
        var active = pending["service:" + row.name + ":active"];
        var enabled = pending["service:" + row.name + ":enabled"];
        if (typeof active === "string") out.active = active;
        if (typeof enabled === "string") out.enabled = enabled;
        return out;
    });
}

function effectiveRadios(rows, pending) {
    return rows.map(function (row) {
        var out = copy(row);
        var on = pending["radio:" + row.name + ":enabled"];
        if (typeof on === "boolean") out.enabled = on;
        return out;
    });
}
