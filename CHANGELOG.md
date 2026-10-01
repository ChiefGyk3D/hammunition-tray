# Changelog

## [Unreleased]

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
