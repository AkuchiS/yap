"""macOS menu-bar app — 'just like Wispr'.

A small icon in the menu bar that flips between idle / listening / transcribing,
plus quick toggles for engine and verbosity. The dictation engine runs in the
background; rumps owns the main loop.

Requires `rumps` (macOS only):  pip install "yap-dictation[macos]"
Launch with:  yap app
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Optional

from . import config

# Icons for each state (kept text-glyphs so no asset files are needed).
_ICONS = {"idle": "🎙", "listening": "🔴", "transcribing": "⏳"}


def _request_permissions() -> None:
    """Proactively ask macOS for the permissions the hotkey needs, so a freshly
    built Yap.app *appears* in System Settings → Privacy & Security and the user
    can grant it. Without this the app never asks, never lists, can't be granted.

      • Accessibility  — needed to synthesize the paste keystroke. Prompting
        registers the app and shows the "control your computer" dialog.
      • Input Monitoring — needed to watch the hotkey. IOHIDRequestAccess with
        kIOHIDRequestTypeListenEvent registers + prompts for it.
    """
    # Accessibility (ApplicationServices / HIServices via pyobjc)
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

    # Input Monitoring (IOKit IOHIDRequestAccess via ctypes — no extra dep)
    try:
        import ctypes

        iokit = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDRequestAccess.restype = ctypes.c_bool
        iokit.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
        iokit.IOHIDRequestAccess(1)  # kIOHIDRequestTypeListenEvent
    except Exception as e:
        print(f"yap: could not request Input Monitoring ({e})", file=sys.stderr)


def _show_in_dock() -> None:
    """Force a Dock icon. rumps apps default to 'accessory' (menu-bar only),
    which hides the Dock icon even with LSUIElement=false — so set the
    activation policy to Regular explicitly."""
    try:
        from AppKit import NSApplication

        # NSApplicationActivationPolicyRegular = 0 (Dock icon + menu bar)
        NSApplication.sharedApplication().setActivationPolicy_(0)
    except Exception as e:
        print(f"yap: could not show Dock icon ({e})", file=sys.stderr)


def _set_dock_icon(path: Optional[str]) -> bool:
    """Set the Dock/app icon to a user image at runtime (macOS, via AppKit)."""
    if not path:
        return False
    try:
        from AppKit import NSApplication, NSImage

        img = NSImage.alloc().initByReferencingFile_(path)
        if img is not None and img.isValid():
            NSApplication.sharedApplication().setApplicationIconImage_(img)
            return True
        print(f"yap: icon file isn't a valid image: {path}", file=sys.stderr)
    except Exception as e:
        print(f"yap: could not set Dock icon ({e})", file=sys.stderr)
    return False


def run(cfg: dict[str, Any]) -> int:
    if sys.platform != "darwin":
        print("yap app: the menu-bar app is macOS-only for now. Use `yap run` "
              "elsewhere (a cross-platform tray is on the roadmap).", file=sys.stderr)
        return 2
    try:
        import rumps
    except Exception:
        print("yap app: needs rumps. Install it:\n"
              "  pip install rumps    (or: pipx inject yap-dictation rumps)",
              file=sys.stderr)
        return 2

    from .app import App
    from .hotkey import describe_mode

    # Make the app appear in (and prompt for) Privacy & Security on launch.
    _request_permissions()

    logic = App(cfg)

    class YapBar(rumps.App):
        def __init__(self):
            super().__init__("Yap", title=_ICONS["idle"], quit_button=None)
            if not (cfg.get("app", {}) or {}).get("menubar_only"):
                _show_in_dock()  # Dock icon + menu bar (default)
            _set_dock_icon(config.icon_path(cfg))
            self.status_item = rumps.MenuItem("Starting…")
            mode = cfg["hotkey"]["mode"]
            combo = cfg["hotkey"]["combo"]
            # Explicit "switch to" label so a stray click can't silently strand
            # you on the cloud engine (which needs an API key).
            other = "cloud" if logic.engine.name == "local" else "local"
            self.menu = [
                self.status_item,
                rumps.MenuItem(describe_mode(mode, combo)),
                None,
                rumps.MenuItem("Learn from my last correction", callback=self._relearn),
                rumps.MenuItem(f"Engine: {logic.engine.name}  ·  switch to {other}",
                               callback=self._toggle_engine),
                None,
                rumps.MenuItem("Quit Yap", callback=self._quit),
            ]
            logic.status_cb = self._on_status
            logic.notify_cb = self._notify_user
            self._listener = None
            # start the engine off the main thread so the menu appears instantly
            threading.Thread(target=self._boot, daemon=True).start()

            # check for a newer release in the background (cached ~daily) and, if
            # there is one, surface it as a menu item via a main-loop timer.
            self._pending_update = None
            self._update_added = False
            self._update_ticks = 0
            threading.Thread(target=self._check_update, daemon=True).start()
            try:
                self._update_timer = rumps.Timer(self._surface_update, 3)
                self._update_timer.start()
            except Exception:
                pass

        def _main(self, fn):
            """Run a UI mutation on the AppKit main thread. rumps/AppKit are NOT
            thread-safe — mutating the status item / title / menu from a worker thread
            corrupts the view hierarchy (the `_enumeratingSubviewsCount` assertion →
            SIGABRT). callAfter marshals onto the main run loop."""
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(fn)
            except Exception:
                try:
                    fn()
                except Exception:
                    pass

        def _boot(self):
            self._listener = logic.start_background()
            self._main(lambda: setattr(self.status_item, "title",
                                       "Ready — hold your hotkey to dictate"))

        def _check_update(self):
            try:
                from . import update as _update
                info = _update.check_for_update()
                if info and info.get("available"):
                    self._pending_update = info
            except Exception:
                pass

        def _surface_update(self, timer):
            # runs on the rumps main loop; safe to touch the menu here
            info = self._pending_update
            if info and not self._update_added:
                try:
                    import webbrowser
                    url = info["url"]
                    item = rumps.MenuItem(
                        f"⬆︎  Update available: v{info['latest']}",
                        callback=lambda _s, u=url: webbrowser.open(u))
                    try:
                        self.menu.insert_before("Quit Yap", item)
                    except Exception:
                        self.menu.add(item)
                    self._update_added = True
                except Exception:
                    pass
            self._update_ticks += 1
            if self._update_added or self._update_ticks > 10:  # surfaced, or give up after ~30s
                try:
                    timer.stop()
                except Exception:
                    pass

        def _on_status(self, state: str):
            # called from worker threads — marshal the UI change onto the main thread
            # (mutating title/status off-thread trips an AppKit assertion → SIGABRT).
            title = _ICONS.get(state, _ICONS["idle"])
            sub = {
                "idle": "Ready — hold your hotkey to dictate",
                "listening": "● Listening…",
                "transcribing": "⏳ Transcribing…",
            }.get(state, "Ready")

            def apply():
                self.title = title
                self.status_item.title = sub
            self._main(apply)

        def _relearn(self, _sender):
            try:
                logic.on_relearn()   # reads clipboard, diffs vs last typed, notifies
            except Exception as e:
                self._notify_user(f"relearn failed: {e}")

        def _notify_user(self, msg):
            def show():
                self.status_item.title = msg
                try:
                    rumps.notification("yap", "", msg)
                except Exception:
                    pass
            self._main(show)

        def _toggle_engine(self, sender):
            # flip local <-> cloud for the *next* launch (engine is built at start)
            new = "cloud" if logic.engine.name == "local" else "local"
            saved = config.load()
            saved["engine"] = new
            config.save(saved)
            note = ""
            if new == "cloud":
                note = ("\n\nCloud needs an API key in $YAP_API_KEY. Without one, "
                        "yap will warn at startup and dictation won't work — switch "
                        "back to 'local' if you don't have a key set.")
            rumps.alert("yap", f"Engine set to '{new}'. Quit and relaunch yap to apply.{note}")

        def _quit(self, _sender):
            if self._listener is not None:
                self._listener.stop()
            logic.stop_relearn()
            rumps.quit_application()

    YapBar().run()
    return 0
