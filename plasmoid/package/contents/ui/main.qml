/*
 * Hammunition Devices - Plasma 6 applet
 * Copyright (C) 2026 ChiefGyk3D
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A switch per parkable radio device. Parking writes 0 to the device's sysfs
 * `authorized`, so the kernel drops its interfaces and the port can suspend;
 * waking writes 1. Nothing here touches sysfs and nothing here runs as root:
 * every write goes through Hammunition's own helper behind one polkit action
 * (D-056), and this applet is a client of that engine, not part of it.
 */
import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.notification

PlasmoidItem {
    id: root

    // The wrapper `hammunition hardware apply` installs. The polkit action
    // authorises this exact path, so it is a constant here rather than
    // something discovered -- a path we went looking for would be a second
    // value crossing the privilege boundary.
    readonly property string helper: "/usr/local/libexec/hammunition-devctl"

    // Parsed `devctl state`: an array of parkable attached devices. Null
    // until the first poll returns, which is why "no devices" and "not polled
    // yet" are distinguishable in the UI.
    property var devices: null

    // True once a poll has come back saying the helper is not there. Shown as
    // a sentence with the fix in it, never as a dead switch -- a switch that
    // cannot work is worse than an explanation.
    property bool helperMissing: false

    // The poll's error, replaced by every poll.
    property string lastError: ""
    // The last park or wake's error, kept apart because every action is
    // followed at once by a poll: when one lastError served both, that poll
    // cleared the action's error as it appeared. Cleared when the next
    // action starts, never by a poll.
    property string actionError: ""
    property bool acting: false

    // True once the login notice has been sent for this load of the applet.
    // A poll runs every few seconds; without this guard the same kept
    // devices would renotify on every tick rather than once per login.
    property bool keptNoticeSent: false

    readonly property int parkedCount: {
        if (!devices) return 0;
        let n = 0;
        for (const d of devices) if (d.attached !== false && d.parked) n += 1;
        return n;
    }

    readonly property bool anyParked: parkedCount > 0

    Notification {
        id: keptNotice
        componentName: "plasma_workspace"
        eventId: "notification"
        iconName: "hammunition-devices"
        title: i18n("Kept off")
    }

    // Checked once, on the first poll after the applet loads (i.e. after
    // login) -- not on every poll tick. A device kept later in the session
    // was just switched off by the operator, who was already watching it
    // happen, so it is not announced.
    function noticeKept() {
        if (!keptNoticeSent && devices) {
            keptNoticeSent = true;
            const names = devices
                .filter(d => d.attached !== false && d.parked && d.kept)
                .map(d => d.summary || d.name);
            if (names.length > 0) {
                keptNotice.text = names.join(", ");
                keptNotice.sendEvent();
            }
        }
    }

    // `state` needs no privilege -- reading sysfs does not, only writing does
    // -- so the poll runs the helper directly and no prompt appears for it.
    function refresh() {
        exec.run(helper + " state");
    }

    // NAME@ADDRESS, always. Two receivers of one class share a catalog name
    // and differ only in bus address; the helper refuses a bare name in that
    // case rather than guessing, so qualifying it here means the switch works
    // whether one or two are plugged in.
    function target(device) {
        return device.name + "@" + device.address;
    }

    function act(device, park) {
        if (acting) return;
        acting = true;
        lastError = "";
        actionError = "";
        exec.run("pkexec " + helper + " " + (park ? "park " : "wake ") + target(device));
    }

    // An unplugged kept device has nothing to wake, but the same "wake"
    // verb clears its kept flag -- that is what lets it drop off the list
    // instead of showing "kept off" forever for a device that is gone.
    function forget(device) {
        if (acting) return;
        acting = true;
        lastError = "";
        actionError = "";
        exec.run("pkexec " + helper + " wake " + target(device));
    }

    Plasma5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []

        onNewData: (source, data) => {
            disconnectSource(source);
            root.handleResult(source, data);
        }

        function run(cmd) {
            connectSource(cmd);
        }
    }

    function handleResult(source, data) {
        const stdout = (data["stdout"] || "").trim();
        const stderr = (data["stderr"] || "").trim();
        const code = data["exit code"];

        if (source.indexOf(" state") !== -1 && source.indexOf("pkexec") === -1) {
            // 127 from a direct (non-pkexec) run is the shell saying the
            // binary is not there. Unambiguous here precisely because the
            // poll does not go through pkexec, which overloads 127.
            if (code === 127) {
                helperMissing = true;
                devices = null;
                return;
            }
            helperMissing = false;
            if (code !== 0) {
                lastError = stderr !== "" ? stderr : i18n("Could not read device state");
                return;
            }
            try {
                devices = JSON.parse(stdout);
                lastError = "";
                root.noticeKept();
            } catch (e) {
                // The helper always prints a JSON array, including an empty
                // one, so a parse failure means something else answered.
                lastError = i18n("Could not parse the device list");
            }
            return;
        }

        // A park or wake finished. pkexec exits 126 when the prompt is
        // dismissed and 127 when authorisation is refused; neither is an
        // error worth showing, because nothing was written either way. The
        // switch has already snapped back to the real state, so the operator
        // can see nothing happened. The one 127 that is said: no polkit
        // agent at all, where every click would otherwise do nothing and say
        // nothing (the Qt tray's rule, here for parity).
        acting = false;
        if (code === 127 && stderr.toLowerCase().indexOf("no authentication agent") !== -1) {
            actionError = i18n("No polkit authentication agent is running, so no password prompt could appear. Install one (polkit-kde-agent-1) and log in again.");
        } else if (code !== 0 && code !== 126 && code !== 127) {
            actionError = stderr !== "" ? stderr : i18n("Action failed (exit %1)", code);
        }
        refresh();
    }

    Timer {
        interval: Plasmoid.configuration.pollSeconds * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    Plasmoid.status: root.anyParked
        ? PlasmaCore.Types.ActiveStatus
        : PlasmaCore.Types.PassiveStatus

    toolTipMainText: i18n("Hammunition Devices")
    toolTipSubText: {
        if (helperMissing) return i18n("Hammunition's device helper is not installed");
        if (!devices) return i18n("Reading device state…");
        if (devices.length === 0) return i18n("No parkable device is attached");
        return i18np("%1 device parked", "%1 devices parked", parkedCount);
    }

    compactRepresentation: CompactRepresentation {}
    fullRepresentation: FullRepresentation {}
}
