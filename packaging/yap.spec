# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a self-contained yap app (macOS .app / Windows .exe / Linux).

Build:  pyinstaller packaging/yap.spec --noconfirm
Output: dist/yap/  (and dist/yap.app on macOS)

The hard part is the Whisper stack — faster-whisper + ctranslate2 (C++) +
onnxruntime (VAD) + tokenizers (Rust). We collect each fully so their native
libraries and data files come along. Optional GUI/audio packages are collected
only if installed, so the same spec works on a headless box and a full desktop.

A custom icon is picked up from $YAP_ICNS (macOS .icns) / $YAP_ICO (Windows .ico).
"""

import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_all

PKG_ROOT = SPECPATH                       # packaging/ (SPECPATH is already a dir)
PROJECT = os.path.dirname(PKG_ROOT)       # repo root
ENTRY = os.path.join(PKG_ROOT, "entry.py")

datas, binaries, hiddenimports = [], [], []


def _collect(pkg, required=False):
    if importlib.util.find_spec(pkg) is None:
        if required:
            raise SystemExit(f"yap.spec: required package not installed: {pkg}")
        return False
    d, b, h = collect_all(pkg)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)
    return True


# The Whisper stack (must be present to build a working app).
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers"):
    _collect(pkg, required=True)

# Optional: present on a full desktop, absent on a headless build box.
for pkg in ("av", "sounddevice", "pynput", "pyperclip", "rumps", "PIL", "numpy"):
    _collect(pkg)

# pyobjc bits the menu-bar app needs on macOS (rumps' deps + permission APIs).
if sys.platform == "darwin":
    hiddenimports += ["objc", "Foundation", "AppKit", "PyObjCTools",
                      "CoreFoundation", "Quartz", "ApplicationServices",
                      "HIServices"]
    for pkg in ("ApplicationServices",):
        _collect(pkg)

# Built-in self-test clip so `yap selftest` works inside the frozen app.
sample = os.path.join(PROJECT, "tests", "jfk.wav")
if os.path.exists(sample):
    datas.append((sample, "."))

a = Analysis(
    [ENTRY],
    pathex=[PROJECT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # keep the bundle lean: yap never needs these heavyweights
    excludes=["torch", "tensorflow", "matplotlib", "tkinter", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# console=True keeps stderr/stdout usable for CLI subcommands and debugging.
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="yap",
    console=True,
    disable_windowed_traceback=False,
    icon=os.environ.get("YAP_ICO") or None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="yap")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Yap.app",
        icon=os.environ.get("YAP_ICNS") or None,
        bundle_identifier="com.yap.dictation",
        version="0.1.0",
        info_plist={
            "CFBundleName": "Yap",
            "CFBundleDisplayName": "Yap",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "LSUIElement": bool(os.environ.get("YAP_MENUBAR_ONLY")),
            "NSMicrophoneUsageDescription":
                "yap transcribes your speech into text at your cursor.",
        },
    )
