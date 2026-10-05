<p align="center">
  <img src="https://raw.githubusercontent.com/Renegade-Penguin/Hammunition/main/docs/images/logo.png"
       alt="Hammunition" width="300">
</p>

# Hammunition Devices

A Plasma 6 system-tray applet for parking and waking the radio devices
[Hammunition](https://github.com/Renegade-Penguin/Hammunition) has catalogued,
and the same switch as a tray icon for Xfce, LXQt, LXDE, MATE and Cinnamon
([below](#xfce-lxqt-lxde-mate-cinnamon-the-qt-tray)).

Parking a device writes `0` to its sysfs `authorized`, so the kernel drops
its interfaces and the USB port can suspend; waking writes `1`. On a laptop
that is the difference between a GNSS receiver drawing power all day and
drawing none, without unplugging anything.

**A Controls panel** also switches the GPS services and the machine's radios,
beside the device switches: [below](#the-controls-panel).

**A Time section** shows what the clock follows and sets the mode of
Hammunition's GPS time (its D-058) — [below](#the-time-section).

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
- The device helper, `/usr/local/libexec/hammunition-devctl`, and the polkit
  action authorising it ([below](#the-device-helper-hammunition-devctl)).
  This repository installs both; Hammunition's `hardware apply` installs
  its own copy of them too. Until one is there the applet says so rather
  than showing switches that cannot work.
- At least one catalogued device marked parkable and plugged in. Today that
  is USB GNSS receivers; a WWAN modem class is expected to follow.
- **For the Time section, Hammunition 0.18.0 or later.** An older engine's
  helper does not know `time state`; the switches still work, and the
  section says "Update Hammunition to 0.18.0 or later…" once instead of
  failing on every poll.

## Install

Any of the three. Each needs the device helper, which this repository's
installers place too (the `.deb` as its own package, `hammunition-devctl`).

**Through Hammunition** (both tray units are in its catalog at 0.5.0):

```sh
hammunition install hammunition-tray
```

**The Debian package**, from the [releases page](https://github.com/Renegade-Penguin/hammunition-tray/releases),
for every account on the machine. Check it against the release's
`SHA256SUMS` first:

```sh
sha256sum -c SHA256SUMS --ignore-missing
sudo apt install ./hammunition-tray_0.5.0_all.deb
```

It depends on Plasma 6 and the QML modules the applet imports, including two
that ship separately from Plasma (`qml6-module-org-kde-plasma-plasma5support`
and `qml6-module-org-kde-notifications`); apt pulls them in.

**A per-user copy**, from a checkout:

```sh
./install.sh
```

Runs as **you**, not as root: `kpackagetool6` installs into
`~/.local/share/plasma/plasmoids`, and the helper step lists the root-owned
files it needs and asks for `sudo` once, after you confirm (`--no-helper`
skips it, `--yes` answers the question). `./uninstall.sh` removes the
applet; `./uninstall.sh --helper` also removes the helper this repository
installed. A per-user copy **shadows** the package, so if you move to the
`.deb`, run `./uninstall.sh` once.

After any install or upgrade, Plasma keeps the old version loaded until you
run `systemctl --user restart plasma-plasmashell` or log in again. Then add
*Hammunition Devices* to your panel or system tray.

Removing the applet does not remove the helper unless you say `--helper`.
When `hammunition hardware unapply` finds a helper that answers
`hammunition-devctl contract 1`, it leaves the helper and its polkit action
alone, reports that the helper is now `hammunition-tray`'s, and leaves their
removal to this repository's uninstall.

## The device helper, `hammunition-devctl`

This repository is the device project of the Hammunition suite, so the
program that actually changes a device lives here: the one root helper that
the applet, the Qt tray, Hammunition's CLI and its generated menu entries
all call. It used to be part of the engine (its D-056); it moved here with
its tests. Everything it accepts and prints is in
**[`docs/contract.md`](docs/contract.md)**, which is the interface and is
versioned (`hammunition-devctl --version` prints `hammunition-devctl contract 1`).

What it does:

- `park`/`wake` a catalogued USB device, `linger on|off`, `time mode|state`
  (the engine's GPS time): the engine's verbs, argv and JSON unchanged.
- `services state` and `services start|stop|enable|disable NAME`: the
  services Hammunition manages (the GPS tether, gpsd, the clock, the rig).
  A user service is `systemctl --user` as you; a system one needs pkexec and
  the same polkit action.
- `radio state` and `radio on|off wwan|wifi|bluetooth`: your own session's
  switches, through `nmcli` and `bluetoothctl`, no root.

What it never does: run a command whose words come from its arguments. Every
verb has a fixed argv; a service is found by name in an allow-list file the
helper reads (`/etc/hammunition/devctl-services.yaml`, and
`~/.config/hammunition/devctl-services.yaml` for user services, never read
by a root process); a device by name in `/etc/hammunition/devctl-devices.yaml`.
The Hammunition engine writes those files; until it writes the devices file
the helper falls back to importing the engine's catalog and says so
(`state --with-source`).

**Layout: a sibling package, `devctl/hammunition_devctl`, not a submodule of
`hammunition_tray_qt`.** The helper is the one thing here that runs as
root, so it must not share an import path, a test target or a dependency
with PyQt6, and it must install without a desktop (a headless station has
no use for a tray and every use for `services` and `radio`). The Plasma
applet is not Python at all and calls the same helper. The package has its
own `devctl/pyproject.toml`, so `pip install ./devctl` gives the console
script `hammunition-devctl`; the system install uses a copy under
`/usr/local/lib` (checkout install) or `/usr/share` (the `.deb`) behind the
wrapper polkit authorises, because root must never run code from a tree
somebody else can write.

**Install**, any one of:

```sh
sudo apt install ./hammunition-devctl_*_all.deb     # its postinst writes the wrapper
./install.sh --helper-only                          # from a checkout; asks for sudo once
hammunition install hammunition-tray                # the engine's catalog unit
```

The wrapper runs `/usr/bin/python3` by default. The `time` verbs belong to
the engine (`hammunition.gpstime`), so they answer "the Hammunition engine is
not installed" unless the wrapper's interpreter can import it: install with
`./install.sh --helper-only --interpreter /path/to/engine/venv/bin/python`
(the engine's installer does this) and they work.

**How the engine calls it**: by path, `/usr/local/libexec/hammunition-devctl`,
as the tray does: `state`, `services state` and `radio state` directly; `park`,
`wake`, `linger`, `time mode` and system-scope `services` verbs through
`/usr/bin/pkexec`. It never imports this package, and never runs
`systemctl` itself.

Tests: `python -m pytest tests` (the helper's tests need PyYAML and pytest);
CI also runs them on Python 3.11 and 3.13 from a real `pip install ./devctl`
with `mypy --strict`. No test starts a real `systemctl`, `nmcli` or
`bluetoothctl`: a fake runner keyed by argv answers, and any command nobody
faked fails the test.

**Not yet measured:** the new verbs have been exercised against fakes only.
`services` and `radio` have not been run against a real `systemctl`,
NetworkManager or BlueZ, and a WWAN modem that ModemManager has disabled may
or may not still be listed by `nmcli device status`, which is what `present`
reads for it.

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

## The Controls panel

One panel, three groups, worded identically in the Plasma applet and in the
Qt tray (a test holds them to it). The Plasma applet scrolls when the panel
is taller than the popup; the Qt tray's menu has a section heading per group.

- **Devices**: exactly what is described above. Nothing about it changed.
- **Services**: one row per service the helper controls, from
  `hammunition-devctl services state`: a **switch** for *running* and a
  **"Start at login"** checkbox. The rows come from the helper's allow-lists
  (`/etc/hammunition/devctl-services.yaml`, written by
  `hammunition hardware apply`, for system services;
  `~/.config/hammunition/devctl-services.yaml`, updated when a catalog unit
  with a `user_services` block is installed, for your own), and the same list
  is available as `hammunition services`: the GPS daemon, the clock,
  `gps-resume`, the GPS tether and `rigctld`. A service whose unit is not
  installed is still listed, says *not installed*, and cannot be switched.
  *Start at login* is
  disabled for a unit that has nothing to enable (`static`).
- **Radios**: one switch each for mobile broadband (WWAN), Wi-Fi and
  Bluetooth, from `hammunition-devctl radio state`. A radio whose tool the
  helper could not use (NetworkManager's `nmcli`, `bluetoothctl`) shows the
  helper's reason and is disabled.

**Which switch asks for a password.** Reading is never privileged: every
tick (5 s by default) runs `state`, `time state`, `services state` and
`radio state` directly, with no prompt. Changing:

| switch | runs | prompt |
|---|---|---|
| a device (park, wake, forget) | `/usr/bin/pkexec HELPER park\|wake NAME@ADDRESS` | one |
| a clock mode | `/usr/bin/pkexec HELPER time mode MODE` | one |
| a **system** service (running or login) | `/usr/bin/pkexec HELPER services start\|stop\|enable\|disable NAME` | one, the same polkit action |
| a **user** service (running or login) | `HELPER services start\|stop\|enable\|disable NAME` | none: `systemctl --user` as you |
| a radio | `HELPER radio on\|off wwan\|wifi\|bluetooth` | none: polkit already lets an active session do it |

`HELPER` is `/usr/local/libexec/hammunition-devctl`. A service's scope comes
from its row, and a name must have the shape the helper accepts
(`[a-z0-9][a-z0-9-]{0,63}`) or it never reaches a command; the Plasma applet
builds a shell string, so that check is the one that matters there. Only the
four verbs, and only the three radios, can be sent.

**What a switch does when you use it.** It moves at once, to what you asked
for. The next poll replaces that with what the helper really reports, so a
verb that "worked" but left the service somewhere else shows where it is. If
the verb fails, the switch goes back and the helper's one line is shown
(`error: ...` or `unverified: ...`); a dismissed or refused password prompt
goes back silently, since nothing was written. While a verb runs, every
switch is disabled.
A poll that was already running when you used a switch is a picture from
before it, so it never takes your request off the screen; the poll that
confirms is the next one that starts after the verb has finished, which the
tray asks for at once rather than at the next tick.

**A helper without these verbs.** The group says one line, *update
hammunition-tray*, instead of an error; the poll keeps asking, so updating
brings it in without logging out. That is the helper answering exit 2 with
argparse's "invalid choice", and nothing else: the helper's own refusals,
also exit 2, are shown as errors.

**The helper contract.** The helper's interface is `docs/contract.md` in its
repository; this tray speaks **contract version 1**. The floor is one
number, `CONTRACT_FLOOR` in `qt/hammunition_tray_qt/controls.py` and
`controlslogic.js`, compared with the `version` of each document the helper
prints; a document that says less, or nothing, is *update hammunition-tray*.
A document that says more is read as far as this tray understands it. A
state or a radio this tray does not know is shown and never offered a
switch.

## The Time section

Below the switches, both front ends show Hammunition's GPS time (engine
**D-058**, Hammunition 0.18.0 or later; the engine's own guide is its
`docs/guides/gps-time.md`):

- **What the clock follows now**: the GPS or the network, with the offset
  ntpd reports, or *Holdover since HH:MM UTC* and for how long when nothing
  is setting it.
- **The four modes**, the current one checked: *Automatic (the default)*,
  *Prefer the GPS*, *Network only*, *GPS only*. Choosing one runs
  `/usr/bin/pkexec /usr/local/libexec/hammunition-devctl time mode MODE`:
  one polkit prompt, the same action as park and wake. Only those four
  names can reach the helper. A dismissed prompt leaves the old mode
  checked. Exit 1 (written, but not verified) and exit 2 (refused) show the
  helper's own reason.
- **Greyed, with the reason**, when the GPS cannot feed the clock: ntpsec is
  not the time daemon (Debian, Ubuntu and Kali default to
  systemd-timesyncd, and an `apt remove`d ntpsec counts as none), where
  the modes are disabled because the engine would refuse them; or the
  receiver is parked while the mode would use it, where the modes stay
  usable, to switch to *Network only* say.
- **Notes**, small, under the sentence: the receiver is parked; *GPS only*
  with no receiver attached; ntpd cannot read the GPS's time yet (pointing
  at `hammunition time`, deliberately not at `hardware apply`, which
  declines the grants on a machine without gpsd); ntpd started on a
  DHCP-supplied configuration; anything the engine itself lists as a
  problem.
- **No hardware clock** is a line in the tooltip.

Reading it is `hammunition-devctl time state` with no pkexec, polled with
the devices (and, since 0.5.0, the services and radios). The Qt tray shows the same as a *Time* section in its menu,
with the modes as checkable items; a menu has no opacity, so there the
reason is the note.

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
`python3-pyqt6` 6.6.1 and both names. The catalog units install the helper;
`hammunition hardware apply` writes the device and system-service lists it
reads.

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

## CI and release

CI, the security scans and the release are the reusable workflows of
[git-your-ship-together](https://github.com/ChiefGyk3D/git-your-ship-together)
(GYST), pinned by commit at v1.6.3. `.github/workflows/ci.yml` calls its
Python CI (ruff, `mypy --strict` over the helper on 3.11 and 3.13 typeshed, and
every test on Python 3.11 and 3.13) and its shell CI (shellcheck over every
tracked script); `security.yml` calls its gitleaks, CodeQL and Scorecard jobs
(no secrets, so no Doppler); `release.yml` calls its artifact release, which
builds the three `.deb` files, checks each on Parrot, and on a `v*` tag
writes `SHA256SUMS`, signs every file with cosign, records build provenance
and creates the GitHub release.

One job stays here: `qt`, the Qt tray against the archive's own PyQt6 and the
system python3. GYST runs distro tests in a fresh virtual environment, which
cannot see the archive's PyQt6.

### Fuzzing

The helper runs as root, so what it parses is fuzzed. `fuzz/fuzz_*.py` are
[Atheris](https://github.com/google/atheris) targets: the two allow-list
readers (`devctl-devices.yaml`, `devctl-services.yaml`), the lexical sysfs
path guard (an accepted path must still sit under an allowed root once
normalised), the kept-off udev rules reader, and the linger record with the
polkit wrapper script. The `fuzz` job of `ci.yml` calls GYST's `python-fuzz.yml`
(30 seconds per target on a pull request, 10 minutes on the Monday schedule).
Run one yourself in a CPython 3.12 to 3.14 environment on x86_64:

```sh
pip install ./devctl atheris==3.1.0
python fuzz/fuzz_sysfs_guard.py -max_total_time=60 -max_len=4096
```

A crash prints the exception and writes a `crash-<sha>` file (in CI it is
the `fuzz-findings` artifact). Do not just patch around it: turn the bytes in
that file into an ordinary pytest test, watch it fail, fix the helper at the
root cause, and keep the test. `tests/test_fuzz_targets.py` feeds every target
a few seeds on each normal test run so a target cannot rot unnoticed. The
`fuzz` job is not one of the required checks below; a crash on `main` shows
up there.

Required checks for `main`:

- `ci / CI green` (Python: lint, type check, tests on 3.11 and 3.13)
- `shell / CI green` (shellcheck)
- `Qt tray (system python3, archive PyQt6)`

The security and release workflows are not merge gates. The release builds and
verifies on a pull request that touches the packaging and never publishes
there; the Parrot mirror's availability is not a merge gate.

## Status

0.5.0. **The Controls panel and the helper's move here** is tested against fake helper
documents for every state of a service and a radio, with the applet's
`controlslogic.js` and the tray's `controls.py` required to agree word for
word, and the Qt tray's menu is driven end to end by a fake runner. Neither
front end has been opened on a real panel, and no service or radio has been
switched from either against the real helper: the Plasma panel in
particular (its new scroll view and the check boxes) has been parsed, not
rendered. The helper's `services` and `radio` verbs are from the helper
repository's contract, version 1, and are not yet installed on any machine
this was run on.

0.4.0. **The Time section** is tested against fake helper outputs for every
state the engine's `time state` can report, with the applet's
`timelogic.js` and the tray's `timelogic.py` required to agree word for
word. On 2026-10-01 the real helper's `time state` on the Latitude 5430
was read (no prompt, no change) and both modules read it the same way. No
mode has been changed from either front end yet, and neither has been
opened with the section on a real panel.

The switches: The engine half is Hammunition's **D-056**. Park and wake were run
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
