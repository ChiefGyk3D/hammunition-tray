# Changelog

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
