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
from typing import Any

# Icons for each state (kept text-glyphs so no asset files are needed).
_ICONS = {"idle": "🎙", "listening": "🔴", "transcribing": "⏳"}


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

    logic = App(cfg)

    class YapBar(rumps.App):
        def __init__(self):
            super().__init__("yap", title=_ICONS["idle"], quit_button=None)
            self.status_item = rumps.MenuItem("Starting…")
            mode = cfg["hotkey"]["mode"]
            combo = cfg["hotkey"]["combo"]
            self.menu = [
                self.status_item,
                rumps.MenuItem(describe_mode(mode, combo)),
                None,
                rumps.MenuItem(f"Engine: {logic.engine.name}", callback=self._toggle_engine),
                None,
                rumps.MenuItem("Quit yap", callback=self._quit),
            ]
            logic.status_cb = self._on_status
            self._listener = None
            # start the engine off the main thread so the menu appears instantly
            threading.Thread(target=self._boot, daemon=True).start()

        def _boot(self):
            self._listener = logic.start_background()
            self.status_item.title = "Ready — hold your hotkey to dictate"

        def _on_status(self, state: str):
            # called from worker threads; rumps title set is thread-safe enough here
            self.title = _ICONS.get(state, _ICONS["idle"])
            self.status_item.title = {
                "idle": "Ready — hold your hotkey to dictate",
                "listening": "● Listening…",
                "transcribing": "⏳ Transcribing…",
            }.get(state, "Ready")

        def _toggle_engine(self, sender):
            # flip local <-> cloud for the *next* launch (engine is built at start)
            new = "cloud" if logic.engine.name == "local" else "local"
            from . import config as _config

            saved = _config.load()
            saved["engine"] = new
            _config.save(saved)
            rumps.alert("yap", f"Engine set to '{new}'. Quit and relaunch yap to apply.")

        def _quit(self, _sender):
            if self._listener is not None:
                self._listener.stop()
            rumps.quit_application()

    YapBar().run()
    return 0
