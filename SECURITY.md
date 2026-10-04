# Security Policy

## Supported versions

The latest tagged release is supported (currently v0.5.0). Fixes land on
`main` and ship in the next tag; older tags are not patched.

## Reporting a vulnerability

Please report security issues **privately**, not in a public issue or pull
request. Use GitHub's private vulnerability reporting on this repository:
[Report a vulnerability](https://github.com/ChiefGyk3D/hammunition-tray/security/advisories/new).

Please include the affected verb, file or applet, what you expected and what
happened, and the steps to reproduce it. Do not include a callsign, grid
square, hostname or any other station detail you want kept private.

## What is in scope

- The root helper, `hammunition-devctl` (`devctl/hammunition_devctl/`): its
  verbs, the files it writes under `/etc` and `/etc/udev/rules.d`, the polkit
  action it runs behind, and the checks that decide which files and trees it
  will trust or import as root.
- The Plasma applet and the Qt tray as front ends: any way they can make the
  helper do something its caller could not ask for directly, or run a command
  built from data they read.
- The Debian packages and installers built from this repository
  (`packaging/`, `install.sh`, `uninstall.sh`) and their release workflow.

Vulnerabilities in the software the suite drives (systemd, NetworkManager,
Plasma, the Hammunition engine itself) belong with those projects; tell us if
the helper should change because of one.

## What to expect

hammunition-tray has a sole maintainer. Expect an acknowledgement within a week
and a fix or a written assessment as soon as practical after that. There is no
bug bounty. Reporters are credited in the changelog entry for the fix unless
they ask not to be.
