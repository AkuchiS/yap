"""`yap autostart` — run yap as a background agent that starts at login.

This is the no-terminal, no-menu-bar way to use yap day to day: a tiny login
agent runs `yap run` in the background, so you just hold your hotkey and dictate.
On macOS it deliberately uses the headless `yap run` (not the menu-bar app), which
keeps a single keyboard listener and so avoids the macOS 26 Text-Input-Source
abort that an app event loop triggers.

  yap autostart        # enable: start now + at every login
  yap autostart --off  # disable and stop it
  yap autostart --status
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.akuchis.yap"


def _yap_cmd() -> list[str]:
    """The command that launches the daemon, found with a login-shell-safe path."""
    exe = shutil.which("yap")
    if exe:
        return [exe, "run", "--quiet"]
    # pipx venv fallback (Finder/launchd have a minimal PATH)
    venv_py = Path.home() / ".local/pipx/venvs/yap-dictation/bin/python"
    if venv_py.exists():
        return [str(venv_py), "-m", "yap", "run", "--quiet"]
    return [sys.executable, "-m", "yap", "run", "--quiet"]


# ----------------------------------------------------------------- macOS -------
def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _mac_enable() -> int:
    logs = Path.home() / "Library" / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    plist = _mac_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "Label": LABEL,
        "ProgramArguments": _yap_cmd(),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(logs / "yap.log"),
        "StandardErrorPath": str(logs / "yap.log"),
        "ProcessType": "Interactive",
    }
    with open(plist, "wb") as f:
        plistlib.dump(data, f)
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
                       capture_output=True, text=True)
    if r.returncode != 0:  # older macOS verb
        subprocess.run(["launchctl", "load", "-w", str(plist)], capture_output=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"], capture_output=True)
    print(f"✓ yap will now run in the background and start at login.\n  agent : {plist}")
    print("  Hold your hotkey and dictate. Logs: ~/Library/Logs/yap.log")
    print("  (If keys aren't captured, grant this Python Accessibility + Input")
    print("   Monitoring once in System Settings → Privacy & Security.)")
    return 0


def _mac_disable() -> int:
    plist = _mac_plist_path()
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    if plist.exists():
        plist.unlink()
    print("✓ yap background agent disabled and stopped.")
    return 0


# ----------------------------------------------------------------- Linux -------
def _linux_unit_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user" / "yap.service"


def _linux_enable() -> int:
    unit = _linux_unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    cmd = " ".join(_yap_cmd())
    unit.write_text(
        "[Unit]\nDescription=yap dictation daemon\n\n"
        f"[Service]\nExecStart={cmd}\nRestart=on-failure\n\n"
        "[Install]\nWantedBy=default.target\n")
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "yap.service"],
                       capture_output=True)
        print(f"✓ yap enabled as a user service (starts at login).\n  unit: {unit}")
        print("  Status: systemctl --user status yap")
    else:
        print(f"✓ wrote {unit}, but systemd --user isn't available here.")
        print(f"  Add this to your session startup instead:  {cmd}")
    return 0


def _linux_disable() -> int:
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "disable", "--now", "yap.service"],
                       capture_output=True)
    unit = _linux_unit_path()
    if unit.exists():
        unit.unlink()
    print("✓ yap user service disabled.")
    return 0


def _status() -> int:
    if sys.platform == "darwin":
        on = _mac_plist_path().exists()
    elif os.name != "nt":
        on = _linux_unit_path().exists()
    else:
        on = False
    print("yap autostart:", "ENABLED" if on else "disabled")
    return 0


def run(off: bool = False, status: bool = False) -> int:
    if status:
        return _status()
    if sys.platform == "darwin":
        return _mac_disable() if off else _mac_enable()
    if os.name == "nt":
        print("yap autostart isn't wired for Windows yet — add `yap run` to your "
              "Startup folder (Win+R → shell:startup).", file=sys.stderr)
        return 1
    return _linux_disable() if off else _linux_enable()
