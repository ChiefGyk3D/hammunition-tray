# The device helper's contract (version 1)

`hammunition-devctl` is the one program in the Hammunition suite that
changes a device, a service or a radio on a person's behalf. The Plasma
applet, the Qt tray, the engine's CLI and its generated menu entries all go
through it, so there is one privileged path to review rather than four.

This file is the interface. A front end is written against it, and the
helper's tests pin it. **If a shape here changes, `CONTRACT` in
`devctl/hammunition_devctl/__init__.py` and this file change in the same
commit**, and a front end's floor moves with it.

## Where it lives

- Installed path, fixed: `/usr/local/libexec/hammunition-devctl` (a small
  `/bin/sh` wrapper). The polkit action annotates exactly this path, so a
  caller never looks for it anywhere else and never discovers another.
- Polkit action, one: `com.chiefgyk3d.hammunition.devctl`
  (`/usr/share/polkit-1/actions/com.chiefgyk3d.hammunition.devctl.policy`),
  `allow_active` = `auth_self_keep`, `allow_any` and `allow_inactive` =
  `auth_admin`.
- Privileged calls are `/usr/bin/pkexec /usr/local/libexec/hammunition-devctl
  VERB ...`, by absolute path. Unprivileged calls run the wrapper directly.

## Version and floor

```
$ hammunition-devctl --version
hammunition-devctl contract 1
```

One line, the word `contract` and an integer. The integer is the contract
number of this file (`1` here); it rises only when a shape or a verb's
meaning changes incompatibly, and a verb or a field *added* to version 1
does not raise it. A front end records the lowest contract it needs in one
place and compares it with this number.

A helper that predates `--version` (the engine's own copy, before this
repository carried the helper) exits 2 with an argparse error on it. A front
end treats that as contract 0: `state`, `park`, `wake`, `linger`, `time mode`
and `time state` work; `services`, `radio` and `--version` do not. A helper
that has `--version` but lacks a verb a front end asks for answers it with
exit 2 and an argparse "invalid choice" on stderr and nothing on stdout.

## Exit codes (every verb)

| code | meaning |
|---|---|
| 0 | done, and for a change the effect was read back and matches |
| 1 | the change was attempted and failed or could not be verified; the reason is on stderr, lines starting `unverified:` or `error:` |
| 2 | refused before anything happened: unknown or ambiguous name, a name not in an allow-list, wrong scope, the engine not installed, a verb that needs root (`park`, `wake`, `linger`, `time mode`, a system-scope `services` change) run without it; the reason is on stderr, `error: ...` |
| 126, 127 | not the helper: pkexec's own (dismissed or refused prompt, no authentication agent). Front ends already treat both as "nothing was written" |

stdout is empty on exit 1 and 2 except where a verb's section says
otherwise. Reading verbs always print exactly one JSON document and
nothing else on stdout; diagnostics go to stderr as `note: ...` lines and do
not change the exit code.

## Which verbs need pkexec

| verb | pkexec |
|---|---|
| `--version` | no |
| `state`, `state --with-source` | no |
| `time state` | no |
| `services state` | no |
| `services start\|stop\|enable\|disable NAME`, a **user**-scope name | no (`systemctl --user`, as the caller) |
| `services start\|stop\|enable\|disable NAME`, a **system**-scope name | **yes** |
| `radio state` | no |
| `radio on\|off wwan\|wifi\|bluetooth` | no |
| `park NAME[@ADDR] [--until-reboot]`, `wake NAME[@ADDR]` | **yes** |
| `linger on\|off` | **yes** |
| `time mode MODE` | **yes** |

Which scope a service has is in its row from `services state` (`scope`,
and `root` which is `true` exactly for the system scope). A system-scope
verb run without root exits 2; a user-scope verb run as root exits 2: a
user's services are never driven from a root process.

## Unchanged verbs (they were the engine's; their argv and output are
byte-compatible with it)

### `state`

Argv `state`. stdout: one JSON array, always, empty as `[]`. One row per
parkable attached device, then one per kept-off device that is not attached:

```json
[{"name": "gnss-ublox", "summary": "u-blox GNSS receiver", "address": "1-4",
  "identifier": "1546:01a8", "method": "usb_deauthorize",
  "parked": false, "kept": false, "attached": true}]
```

`parked` is `null` for an unattached kept row. `name` matches
`[a-z0-9][a-z0-9-]*`; `address` is a USB bus address (`1-4`, `3-1.2.4`).
Where the device list came from (below) is **not** in this output, which
stays an array; ask for it with:

### `state --with-source` (new)

stdout: one JSON object.

```json
{"kind": "state", "version": 1, "source": "file", "devices": [ ...the rows above... ]}
```

`source` is `"file"` (`/etc/hammunition/devctl-devices.yaml`),
`"engine-import"` (the file is absent and the Hammunition engine's catalog
was read instead) or `"none"` (neither: `devices` is `[]`). When it is not
`"file"` the plain `state` also prints one `note:` line to stderr.

### `park NAME[@ADDR] [--until-reboot]`, `wake NAME[@ADDR]`

Argv exactly as before. `NAME` is the catalog name, `NAME@ADDRESS` when two
of a kind are attached. Nothing but a name crosses the boundary: the helper
re-reads the USB bus and the device list and derives every path itself.
`wake` of a device that is kept off and not attached is a forget (the entry
is removed, nothing is written to sysfs). stdout empty. Exit 0 / 1 / 2 as
above; a refusal (not parkable, ambiguous) is exit 2 with the attached
candidates named.

### `linger on|off`

Acts only on the calling account (`PKEXEC_UID`, never an argument). stdout:
one sentence saying what was done or why nothing was. It records whether
Hammunition turned linger on in `/etc/hammunition/linger.yaml`, and `off`
only undoes linger Hammunition turned on.

### `time mode MODE`, `time state`

`MODE` is one of `auto`, `prefer-gps`, `ntp-only`, `gps-only`. `time state`
prints one JSON object with the 13 keys `mode`, `mode_set`, `daemon`, `gps`,
`following`, `offset_ms`, `last_sync`, `last_source`, `holdover_seconds`,
`rtc`, `grants`, `dhcp_config`, `problems` (the engine's D-058 document).
**These two verbs are the engine's**: the helper delegates to
`hammunition.gpstime` when it can import it and otherwise exits 2 with
`error: the Hammunition engine is not installed ...`. As root it imports the
engine only from a tree no account but its owner can write (the same D-056
rule the helper's own package gets: refused when group- or other-writable,
a `warning:` when one non-root account owns it); a refused import answers
the same exit 2. A front end already
treats exit 2 from `time state` as "update or install Hammunition". Whether
the engine is importable depends on the interpreter the wrapper runs
(`install.sh --interpreter`).

## New verbs

### `services state`

Argv `services state`. No pkexec. stdout, one document:

```json
{"kind": "services", "version": 1,
 "services": [
   {"name": "gps-tether", "unit": "hammunition-gps-tether.service", "scope": "user",
    "description": "GPS position for QMapShack and the browser map on 127.0.0.1",
    "active": "active", "enabled": "enabled", "root": false},
   {"name": "gpsd", "unit": "gpsd.socket", "scope": "system", "description": "the GPS daemon (socket-activated)", "active": "active", "enabled": "enabled", "root": true},
   {"name": "time", "unit": "ntpsec.service", "scope": "system", "description": "the clock", "active": "active", "enabled": "enabled", "root": true},
   {"name": "gps-resume", "unit": "hammunition-gps-resume.service", "scope": "system", "description": "re-adds the receiver to gpsd after sleep", "active": "inactive", "enabled": "not-found", "root": true},
   {"name": "rig", "unit": "hammunition-rigctld.service", "scope": "user", "description": "rigctld for this operator", "active": "inactive", "enabled": "not-found", "root": false}
 ],
 "linger": {"state": "off", "ours": false}}
```

- Every key of a row is always present. `active` is one of `active`,
  `inactive`, `failed`, `activating`, `unknown`; `enabled` is one of
  `enabled`, `disabled`, `static`, `not-found`, `unknown`.
- **A unit that is not installed is listed, with `enabled: "not-found"`
  (and `active: "inactive"`), never omitted.** A front end shows it as "not
  installed".
- `static` stands for any unit with no `[Install]` of its own (systemd's
  `static`, `indirect`, `generated`, `transient`, `alias`); a runtime
  enable counts as `enabled`.
- `masked`, `masked-runtime`, `linked`, `linked-runtime` and `bad` unit-file
  states fold to `enabled: "unknown"`. `enable` is verified only by
  `enabled`; `disable` is verified by any other state, so `unknown` after
  `disable` counts as disabled.
- Rows are the system file's, in file order, then the user file's. The order
  carries no meaning; a front end sorts to taste. A name is unique across
  both files: a user row whose name a system row already has is dropped (and
  noted on stderr).
- `linger.state` is `on`, `off` or `unknown` (logind could not be asked, for
  one: the account is not logged in under logind); `ours` is `true` when
  `/etc/hammunition/linger.yaml` says Hammunition turned it on for this uid.
- Under root the user file is not read: only system rows are listed.

### `services start|stop|enable|disable NAME`

Argv `services VERB NAME`, `VERB` one of `start`, `stop`, `enable`,
`disable`. `NAME` is a row's `name`. For a user-scope name the helper runs
`/usr/bin/systemctl --user VERB UNIT` as the caller; for a system-scope name
it runs `/usr/bin/systemctl VERB UNIT` and must be running as root (through
pkexec). `systemctl` and `loginctl` are always started by absolute path:
nothing found through a `PATH` is run with root's authority.

- `NAME` that is in neither allow-list file: exit 2, `error: 'NAME' is not a
  service Hammunition controls`.
- The name is in a file but the unit is not installed (`LoadState` is
  `not-found`): exit 2, `error: ... is not installed`.
- The verb's effect is read back (`start`: `active` or `activating`; `stop`:
  neither `active` nor `activating` afterwards; `enable`: `enabled`;
  `disable`: not `enabled`). An `activating` unit, for example during an
  automatic restart, counts as not stopped. A mismatch or a failing
  `systemctl` is exit 1, `unverified:` or `error:` on stderr.
- stdout is empty on success.
- Nothing in the argv is ever a unit name or a command: the unit comes
  from the allow-list row, and the verb is one of four words.

### `radio state`

Argv `radio state`. No pkexec. stdout, one document:

```json
{"kind": "radios", "version": 1,
 "radios": [
   {"name": "wwan", "present": true, "enabled": true, "method": "nmcli", "detail": "cdc-wdm0"},
   {"name": "wifi", "present": true, "enabled": true, "method": "nmcli", "detail": "wlan0"},
   {"name": "bluetooth", "present": true, "enabled": true, "method": "bluetoothctl", "detail": ""}
 ]}
```

Always three rows, in that order. `present` is false, and `enabled` false,
when the tool that answers is not installed (`detail` is then `nmcli is not
installed` or `bluetoothctl is not installed`), when it fails
(`detail` says so), or when it reports no such radio (`wwan` and `wifi`: no
NetworkManager device of that type). `detail` is free text for a person: the
device names for `nmcli`, `blocked by rfkill` for a bluetooth controller
that is blocked, otherwise `""`. No address, serial or hostname is ever put
in it.

### `radio on|off wwan|wifi|bluetooth`

Argv `radio on|off NAME`. No pkexec; run as root it exits 2 (a radio switch
is the calling user's session, and polkit already lets an active local
session do it). Fixed argv per radio, nothing else is ever run:

| radio | command |
|---|---|
| `wwan` | `nmcli radio wwan on\|off` |
| `wifi` | `nmcli radio wifi on\|off` |
| `bluetooth` | `bluetoothctl power on\|off` |

rfkill is never written. The result is read back with the same reads as
`radio state`; a mismatch is exit 1 `unverified:`. A radio whose tool is
absent is exit 2. stdout is empty on success.

## The three data files

The helper never takes an allow-list, a unit name, a device or a path as an
argument. It reads these, and a name that is not in them is refused by
name. All three are YAML; each carries `version: 1`. A file that is absent
is not an error (an empty list, and `state --with-source` says where the
devices came from); a file that cannot be parsed is reported on stderr as a
`note:` and treated as empty, never half-read.

**Root-read files must be trusted.** When the helper runs as root it reads
the two `/etc/hammunition/` files (and `/etc/hammunition/linger.yaml`) only
after checking, on the open file, that each is a regular file owned by root
and not writable by group or other, in a directory that is the same; a
symlink is never followed. One that fails is refused with a `note:` and
treated as empty. The user file is never read by a root process.

### `/etc/hammunition/devctl-services.yaml` (system scope)

Written by the Hammunition engine's `hardware apply`; 0644 root.

```yaml
version: 1
services:
  - name: gpsd
    unit: gpsd.socket
    scope: system
    description: the GPS daemon (socket-activated)
```

### `~/.config/hammunition/devctl-services.yaml` (user scope)

(`$XDG_CONFIG_HOME/hammunition/` when set.) Written by the engine when it
installs a catalog unit that has a `user_services` block; 0600, the
caller's.

```yaml
version: 1
services:
  - name: gps-tether
    unit: hammunition-gps-tether.service
    scope: user
    description: GPS position for QMapShack and the browser map on 127.0.0.1
```

Row rules, checked on read; a row that breaks one is dropped with a
`note:` naming it and the rest are kept:

- `name` matches `[a-z0-9][a-z0-9-]{0,63}`.
- `unit` matches `[A-Za-z0-9][A-Za-z0-9:_.@-]{0,127}\.(service|socket|timer|path)`:
  it cannot begin with `-`, so it can never be read as an option.
- `scope` is `system` or `user`, and agrees with the file it is in.
- `description` is a string of at most 200 characters, free of control
  characters.

### `/etc/hammunition/devctl-devices.yaml` (parkable devices)

Written by the engine's `hardware apply` from every catalogued device or
class that has a `power_control` block; 0644 root.

```yaml
version: 1
devices:
  - name: gps-receiver
    summary: u-blox GNSS receiver
    method: usb_deauthorize
    quiet: []
    usb_ids:
      - {vendor: "1546", product: "01a8"}
      - {vendor: "0403", product: "6001", product_string: "FT232R USB UART"}
```

- `method` is `usb_deauthorize` or `pci_runtime`; the latter, and any
  non-empty `quiet`, are accepted into the file and **refused when a verb
  would act on the device** (D-056), exactly as the engine does.
- `usb_ids` lists only confirmed identifiers, four lowercase hex digits each.
  `product_string` is present only for an identifier the catalog records as
  shared between products; a device the bus reports with a different
  product string than that is not a match, and when the bus reports none the
  identifier alone matches. An entry with `vendor` alone (`product` absent)
  matches any product of that vendor.
- A device matched by two entries is listed once per entry, as the engine
  always did; `NAME@ADDRESS` is how two of a kind are told apart.

When this file is absent the helper falls back to importing the engine
(`hammunition.cli.main.find_catalog`, `hammunition.manifest.load`) and
building the same list from the catalog, reports `source: "engine-import"`,
and finds nothing (`source: "none"`) when the engine is not importable
either.

## What the helper will never do

- Run a command whose words come from input. Every verb has fixed argv; the
  only variable parts are a unit name taken from an allow-list row, a
  username taken from the account database, and a sysfs path built from a
  bus address the helper read itself.
- Write anywhere but the two sysfs files `authorized` and `power/control`
  directly under a USB or PCI device node, the kept-off udev rules file
  `/etc/udev/rules.d/66-hammunition-kept.rules`, `/etc/hammunition/linger.yaml`,
  and (by delegating to the engine) the GPS time files.
- Read a station value. Parking a GPS has nothing to do with a callsign.
