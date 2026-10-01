/*
 * Copyright (C) 2026 ChiefGyk3D
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import "timelogic.js" as TimeLogic

PlasmaExtras.Representation {
    id: full

    Layout.minimumWidth: Kirigami.Units.gridUnit * 20
    // Taller since the Time section: a heading, a sentence, any notes and
    // four modes under the device list.
    Layout.minimumHeight: Kirigami.Units.gridUnit * 20

    header: PlasmaExtras.PlasmoidHeading {
        RowLayout {
            anchors.fill: parent
            PlasmaExtras.Heading {
                Layout.fillWidth: true
                level: 4
                text: i18n("Radio devices")
            }
            PlasmaComponents.BusyIndicator {
                running: root.acting
                visible: running
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        // The helper is absent. Say what to run; a dead switch would be
        // worse than a sentence, because a switch implies it could work.
        PlasmaExtras.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.helperMissing
            iconName: "dialog-warning"
            text: i18n("Device control is not installed")
            explanation: i18n("Run `hammunition hardware apply` to install the helper and the polkit action that authorises it.")
        }

        PlasmaExtras.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !root.helperMissing && root.devices !== null && root.devices.length === 0
            iconName: Qt.resolvedUrl("../icons/hammunition-devices-awake.svg")
            text: i18n("No parkable device is attached")
            explanation: i18n("A device is parkable when its catalog entry carries a power_control block and it is plugged in now.")
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !root.helperMissing && root.devices !== null && root.devices.length > 0
            clip: true
            model: root.devices || []

            delegate: RowLayout {
                width: ListView.view ? ListView.view.width : 0
                spacing: Kirigami.Units.smallSpacing

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PlasmaComponents.Label {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        text: modelData.summary || modelData.name
                    }
                    PlasmaComponents.Label {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        opacity: 0.7
                        font: Kirigami.Theme.smallFont
                        // The bus address is what distinguishes two of a kind,
                        // and it is what the operator would type. A kept
                        // device says so whether or not it is still plugged
                        // in, and an absent one says that too.
                        text: modelData.attached === false
                            ? i18n("%1 at %2, kept off, not attached", modelData.name, modelData.address)
                            : (modelData.kept
                                ? i18n("%1 at %2, kept off", modelData.name, modelData.address)
                                : i18n("%1 at %2", modelData.name, modelData.address))
                    }
                }

                PlasmaComponents.Switch {
                    // Bound to the state the helper reported, and rebound
                    // immediately on toggle. A dismissed polkit prompt
                    // therefore leaves the switch showing the truth rather
                    // than the intent -- nothing was written, so nothing moves.
                    //
                    // Hidden for a device that is no longer attached: there is
                    // nothing to park or wake, only to forget.
                    visible: modelData.attached !== false
                    checked: !modelData.parked
                    enabled: !root.acting
                    onToggled: {
                        const wantAwake = checked;
                        checked = Qt.binding(() => !modelData.parked);
                        root.act(modelData, !wantAwake);
                    }
                }

                PlasmaComponents.Button {
                    // The only action left for a kept device that has been
                    // unplugged: "wake" on an absent device clears its kept
                    // flag, which is what drops it off this list.
                    visible: modelData.attached === false
                    enabled: !root.acting
                    text: i18n("Forget")
                    onClicked: root.forget(modelData)
                }
            }
        }

        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: root.lastError !== ""
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
            text: root.lastError
        }

        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: root.actionError !== ""
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
            text: root.actionError
        }

        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: !root.helperMissing
            wrapMode: Text.WordWrap
            opacity: 0.7
            font: Kirigami.Theme.smallFont
            // Stated because it used to be the single most surprising
            // property of the feature; the engine can now keep a device
            // off across reboots (Hammunition D-056), so the sentence no
            // longer claims a reboot always wakes everything.
            text: i18n("Off stays off across reboots until you turn it back on.")
        }

        // The Time section (Hammunition D-058): what the clock follows, and
        // the engine's four time modes. Every sentence comes from
        // timelogic.js, shared word for word with the Qt tray.
        Kirigami.Separator {
            Layout.fillWidth: true
            visible: !root.helperMissing
        }

        PlasmaExtras.Heading {
            Layout.fillWidth: true
            visible: !root.helperMissing
            level: 5
            text: i18n("Time")
        }

        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: !root.helperMissing
            wrapMode: Text.WordWrap
            // Greyed when the GPS cannot feed the clock: no ntpsec, or the
            // receiver is parked while the mode would use it. The note
            // below says which.
            opacity: root.timeGreyed ? 0.6 : 1.0
            text: TimeLogic.headline(root.timeState, root.timeUnsupported, root.tr)
        }

        Repeater {
            model: root.helperMissing ? [] : TimeLogic.notes(root.timeState, root.tr)
            delegate: PlasmaComponents.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                text: modelData
            }
        }

        Repeater {
            model: root.timeModes
            delegate: PlasmaComponents.RadioButton {
                Layout.fillWidth: true
                visible: !root.helperMissing && !root.timeUnsupported && root.timeState !== null
                // Disabled only where `time mode` would refuse: ntpsec is
                // not the daemon. A parked receiver greys the sentence but
                // the mode can still be changed, to ntp-only say.
                enabled: !root.acting && root.timeChoosable
                opacity: root.timeGreyed ? 0.6 : 1.0
                text: TimeLogic.modeLabel(modelData, root.tr)
                // Bound to the mode the helper reported and rebound on
                // toggle, so a dismissed prompt leaves the truth checked.
                checked: root.timeState !== null && root.timeState.mode === modelData
                onToggled: {
                    const wanted = modelData;
                    checked = Qt.binding(() => root.timeState !== null && root.timeState.mode === modelData);
                    root.setTimeMode(wanted);
                }
            }
        }

        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: !root.helperMissing && root.timeError !== ""
            wrapMode: Text.WordWrap
            color: Kirigami.Theme.negativeTextColor
            text: root.timeError
        }
    }
}
