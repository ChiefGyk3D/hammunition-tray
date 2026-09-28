# Hammunition Devices - tray for desktops other than Plasma
# Copyright (C) 2026 ChiefGyk3D
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Qt half: a QSystemTrayIcon, a menu, and QProcess.

Every decision is made in logic.py; this file only turns state into widgets
and argv lists into processes. Nothing is ever run through a shell: QProcess
is given a program and a list, and the helper's output is only ever parsed
as JSON, never passed on to anything that runs.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import QLockFile, QObject, QProcess, QStandardPaths, QTimer
from PyQt6.QtGui import QAction, QCursor, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from . import logic
from .logic import MenuEntry, ProcResult, TrayState

# A poll that has not answered in this long is killed and reported as a
# failed read, rather than blocking every later poll behind it. pkexec gets
# no timeout: the operator may still be typing a password.
POLL_TIMEOUT_MS = 30_000

# From a checkout, where the icons are not installed into the theme.
_CHECKOUT_ICONS = Path(__file__).resolve().parents[2] / "plasmoid/package/contents/icons"
_CHECKOUT_FILES = {
    logic.ICON_AWAKE: "hammunition-devices-awake.svg",
    logic.ICON_PARKED: "hammunition-devices-parked.svg",
}

Done = Callable[[ProcResult], None]


class QtRunner:
    """Runs a program with an argument list and reports once when it ends."""

    def __init__(self, parent: QObject | None = None) -> None:
        self._parent = parent
        self._live: set[QProcess] = set()

    def run(self, program: str, args: list[str], done: Done, timeout_ms: int | None = None) -> None:
        proc = QProcess(self._parent)
        proc.setProgram(program)
        proc.setArguments(list(args))
        fired = False

        def finish(result: ProcResult) -> None:
            nonlocal fired
            if fired:
                return
            fired = True
            self._live.discard(proc)
            proc.deleteLater()
            done(result)

        def finished(code: int, status: QProcess.ExitStatus) -> None:
            out = bytes(proc.readAllStandardOutput().data()).decode(errors="replace")
            err = bytes(proc.readAllStandardError().data()).decode(errors="replace")
            crashed = status == QProcess.ExitStatus.CrashExit
            finish(ProcResult(started=True, crashed=crashed, code=code, stdout=out, stderr=err))

        def errored(error: QProcess.ProcessError) -> None:
            # Every other error is followed by finished(); this one is not.
            if error == QProcess.ProcessError.FailedToStart:
                finish(ProcResult(started=False))

        proc.finished.connect(finished)
        proc.errorOccurred.connect(errored)
        if timeout_ms is not None:
            timer = QTimer(proc)
            timer.setSingleShot(True)
            timer.timeout.connect(proc.kill)
            timer.start(timeout_ms)
        self._live.add(proc)
        proc.start()


def _menu_text(text: str) -> str:
    # QAction treats & as a mnemonic marker and a tab as the shortcut column;
    # a device summary or an error from stderr is text, not markup.
    return " ".join(text.replace("&", "&&").split())


class Tray(QObject):
    def __init__(self, runner: QtRunner | None = None) -> None:
        super().__init__()
        self.runner = runner or QtRunner(self)
        self.state = TrayState()
        self._polling = False
        self._repoll = False
        self._model: list[MenuEntry] | None = None

        self.menu = QMenu()
        self.icon = QSystemTrayIcon()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self.menu.aboutToShow.connect(self.refresh)

        self.timer = QTimer(self)
        self.timer.setInterval(logic.POLL_MS)
        self.timer.timeout.connect(self.refresh)
        self._render()

    def start(self) -> None:
        self.icon.show()
        self.timer.start()
        self.refresh()

    def close(self) -> None:
        self.timer.stop()
        self.icon.hide()

    # -- polling ---------------------------------------------------------

    def refresh(self) -> None:
        if self._polling:
            self._repoll = True
            return
        self._polling = True
        program, args = logic.poll_argv()
        self.runner.run(program, args, self._polled, timeout_ms=POLL_TIMEOUT_MS)

    def _polled(self, result: ProcResult) -> None:
        self._polling = False
        self.state, notice = logic.apply_poll(self.state, result)
        if notice:
            self.icon.showMessage("Kept off", notice, self._qicon(logic.ICON_PARKED), 10_000)
        self._render()
        if self._repoll:
            self._repoll = False
            self.refresh()

    # -- actions ---------------------------------------------------------

    def act(self, entry: MenuEntry) -> None:
        if self.state.acting or entry.verb is None or entry.device is None:
            return
        try:
            program, args = logic.action_argv(entry.verb, entry.device)
        except ValueError as exc:
            self.state = replace(self.state, last_error=str(exc))
            self._render(force=True)
            return
        self.state = logic.begin_action(self.state)
        self._render()
        self.runner.run(program, args, self._acted)

    def _acted(self, result: ProcResult) -> None:
        self.state = logic.apply_action(self.state, result)
        # Forced: a dismissed prompt leaves the model as it was before the
        # click, but the checkable item toggled itself when clicked.
        self._render(force=True)
        self.refresh()

    # -- drawing ---------------------------------------------------------

    def _qicon(self, name: str) -> QIcon:
        icon = QIcon.fromTheme(name)
        if icon.isNull() and name in _CHECKOUT_FILES:
            icon = QIcon(str(_CHECKOUT_ICONS / _CHECKOUT_FILES[name]))
        if icon.isNull():
            style = QApplication.style()
            if style is not None:
                icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        return icon

    def _render(self, force: bool = False) -> None:
        self.icon.setIcon(self._qicon(logic.icon_name(self.state)))
        self.icon.setToolTip(logic.tooltip(self.state))
        model = logic.menu_model(self.state)
        # Rebuilt only when something changed, so a menu the operator has
        # open is not torn down under the pointer every five seconds.
        if not force and model == self._model:
            return
        self._model = model
        self.menu.clear()
        for entry in model:
            if entry.kind == "separator":
                self.menu.addSeparator()
                continue
            action = QAction(_menu_text(entry.text), self.menu)
            action.setEnabled(entry.enabled)
            if entry.kind == "toggle":
                action.setCheckable(True)
                action.setChecked(bool(entry.checked))
            if entry.kind in ("toggle", "forget"):
                action.triggered.connect(lambda _=False, e=entry: self.act(e))
            elif entry.kind == "quit":
                action.triggered.connect(QApplication.quit)
            self.menu.addAction(action)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left click opens the same menu; a tray with only a right-click
        # menu hides the only thing it does.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.menu.popup(QCursor.pos())


def _wait_for_tray(seconds: int) -> bool:
    """At login the panel may not be up yet. Wait for it, bounded."""
    deadline = time.monotonic() + seconds
    while not QSystemTrayIcon.isSystemTrayAvailable():
        if time.monotonic() >= deadline:
            return False
        QApplication.processEvents()
        time.sleep(0.5)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hammunition-tray-qt",
        description="Park and wake Hammunition's parkable radio devices from the system tray.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        metavar="SECONDS",
        help="wait up to SECONDS for a system tray to appear (used at login)",
    )
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("hammunition-tray-qt")
    app.setDesktopFileName("hammunition-tray-qt")
    app.setQuitOnLastWindowClosed(False)

    if not _wait_for_tray(max(0, args.wait)):
        print(
            "hammunition-tray-qt: no system tray on this desktop "
            "(GNOME needs the AppIndicator extension); exiting",
            file=sys.stderr,
        )
        return 0

    runtime = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
    lock = QLockFile(f"{runtime}/hammunition-tray-qt.lock") if runtime else None
    if lock is not None and not lock.tryLock(0):
        print("hammunition-tray-qt: already running in this session", file=sys.stderr)
        return 0

    tray = Tray()
    tray.start()
    return app.exec()
