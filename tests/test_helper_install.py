"""install.sh and uninstall.sh place and remove the helper's files.

Run against a scratch root (HAMMUNITION_DEVCTL_ROOT) with sudo replaced by
nothing, so no test touches /usr/local or asks for a password. What is
checked is the effect -- the files, their modes, what the installed copy
prints -- not the scripts' exit status.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = "usr/local/lib/hammunition-devctl"
WRAPPER = "usr/local/libexec/hammunition-devctl"
POLICY = "usr/share/polkit-1/actions/com.chiefgyk3d.hammunition.devctl.policy"
MARK = "# Installed by hammunition-tray (hammunition-devctl, D-056)."


def _script(name: str, root: Path, *args: str, stdin: int | None = subprocess.DEVNULL):
    env = {
        **os.environ,
        "HAMMUNITION_DEVCTL_ROOT": str(root),
        "HAMMUNITION_DEVCTL_SUDO": "",
    }
    return subprocess.run(
        [str(ROOT / name), *args],
        env=env,
        stdin=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "root"


def test_install_places_the_files_with_their_modes(root: Path) -> None:
    done = _script("install.sh", root, "--helper-only", "--yes")
    assert done.returncode == 0, done.stderr
    assert _mode(root / WRAPPER) == 0o755
    assert _mode(root / LIB / "hammunition-devctl") == 0o755
    assert _mode(root / POLICY) == 0o644
    package = sorted(p.name for p in (root / LIB / "hammunition_devctl").iterdir())
    source = sorted(p.name for p in (ROOT / "devctl/hammunition_devctl").glob("*.py"))
    assert package == source
    assert all(_mode(root / LIB / "hammunition_devctl" / name) == 0o644 for name in package)


def test_the_wrapper_names_the_copy_in_usr_local_never_the_checkout(root: Path) -> None:
    _script("install.sh", root, "--helper-only", "--yes", "--interpreter", "/opt/engine/bin/python")
    text = (root / WRAPPER).read_text()
    assert text.splitlines()[1] == MARK
    assert "exec /opt/engine/bin/python -I /usr/local/lib/hammunition-devctl/hammunition-devctl" in text
    assert str(ROOT) not in text
    assert str(ROOT) not in (root / POLICY).read_text()


def test_the_installed_copy_runs_isolated_and_ignores_the_working_directory(
    root: Path, tmp_path: Path
) -> None:
    """The wrapper's `-I` and `cd /`, exercised on the installed copy: a
    directory holding its own hammunition_devctl package must not be imported."""
    _script("install.sh", root, "--helper-only", "--yes")
    trap = tmp_path / "trap"
    (trap / "hammunition_devctl").mkdir(parents=True)
    (trap / "hammunition_devctl/__init__.py").write_text("raise SystemExit('PWNED')\n")
    done = subprocess.run(
        [sys.executable, "-I", str(root / LIB / "hammunition-devctl"), "--version"],
        cwd=trap,
        env={**os.environ, "PYTHONPATH": str(trap)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.stdout == "hammunition-devctl contract 1\n", done.stderr


def test_a_run_with_no_terminal_and_no_yes_installs_nothing(root: Path) -> None:
    done = _script("install.sh", root, "--helper-only")
    assert done.returncode == 0
    assert "NOT installed" in done.stderr
    assert not root.exists()


def test_a_wrapper_another_installer_wrote_is_left_alone_without_force(root: Path) -> None:
    foreign = root / WRAPPER
    foreign.parent.mkdir(parents=True)
    foreign.write_text("#!/bin/sh\n# Installed by `hammunition hardware apply` (D-056).\nexit 0\n")
    done = _script("install.sh", root, "--helper-only", "--yes")
    assert done.returncode == 0
    assert "Left alone" in done.stdout
    assert "hardware apply" in foreign.read_text()
    assert not (root / LIB).exists() and not (root / POLICY).exists()


def test_force_replaces_a_foreign_wrapper(root: Path) -> None:
    foreign = root / WRAPPER
    foreign.parent.mkdir(parents=True)
    foreign.write_text("#!/bin/sh\n# written by something else\n")
    _script("install.sh", root, "--helper-only", "--yes", "--force-helper")
    assert MARK in foreign.read_text()


def test_installing_twice_is_the_same_tree(root: Path) -> None:
    def tree() -> dict[str, bytes]:
        return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}

    _script("install.sh", root, "--helper-only", "--yes")
    first = tree()
    _script("install.sh", root, "--helper-only", "--yes")
    assert tree() == first


def test_uninstall_removes_ours_and_nothing_else(root: Path) -> None:
    _script("install.sh", root, "--helper-only", "--yes")
    other = root / "usr/share/polkit-1/actions/com.example.other.policy"
    other.write_text("<policyconfig/>")
    done = _script("uninstall.sh", root, "--helper-only", "--yes")
    assert done.returncode == 0, done.stderr
    assert not (root / WRAPPER).exists()
    assert not (root / POLICY).exists()
    assert not (root / LIB).exists()
    assert other.exists()


def test_uninstall_leaves_a_foreign_wrapper_and_its_policy(root: Path) -> None:
    foreign = root / WRAPPER
    policy = root / POLICY
    foreign.parent.mkdir(parents=True)
    policy.parent.mkdir(parents=True)
    foreign.write_text("#!/bin/sh\n# Installed by `hammunition hardware apply` (D-056).\n")
    policy.write_text("<policyconfig/>")
    done = _script("uninstall.sh", root, "--helper-only", "--yes")
    assert "Left alone" in done.stdout
    assert foreign.exists() and policy.exists()


def test_uninstall_without_the_helper_flag_never_touches_the_helper(
    root: Path, tmp_path: Path
) -> None:
    """The default stays what the README always promised: the applet only.
    kpackagetool6 is a stand-in that succeeds, so the applet half runs."""
    _script("install.sh", root, "--helper-only", "--yes")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "kpackagetool6"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HAMMUNITION_DEVCTL_ROOT": str(root),
        "HAMMUNITION_DEVCTL_SUDO": "",
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    done = subprocess.run(
        [str(ROOT / "uninstall.sh"), "--yes"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "Applet removed" in done.stdout
    assert (root / WRAPPER).exists() and (root / POLICY).exists() and (root / LIB).exists()


def test_both_scripts_refuse_an_unknown_option(root: Path) -> None:
    for name in ("install.sh", "uninstall.sh"):
        assert _script(name, root, "--nope").returncode == 2


def test_a_relative_interpreter_is_refused(root: Path) -> None:
    done = _script("install.sh", root, "--helper-only", "--yes", "--interpreter", "python3")
    assert done.returncode == 2 and "absolute" in done.stderr


def test_the_render_script_refuses_a_relative_or_multiline_path() -> None:
    script = ROOT / "scripts/render_helper_files.py"
    for bad in ("rel/python", "/ok\n/etc"):
        done = subprocess.run(
            [sys.executable, str(script), "wrapper", bad, "/usr/bin/x"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode != 0 and done.stdout == ""
