/*
 * Copyright (C) 2026 ChiefGyk3D
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    property alias cfg_pollSeconds: pollSeconds.value

    QQC2.SpinBox {
        id: pollSeconds
        Kirigami.FormData.label: i18n("Refresh every:")
        from: 2
        to: 60
        textFromValue: (value) => i18np("%1 second", "%1 seconds", value)
    }

    QQC2.Label {
        Kirigami.FormData.label: i18n("Reading state:")
        wrapMode: Text.WordWrap
        Layout.maximumWidth: Kirigami.Units.gridUnit * 18
        text: i18n("Reading which devices are parked needs no privilege, so no password is asked for. Parking or waking one does, and prompts through polkit.")
    }
}
