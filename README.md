# Hammunition Devices

A Plasma 6 system-tray applet for parking and waking the radio devices
[Hammunition](https://github.com/ChiefGyk3D/Hammunition) has catalogued.

Parking a device writes `0` to its sysfs `authorized`, so the kernel drops
its interfaces and the USB port can suspend; waking writes `1`. On a laptop
that is the difference between a GNSS receiver drawing power all day and
drawing none, without unplugging anything.

**Parked state is not saved. A reboot wakes everything.** There is no state
file to go stale and nothing to reconcile at boot.

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
sudo apt install ./hammunition-tray_0.1.0_all.deb
```

It depends on Plasma 6 and the two QML modules the applet imports, one of
which (`qml6-module-org-kde-plasma-plasma5support`) ships separately from
Plasma; apt pulls them in.

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
- **The tray icon changes** when anything is parked.
- **A dismissed password prompt leaves the switch where it was.** Nothing was
  written, so nothing moves — the switch shows the device's real state, not
  what you asked for.

## Status

Early (0.1.0). The engine half is Hammunition's **D-056**. Park and wake
were run from this applet against a u-blox GPS receiver on a Dell Latitude
5430 Rugged running Parrot 7.3 on 2026-09-27: gpsd let go of the receiver
within a second of parking and took it back within a second of waking, and
the fix returned by 74 s (Hammunition's bench record, session 10). No other
device has been parked yet, and parked state does not yet survive a reboot.

## Licence

GPL-3.0-or-later. Copyright (C) 2026 ChiefGyk3D.
