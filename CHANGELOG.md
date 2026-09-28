# Changelog

## [Unreleased]

- **`hammunition-tray-qt`**, a second package from the same build: the
  applet's switch as a Qt tray icon for Xfce, LXQt, LXDE, MATE and Cinnamon.
  Same helper, same prompts, same texts; one menu item per parkable device,
  Forget for an unplugged kept one, one kept-off notice per login. Starts at
  login everywhere except Plasma (`NotShowIn=KDE;`), and exits 0 with one
  line on stderr where there is no system tray. Depends on `python3 (>= 3.11)`,
  `python3-pyqt6` and `pkexec | policykit-1`.
- The release builds, checksums, installs and removes both packages. The
  Plasma package is unchanged apart from this README.

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
