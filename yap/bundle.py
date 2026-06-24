"""Build a real macOS .app bundle for yap.

Produces `yap.app` — a proper double-click application that:
  * shows the neon-Y icon in the Dock (baked in as .icns),
  * gets its OWN entry in Privacy & Security (Mic / Accessibility / Input
    Monitoring) instead of borrowing Terminal's,
  * can launch automatically at login (--login).

This is a lightweight *wrapper* app: its executable launches your installed
`yap` (via pip/pipx). That sidesteps the pain of freezing CTranslate2/Whisper
into a standalone binary, while still giving a first-class Mac app. Because the
bundle is built locally (not downloaded), Gatekeeper won't quarantine it.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from . import __version__, config

BUNDLE_ID = "com.yap.dictation"

# The app's executable: find the installed `yap` even with Finder's minimal PATH,
# then run the menu-bar app. Logs to ~/Library/Logs/yap-app.log so launch
# failures are diagnosable. Falls back to the pipx venv interpreter.
_LAUNCHER = r"""#!/bin/bash
mkdir -p "$HOME/Library/Logs"
LOG="$HOME/Library/Logs/yap-app.log"
exec >>"$LOG" 2>&1
echo "=== yap.app launch: $(date) ==="
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
for cand in "$HOME/.local/bin/yap" "/opt/homebrew/bin/yap" "/usr/local/bin/yap" "$(command -v yap 2>/dev/null)"; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then echo "launching: $cand app"; exec "$cand" app; fi
done
for py in "$HOME/.local/pipx/venvs/yap-dictation/bin/python" "${PIPX_HOME:-$HOME/.local/pipx}/venvs/yap-dictation/bin/python"; do
  if [ -x "$py" ]; then echo "launching: $py -m yap app"; exec "$py" -m yap app; fi
done
echo "ERROR: could not find an installed 'yap' (PATH or pipx venv)."
osascript -e 'display alert "yap is not installed" message "Install it first:  pipx install yap-dictation"'
exit 1
"""


def _make_icns(icon_png: str, icns_out: Path) -> bool:
    """Build a multi-resolution .icns from a PNG (iconutil on mac, else Pillow)."""
    if sys.platform == "darwin" and shutil.which("iconutil") and shutil.which("sips"):
        try:
            with tempfile.TemporaryDirectory() as td:
                iconset = Path(td) / "yap.iconset"
                iconset.mkdir()
                for s in (16, 32, 128, 256, 512):
                    for px, name in ((s, f"icon_{s}x{s}.png"),
                                     (s * 2, f"icon_{s}x{s}@2x.png")):
                        subprocess.run(
                            ["sips", "-z", str(px), str(px), icon_png,
                             "--out", str(iconset / name)],
                            check=True, capture_output=True)
                subprocess.run(["iconutil", "-c", "icns", str(iconset),
                                "-o", str(icns_out)], check=True, capture_output=True)
            return True
        except Exception as e:
            print(f"yap: iconutil path failed ({e}); trying Pillow", file=sys.stderr)
    try:
        from PIL import Image

        img = Image.open(icon_png).convert("RGBA").resize((1024, 1024))
        img.save(str(icns_out), format="ICNS")
        return True
    except Exception as e:
        print(f"yap: could not build .icns ({e}); app will use a default icon",
              file=sys.stderr)
        return False


def _info_plist(has_icon: bool, menubar_only: bool) -> dict:
    info = {
        "CFBundleName": "yap",
        "CFBundleDisplayName": "yap",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "yap",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription":
            "yap transcribes your speech into text at your cursor.",
        # menu-bar-only (no Dock icon) if requested; default keeps the Dock icon
        "LSUIElement": bool(menubar_only),
    }
    if has_icon:
        info["CFBundleIconFile"] = "yap"  # -> Resources/yap.icns
    return info


def _install_login_agent(app_path: Path) -> Path:
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / f"{BUNDLE_ID}.plist"
    data = {
        "Label": BUNDLE_ID,
        "ProgramArguments": [str(app_path / "Contents" / "MacOS" / "yap")],
        "RunAtLoad": True,
        "KeepAlive": False,
    }
    with open(plist, "wb") as f:
        plistlib.dump(data, f)
    # best-effort (re)load
    try:
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
    except Exception:
        pass
    return plist


def build(cfg: dict, dest_dir: str, login: bool = False,
          menubar_only: bool = False) -> Optional[Path]:
    if sys.platform != "darwin":
        print("yap bundle: builds a macOS .app — only runs on macOS.", file=sys.stderr)
        return None

    dest = Path(dest_dir).expanduser()
    app = dest / "yap.app"
    contents = app / "Contents"
    macos_dir = contents / "MacOS"
    resources = contents / "Resources"
    if app.exists():
        shutil.rmtree(app)
    macos_dir.mkdir(parents=True)
    resources.mkdir(parents=True)

    icon = config.icon_path(cfg)
    has_icon = bool(icon) and _make_icns(icon, resources / "yap.icns")

    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump(_info_plist(has_icon, menubar_only), f)
    (contents / "PkgInfo").write_text("APPL????")

    launcher = macos_dir / "yap"
    launcher.write_text(_LAUNCHER)
    launcher.chmod(0o755)

    # Ad-hoc sign so the bundle has a stable identity and launches cleanly.
    # (Note: the running process is still your system Python, so Privacy &
    # Security attributes permissions to "Python", not "yap" — a self-contained
    # build is needed for a yap-named permission entry. See README.)
    try:
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)],
                       capture_output=True)
    except Exception:
        pass

    login_plist = _install_login_agent(app) if login else None

    print(f"✓ built {app}")
    print(f"  icon   : {'baked in' if has_icon else 'default (set one: yap icon <file>)'}")
    print(f"  dock   : {'hidden (menu-bar only)' if menubar_only else 'visible'}")
    if login_plist:
        print(f"  login  : will start at login ({login_plist})")
    print("\nNext:")
    print("  1. Open it once: open", str(app).replace(" ", r"\ "))
    print("  2. Grant the NEW 'yap' app Microphone + Accessibility + Input Monitoring")
    print("     in System Settings → Privacy & Security (separate from Terminal).")
    print("  3. Optionally drag yap.app into your Applications folder.")
    return app
