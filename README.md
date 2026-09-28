# Hammunition Devices

A Plasma 6 system-tray applet for parking and waking the radio devices
[Hammunition](https://github.com/ChiefGyk3D/Hammunition) has catalogued,
and the same switch as a tray icon for Xfce, LXQt, LXDE, MATE and Cinnamon
([below](#xfce-lxqt-lxde-mate-cinnamon-the-qt-tray)).

Parking a device writes `0` to its sysfs `authorized`, so the kernel drops
its interfaces and the USB port can suspend; waking writes `1`. On a laptop
that is the difference between a GNSS receiver drawing power all day and
drawing none, without unplugging anything.

**A parked device can now be kept off across a reboot**, by Hammunition's
engine rather than this applet: the switch calls the same helper either way,
and a device the engine is keeping off shows "kept off" here. That
reboot-persistence has not yet been measured on real hardware by this
applet — see Status below.

## What this is, and what it is not

This applet is a **client** of Hammunition's engine, not part of it. It runs
one command to read state and one to change it, and it is packaged
separately so it can be installed — or not — independently of the engine,
and so somebody who does not use Hammunition can still be pointed at it.

It never touches sysfs and it never runs as root. Reading which devices are
parked needs no privilege, so the poll asks for no password. Parking or
waking one does, and goes through polkit exactly once per action.

## Requirements

- Plasma 6.
- Hammunition installed, with `hammunition hardware apply` already run. That
  is what installs `/usr/local/libexec/hammunition-devctl` and the polkit
  action authorising it. Until then the applet says so rather than showing
  switches that cannot work.
- At least one catalogued device marked parkable and plugged in. Today that
  is USB GNSS receivers; a WWAN modem class is expected to follow.

## Install

Any of the three; each needs `hammunition hardware apply` to have been run,
which installs the helper the switches call.

**Through Hammunition** (once its catalog carries the applet):

```sh
hammunition install hammunition-tray
```

**The Debian package**, from the [releases page](https://github.com/ChiefGyk3D/hammunition-tray/releases),
for every account on the machine. Check it against the release's
`SHA256SUMS` first:

```sh
sha256sum -c SHA256SUMS --ignore-missing
sudo apt install ./hammunition-tray_0.2.0_all.deb
```

It depends on Plasma 6 and the QML modules the applet imports, including two
that ship separately from Plasma (`qml6-module-org-kde-plasma-plasma5support`
and `qml6-module-org-kde-notifications`); apt pulls them in.

**A per-user copy**, from a checkout:

```sh
./install.sh
```

Runs as **you**, not as root: `kpackagetool6` installs into
`~/.local/share/plasma/plasmoids`. `./uninstall.sh` removes it. A per-user
copy **shadows** the package, so if you move to the `.deb`, run
`./uninstall.sh` once.

After any install or upgrade, Plasma keeps the old version loaded until you
run `systemctl --user restart plasma-plasmashell` or log in again. Then add
*Hammunition Devices* to your panel or system tray.

Removing the applet never removes the helper or the polkit action; they
belong to the engine, and `hammunition hardware unapply` removes those.

## What you will see

- **A switch per parkable attached device**, labelled with the catalog's own
  summary and its bus address. The address is shown because two receivers of
  one class share a catalog name and differ only by address.
- **"Kept off"** on a device's second line when the engine is keeping it off
  across reboots; **"kept off, not attached"** and no switch when that same
  device is unplugged, since there is nothing left to park or wake.
- **A Forget button** in place of the switch for an unplugged kept device.
  It clears the kept flag and drops the device off the list — for a device
  you are not going to plug back in.
- **One desktop notice, at most once per login**, naming any device that came
  back kept off.
- **The tray icon changes** when anything is parked.
- **A dismissed password prompt leaves the switch where it was.** Nothing was
  written, so nothing moves — the switch shows the device's real state, not
  what you asked for.

## Xfce, LXQt, LXDE, MATE, Cinnamon: the Qt tray

The Plasma applet only runs in Plasma. Every other desktop with a system
tray gets **`hammunition-tray-qt`**, a second package from the same release
and version: a tray icon whose menu does exactly what the applet does. It
is a second client of the same helper, so nothing about privilege differs —
the poll asks for no password, and each park or wake is one polkit prompt
for `pkexec /usr/local/libexec/hammunition-devctl park|wake NAME@ADDRESS`.

```sh
sha256sum -c SHA256SUMS --ignore-missing
sudo apt install ./hammunition-tray-qt_*_all.deb
```

It depends on `python3 (>= 3.11)`, `python3-pyqt6` and `pkexec` (or the
older `policykit-1`); apt pulls them in. Measured with `apt-cache policy`
on 2026-09-28: Debian 13 (as Parrot 7) offers `python3-pyqt6` 6.9.0 and
`pkexec` 126, and has no `policykit-1` at all; Ubuntu 24.04 offers
`python3-pyqt6` 6.6.1 and both names. As with the applet,
`hammunition hardware apply` must have been run first.

**It starts at login on every desktop except Plasma**, from
`/etc/xdg/autostart/hammunition-tray-qt.desktop`, which carries
`NotShowIn=KDE;` so a machine with both Plasma and Xfce never shows two
trays in Plasma. To start it by hand, *Hammunition Devices* is in the
application menu, or run `hammunition-tray-qt`. At login it waits up to a
minute for the panel to appear; a second copy in the same session exits.

**What you will see:** the icon's menu (right click; left click is meant
to open it too, but that has not yet been tried on a real panel). Each
parkable attached device is a checkable item, *summary (address) — awake*,
*parked* or *kept off*; clicking it parks or wakes. *Kept off* is shown
whenever the engine is keeping the device off, even if something has woken
it since; the checkmark always shows whether it is awake now, as the
applet's switch does. An unplugged kept device shows *Forget*, which clears
its kept flag. The rest is the applet's: the icon goes grey when anything
is parked, the tooltip says how many, one *Kept off* notification at most
per login, a dismissed or refused password prompt changes nothing and says
nothing, and a missing helper is a sentence naming the command that
installs it.

**Two rules the tray brought, which the applet now follows too:**

- **No polkit agent is said, not swallowed.** A dismissed or refused
  password prompt stays silent, since nothing was written. But when pkexec
  reports *No authentication agent found*, every click would otherwise do
  nothing and say nothing, so both say so in one line and name an agent
  package. Plasma normally runs its own agent (`polkit-kde-agent-1`); a
  minimal Xfce or LXQt session may run none. The tray names the desktop's
  usual one: `lxqt-policykit` on LXQt, `policykit-1-gnome` (Ubuntu) or
  `mate-polkit` on Xfce, `lxpolkit` on LXDE, `mate-polkit` on MATE. Those
  are the ones `apt-cache policy` found on Debian 13 or Ubuntu 24.04 on
  2026-09-28; `xfce-polkit` is in neither. Install one and log in again.
  It grants nothing — it only says why nothing happened — and neither
  package pulls an agent in.
- **An action's error stays until the next action.** Every park or wake is
  followed at once by a re-read of the device state. Both used to share
  one error line, which that re-read cleared, so a failed park or wake
  showed its error for a moment at most. The two are kept apart now.
- **pkexec by its absolute path.** Both run `/usr/bin/pkexec`, never one
  looked up through `PATH`.

**GNOME has no system tray** unless the AppIndicator extension is enabled
(`gnome-shell-extension-appindicator` on Debian and Ubuntu). Without it the
tray prints one line to stderr and exits 0 — it never crash-loops. With it,
the icon appears in the top bar like any other.

**To stop it starting at login** for one account only, copy the autostart
file to `~/.config/autostart/` and add `Hidden=true` to the copy. `apt
remove` leaves the system autostart file in place (it is a conffile) but
it no longer starts anything, because the program it names has gone;
`apt purge` removes it.

**Measured so far:** the tray has run in a Plasma 6 Wayland session
against the real helper without an error, and headless — no tray, one line,
exit 0 — installed from the package in a Parrot container. It has not yet
been run in an Xfce, LXQt, LXDE, MATE or Cinnamon session; those panels
are expected to host it through StatusNotifierItem or XEmbed, which Qt
chooses between, but that is an expectation, not a measurement.

## Status

0.2.0. The engine half is Hammunition's **D-056**. Park and wake were run
from this applet against a u-blox GPS receiver on a Dell Latitude 5430
Rugged running Parrot 7.3 on 2026-09-27: gpsd let go of the receiver within
a second of parking and took it back within a second of waking, and the fix
returned by 74 s (Hammunition's bench record, session 10). No other device
has been parked yet. The engine can now keep a device off across a reboot,
but this applet has not yet had that measured against real hardware across
an actual reboot — the "kept off" label and the Forget action are built and
tested against the helper's JSON shape, not against a machine that has been
rebooted with a device kept off.

## Licence

GPL-3.0-or-later. Copyright (C) 2026 ChiefGyk3D.
