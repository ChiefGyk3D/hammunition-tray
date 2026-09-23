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

```sh
./install.sh
```

Runs as **you**, not as root: `kpackagetool6` installs into
`~/.local/share/plasma/plasmoids`, and the applet needs no privilege of its
own. Then add *Hammunition Devices* to your panel or system tray.

```sh
./uninstall.sh
```

removes the applet only. The helper and the polkit action belong to the
engine — `hammunition hardware unapply` is what removes those.

## What you will see

- **A switch per parkable attached device**, labelled with the catalog's own
  summary and its bus address. The address is shown because two receivers of
  one class share a catalog name and differ only by address.
- **The tray icon changes** when anything is parked.
- **A dismissed password prompt leaves the switch where it was.** Nothing was
  written, so nothing moves — the switch shows the device's real state, not
  what you asked for.

## Status

Early. The engine half landed in Hammunition as **D-056**; this applet is
plan 2 of that design. **No park or wake has yet been run against real
hardware** — not by this applet and not by the CLI it drives. Treat the
behaviour described above as what the design intends, verified by tests and
by reading the engine's own output, and not yet as something measured on a
bench.

## Licence

GPL-3.0-or-later. Copyright (C) 2026 ChiefGyk3D.
