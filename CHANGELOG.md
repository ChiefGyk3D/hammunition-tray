# Changelog

## [Unreleased]

### 0.5.0 (the Controls panel)

- **One "Controls" panel, three groups**, worded identically in the Plasma
  applet and the Qt tray: **Devices** (today's rows, unchanged),
  **Services** and **Radios**.
- **Services**, from `hammunition-devctl services state`: per row a running
  switch and a "Start at login" checkbox; "not installed" and no switch for
  a unit that is not installed (the helper lists it as `not-found`, never
  omits it). A user-scope service runs the helper directly with no prompt; a
  system-scope service goes through `/usr/bin/pkexec` and the same polkit
  action as park and wake.
- **Radios**, from `hammunition-devctl radio state`: one switch each for
  WWAN, Wi-Fi and Bluetooth, run directly. A radio whose tool is absent
  shows the helper's reason and is disabled.
- **The 5 s poll asks for all four documents** (`state`, `time state`,
  `services state`, `radio state`), each with its own error and guard so no
  poll clears another's. A helper that lacks a verb shows one line,
  "update hammunition-tray", for that group, never an error.
- **A switch moves at once**; the next poll confirms or contradicts it; a
  failed verb puts it back and shows the helper's one-line error, and a
  dismissed password prompt puts it back silently.
- A poll that was already running when a verb began cannot undo the
  switch: each poll records which verbs had finished when it started, and
  only one that started after the last verb ended may drop the request. A
  failed poll after a verb drops it too, so an intent nothing can confirm
  is not shown for ever.
- A user service named like a poll (`state`, `radio`, `pkexec-...`) cannot
  be mistaken for one: the applet tells finished commands apart by their
  shape, not by what they contain.
- **Helper contract version 1** is the floor, recorded once
  (`CONTRACT_FLOOR`, in `controls.py` and `controlslogic.js`, held equal by
  test) and compared with each document's `version`.
- Nothing odd can reach a command: only the four service verbs and the three
  radio names, and a service name only in the helper's own shape (the
  Plasma applet builds a shell string from it).
- The Plasma popup is now a scroll view, and its heading reads "Controls".
- New: `qt/hammunition_tray_qt/controls.py` and
  `plasmoid/package/contents/ui/controlslogic.js` (both packaged), and a
  parity test over every new fixture, string, argv and dispatch case.

## [0.4.0] - 2026-10-01

- A **Time** section in both the Plasma applet and the Qt tray, for
  Hammunition's GPS time (D-058, Hammunition 0.18.0 or later): what the
  clock follows now (the network, the GPS, or holdover since a time in UTC),
  and the engine's four modes to choose from: automatic, prefer the GPS,
  network only, GPS only. Reading polls `hammunition-devctl time state`
  with no password; choosing a mode is one polkit prompt for
  `pkexec hammunition-devctl time mode MODE`, and no string but those four
  reaches it.
- Greyed, with the reason, when the GPS cannot feed the clock: ntpsec is
  not the time daemon (the modes are disabled then, since the engine would
  refuse them), or the receiver is parked while the mode would use it.
- An engine older than 0.18.0 is said once, as the section's one line
  ("Update Hammunition to 0.18.0 or later…"), never as an error on every
  poll; the poll keeps asking, so updating the engine brings the section in
  without logging out.
- The tooltip notes a machine with no hardware clock (RTC).
- Missing ntpd grants are noted without telling anyone to run
  `hammunition hardware apply`: on a machine without gpsd, apply declines
  them, so they stay missing however often it runs.
- The two front ends' wording and rules are one module each,
  `timelogic.js` and `timelogic.py`, and a test runs both over the same
  helper outputs and fails on any difference. CI now requires node for it.

## [0.3.0] - 2026-09-28

- **`hammunition-tray-qt`**, a second package from the same build: the
  applet's switch as a Qt tray icon for Xfce, LXQt, LXDE, MATE and Cinnamon.
  Same helper, same prompts, same texts; one menu item per parkable device,
  Forget for an unplugged kept one, one kept-off notice per login. Starts at
  login everywhere except Plasma (`NotShowIn=KDE;`), and exits 0 with one
  line on stderr where there is no system tray. Depends on `python3 (>= 3.11)`,
  `python3-pyqt6` and `pkexec | policykit-1`.
- **The applet's park and wake errors are shown again.** Every action is
  followed at once by a re-read of the device state, which cleared the one
  error line the two shared, so a failed action's error vanished as it
  appeared. An action's error now stays until the next action.
- Both front ends run `/usr/bin/pkexec` by its absolute path, and both say
  so when no polkit authentication agent is running, naming the package
  that provides one; any other dismissed or refused prompt stays silent.
- When pkexec finds no polkit authentication agent, the applet and the
  tray say so in one line and name an agent package, instead of every click
  silently doing nothing. Other dismissed or refused prompts stay silent.
- The release builds, checksums, installs and removes both packages.

## [0.2.0] - 2026-09-28

- A device the engine kept off across a reboot now reads "kept off" in the
  list, and a device that is kept but no longer plugged in reads "kept off,
  not attached" with no switch, since there is nothing to park or wake.
- **Forget** on an absent kept device clears its kept flag, dropping it off
  the list.
- One desktop notice per login naming any device that came back kept off.
- Depends on `qml6-module-org-kde-notifications`.

## [0.1.0] - 2026-09-27

- A switch per parkable device, through Hammunition's polkit-gated helper.
- The penguin icon on Hammunition Hill's disc, grey when anything is parked.
- A Debian package, so Hammunition can install the applet.
