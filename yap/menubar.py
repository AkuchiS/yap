"""macOS menu-bar app — the icon-in-the-menu-bar dictation experience.

Architecture (important): EVERYTHING runs in THIS process — the trusted Yap.app
the user grants. The global hotkey is a Quartz CGEventTap installed on the MAIN
run loop (see ``yap/mac_tap.py``); its callback fires on the main thread, which
is the rule macOS 26 enforces for a UI app touching the Text Input Source API.
Recording, transcription and injection run in-process too, so the Accessibility /
Input-Monitoring / Microphone grants the user gives Yap.app actually apply to the
code doing the work.

This replaced the earlier design that spawned a separate ``yap run`` daemon for
the keyboard/mic work: macOS TCC does NOT extend an app's permission grant to a
process it spawns, so that child was reported "not trusted" and recorded silence.
Keeping the listener in THIS process, on the main thread, satisfies both
constraints at once — trusted AND crash-free on macOS 26.

Requires `rumps` (macOS only):  pip install "yap-dictation[macos]"
Launch with:  yap app
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Optional

from . import config

# Menu-bar state glyphs (used as the title; the brand icon, if available, sits
# beside them). Kept as text so the app needs no asset files to show *something*.
_GLYPH = {"idle": "🎙", "listening": "🔴", "transcribing": "⏳", "starting": "…"}


def _request_permissions() -> None:
    """Ask macOS for the permissions yap needs so Yap.app *appears* in System
    Settings → Privacy & Security and can be granted. Because capture now runs in
    THIS process, the grant the user gives here is the grant the key tap uses."""
    try:
        try:
            from ApplicationServices import (  # type: ignore
                AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt)
        except Exception:
            from HIServices import (  # type: ignore
                AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt)
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    except Exception as e:
        print(f"yap: could not request Accessibility ({e})", file=sys.stderr)
    try:
        import ctypes
        iokit = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDRequestAccess.restype = ctypes.c_bool
        iokit.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
        iokit.IOHIDRequestAccess(1)  # kIOHIDRequestTypeListenEvent (Input Monitoring)
    except Exception as e:
        print(f"yap: could not request Input Monitoring ({e})", file=sys.stderr)
    # Microphone: opening a CoreAudio/PortAudio input stream does NOT reliably
    # surface the TCC prompt for our app (it just records zeros), so ask
    # AVFoundation explicitly — the same up-front pattern as the two grants above.
    # Without this the user has no way to grant the mic (the Microphone pane has
    # no "+" to add an app manually); the request is what creates the entry.
    try:
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        except Exception:
            from AVFoundation import AVCaptureDevice
            AVMediaTypeAudio = "soun"  # AVMediaTypeAudio constant value
        # 0 = notDetermined → prompt; 3 = authorized (leave it alone)
        if AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) == 0:
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVMediaTypeAudio, lambda _granted: None)
    except Exception as e:
        print(f"yap: could not request Microphone ({e})", file=sys.stderr)


def _show_in_dock() -> None:
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(0)  # Regular: Dock + menu bar
    except Exception as e:
        print(f"yap: could not show Dock icon ({e})", file=sys.stderr)


def _set_dock_icon(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        from AppKit import NSApplication, NSImage
        img = NSImage.alloc().initByReferencingFile_(path)
        if img is not None and img.isValid():
            NSApplication.sharedApplication().setApplicationIconImage_(img)
            return True
    except Exception as e:
        print(f"yap: could not set Dock icon ({e})", file=sys.stderr)
    return False


def run(cfg: dict[str, Any]) -> int:
    if sys.platform != "darwin":
        print("yap app: the menu-bar app is macOS-only for now. Use `yap run` "
              "elsewhere.", file=sys.stderr)
        return 2
    try:
        import rumps
    except Exception:
        print("yap app: needs rumps. Install it:\n"
              "  pip install rumps    (or: pipx inject yap-dictation rumps)",
              file=sys.stderr)
        return 2

    from . import mac_tap
    from .app import App
    from .hotkey import describe_mode

    _request_permissions()
    icon_path = config.icon_path(cfg)
    mode, combo = cfg["hotkey"]["mode"], cfg["hotkey"]["combo"]

    class YapBar(rumps.App):
        def __init__(self):
            super().__init__("Yap", title=_GLYPH["starting"], icon=icon_path,
                             template=False, quit_button=None)
            if not (cfg.get("app", {}) or {}).get("menubar_only"):
                _show_in_dock()
            _set_dock_icon(icon_path)
            self.app: Optional[App] = None   # in-process engine (set once warm)
            self.tap = None                  # main-thread Quartz key tap
            self.status_item = rumps.MenuItem("Starting the dictation engine…")
            self.menu = [
                self.status_item,
                rumps.MenuItem(describe_mode(mode, combo)),
                None,
                rumps.MenuItem("Start / stop dictation", callback=self._toggle),
                rumps.MenuItem("Learn from my last correction", callback=self._relearn),
                None,
                rumps.MenuItem("Quit Yap", callback=self._quit),
            ]
            # Install the key tap NOW, on this (the main) thread — it's trusted the
            # moment the grants exist. Warm the heavy engine off the UI thread.
            self._install_tap()
            threading.Thread(target=self._boot, daemon=True).start()

        # -- main-thread UI marshalling -------------------------------------
        def _main(self, fn):
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(fn)
            except Exception:
                try:
                    fn()
                except Exception:
                    pass

        # -- key tap (main thread) ------------------------------------------
        def _install_tap(self):
            self.tap = mac_tap.start(cfg, on_start=self._hk_start,
                                     on_stop=self._hk_stop,
                                     on_relearn=self._hk_relearn)
            if not getattr(self.tap, "ok", False):
                self.status_item.title = (
                    "Grant Yap Accessibility + Input Monitoring in System "
                    "Settings, then reopen Yap")
                why = getattr(self.tap, "error", None)
                if why:
                    print(f"yap: key tap not active: {why}", file=sys.stderr)

        # The tap fires on the main thread; guard until the engine is warm.
        def _hk_start(self):
            if self.app is not None:
                self.app.on_start()

        def _hk_stop(self):
            if self.app is not None:
                self.app.on_stop()

        def _hk_relearn(self):
            if self.app is not None:
                self.app.on_relearn()

        # -- engine lifecycle (background) ----------------------------------
        def _boot(self):
            try:
                app = App(cfg)
                app.status_cb = lambda st: self._main(lambda: self._reflect(st))
                app.notify_cb = lambda m: self._main(lambda: self._notify(m))
                # Warm the model + bring up the control socket, but NOT the pynput
                # listener — the main-thread Quartz tap above owns key capture.
                app.start_background(use_global_hotkey=False)
                self.app = app
                if getattr(self.tap, "ok", False):
                    self._main(lambda: setattr(
                        self.status_item, "title",
                        "Ready — hold your hotkey to dictate"))
            except Exception as e:
                self._main(lambda: setattr(self.status_item, "title",
                                           f"couldn't start engine: {e}"))

        def _reflect(self, state):
            self.title = _GLYPH.get(state, _GLYPH["idle"])

        # -- menu actions ----------------------------------------------------
        def _toggle(self, _sender):
            if self.app is not None:
                self.app.toggle()

        def _relearn(self, _sender):
            if self.app is None:
                self._notify("still starting the engine…")
                return
            self.app.on_relearn()  # result is surfaced via notify_cb

        def _notify(self, msg):
            self.status_item.title = msg
            try:
                rumps.notification("Yap", "", msg)
            except Exception:
                pass

        def _quit(self, _sender):
            if self.tap is not None:
                try:
                    self.tap.stop()
                except Exception:
                    pass
            import rumps as _r
            _r.quit_application()

    YapBar().run()
    return 0
