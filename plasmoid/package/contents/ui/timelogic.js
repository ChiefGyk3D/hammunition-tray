.pragma library
/*
 * Hammunition Devices - Plasma 6 applet
 * Copyright (C) 2026 ChiefGyk3D
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Time section's rules (Hammunition D-058), with nothing of QML in them.
 * This is qt/hammunition_tray_qt/timelogic.py restated; the Qt tray runs that
 * one. tests/test_time_parity.py runs both over the same helper outputs and
 * fails on any difference, so every sentence and rule here must match it.
 *
 * A library script has no QML context, so it cannot reach i18n itself: every
 * function that words something takes main.qml's `tr`, which is i18n.
 */

var MODES = ["auto", "prefer-gps", "ntp-only", "gps-only"];

// The engine release that added `time state`.
var ENGINE_FLOOR = "0.18.0";

// Which of the applet's commands a finished source was. The order matters:
// " services state", " radio state" and " time state" must each be tested
// before " state", which they all contain: the other way round, any of them
// would be parsed as the device list. A command through pkexec is an action
// (park, wake, a time mode or a system service verb), never a poll. A user
// service verb or a radio verb runs the helper directly and is "control".
// (It lives in this file, rather than controlslogic.js, because main.qml
// has always dispatched through it; test_controls_parity pins every case.)
function sourceKind(source) {
    if (source.indexOf("pkexec") !== -1) return "action";
    if (source.indexOf(" services state") !== -1) return "services";
    if (source.indexOf(" radio state") !== -1) return "radios";
    if (source.indexOf(" time state") !== -1) return "time";
    if (source.indexOf(" state") !== -1) return "devices";
    if (source.indexOf(" services ") !== -1 || source.indexOf(" radio ") !== -1) return "control";
    return "action";
}

function optStr(row, key) {
    var v = row[key];
    return typeof v === "string" ? v : null;
}

function optNum(row, key) {
    var v = row[key];
    return typeof v === "number" ? v : null;
}

// Throws on anything but the object the helper always prints.
function parseTimeState(stdout) {
    var row = JSON.parse(stdout);
    if (row === null || typeof row !== "object" || Array.isArray(row)
        || typeof row.mode !== "string")
        throw new Error("not a time state object");
    var holdover = optNum(row, "holdover_seconds");
    return {
        mode: row.mode,
        mode_set: row.mode_set === true,
        daemon: optStr(row, "daemon"),
        gps: optStr(row, "gps") || "absent",
        following: optStr(row, "following") || "unknown",
        offset_ms: optNum(row, "offset_ms"),
        last_sync: optStr(row, "last_sync"),
        last_source: optStr(row, "last_source"),
        holdover_seconds: holdover === null ? null : Math.trunc(holdover),
        // Absent is "not reported", not "no RTC".
        rtc: row.rtc !== false,
        grants: row.grants === true,
        dhcp_config: row.dhcp_config === true,
        problems: Array.isArray(row.problems)
            ? row.problems.filter(function (p) { return typeof p === "string"; })
            : []
    };
}

// {state, unsupported, error, keep}: keep means the last good state stays
// on screen, as the device list does after a failed read.
function pollOutcome(code, stdout, stderr, tr) {
    // Not there: the device poll says so, and the section hides with it.
    if (code === 127) return { state: null, unsupported: false, error: "", keep: false };
    // An engine older than D-058: argparse refuses the verb, exit 2. Said
    // once, as the section's one line, never as an error on every poll.
    if (code === 2) return { state: null, unsupported: true, error: "", keep: false };
    if (code !== 0) {
        var err = (stderr || "").trim();
        return { state: null, unsupported: false,
                 error: err !== "" ? err : tr("Could not read the time state"), keep: true };
    }
    try {
        return { state: parseTimeState((stdout || "").trim()), unsupported: false,
                 error: "", keep: false };
    } catch (e) {
        return { state: null, unsupported: false,
                 error: tr("Could not parse the time state"), keep: true };
    }
}

// The GPS cannot feed the clock: no ntpsec, or the receiver is parked while
// the mode would use it.
function greyed(t) {
    if (!t) return false;
    return t.daemon !== "ntpsec" || (t.gps === "parked" && t.mode !== "ntp-only");
}

function canChoose(t, unsupported) {
    return !unsupported && !!t && t.daemon === "ntpsec";
}

function modeLabel(mode, tr) {
    switch (mode) {
    case "auto": return tr("Automatic (the default)");
    case "prefer-gps": return tr("Prefer the GPS");
    case "ntp-only": return tr("Network only");
    case "gps-only": return tr("GPS only");
    }
    return mode;
}

// The engine's format_duration.
function duration(seconds, tr) {
    var minutes = Math.floor(seconds / 60);
    var hours = Math.floor(minutes / 60);
    minutes = minutes % 60;
    var days = Math.floor(hours / 24);
    hours = hours % 24;
    if (days) return tr("%1 d %2 h", days, hours);
    if (hours) return tr("%1 h %2 min", hours, minutes);
    return tr("%1 min", minutes);
}

// Half away from zero, by hand: toFixed and Python's format disagree on ties.
function signedMs(ms) {
    var tenths = Math.floor(Math.abs(ms) * 10 + 0.5);
    var sign = ms < 0 && tenths !== 0 ? "-" : "+";
    return sign + Math.floor(tenths / 10) + "." + (tenths % 10);
}

function headline(t, unsupported, tr) {
    if (unsupported)
        return tr("Update Hammunition to %1 or later to see and set the time source here.", ENGINE_FLOOR);
    if (!t) return tr("Reading time state…");
    if (t.daemon !== "ntpsec") return tr("GPS time unavailable: ntpsec is not this machine's time daemon");
    if (t.following === "gps") {
        if (t.offset_ms === null) return tr("The clock follows the GPS");
        return tr("The clock follows the GPS (offset %1 ms)", signedMs(t.offset_ms));
    }
    if (t.following === "network") {
        if (t.offset_ms === null) return tr("The clock follows the network");
        return tr("The clock follows the network (offset %1 ms)", signedMs(t.offset_ms));
    }
    if (t.following === "none") {
        // UTC, as the helper prints it and `hammunition time` says it.
        var found = /T(\d\d:\d\d)/.exec(t.last_sync || "");
        if (found)
            return tr("Holdover since %1 UTC (%2): nothing is setting the clock",
                      found[1], duration(t.holdover_seconds || 0, tr));
        return tr("Nothing is setting the clock, and ntpd has not synchronised since it started");
    }
    return tr("Time source unknown");
}

function notes(t, tr) {
    if (!t) return [];
    if (t.daemon !== "ntpsec") return t.problems.slice();
    var out = [];
    if (t.gps === "parked" && t.mode !== "ntp-only")
        out.push(tr("GPS time off: the receiver is parked"));
    else if (t.gps === "absent" && t.mode === "gps-only")
        out.push(tr("No GPS receiver is attached, so gps-only has nothing to follow"));
    // Not "run hammunition hardware apply": without gpsd, apply declines
    // the grants, and `grants` stays false however often it is run.
    if (t.gps === "awake" && t.mode !== "ntp-only" && !t.grants)
        out.push(tr("ntpd cannot read the GPS's time yet; `hammunition time` says what it needs"));
    if (t.dhcp_config)
        out.push(tr("ntpd was started on a DHCP-supplied configuration, so the mode may not apply; `hammunition time` says how to change that"));
    return out.concat(t.problems);
}

function rtcNote(t, tr) {
    return t && !t.rtc ? tr("No hardware clock: the time is lost at power-off with no network or GPS") : "";
}
