/*
 * Copyright (C) 2026 ChiefGyk3D
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

MouseArea {
    id: compact

    Layout.minimumWidth: Kirigami.Units.iconSizes.small
    Layout.minimumHeight: Kirigami.Units.iconSizes.small

    hoverEnabled: true
    acceptedButtons: Qt.LeftButton
    onClicked: root.expanded = !root.expanded

    Kirigami.Icon {
        anchors.fill: parent
        // One icon, three states, no text: the tray gives every item a
        // square. "Something is parked" is the only state worth a glance --
        // the penguin loses its signal and the disc goes grey. A missing
        // helper is worth the popup's sentence, so it stays the theme's
        // warning icon. Both SVGs ship inside the package: no icon theme,
        // no install step of their own.
        source: root.helperMissing
            ? "dialog-warning"
            : Qt.resolvedUrl(root.anyParked
                ? "../icons/hammunition-devices-parked.svg"
                : "../icons/hammunition-devices-awake.svg")
        active: compact.containsMouse
    }
}
