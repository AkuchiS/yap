"""Cross-platform system-tray app for Windows & Linux — the pystray counterpart to
the macOS menu-bar app (`yap/menubar.py`). A tray icon reflects idle / listening /
transcribing while the dictation daemon runs in the background, with a small menu to
switch engine and quit.

macOS uses the richer rumps menu-bar app instead (see `cli._cmd_app`). Needs
`pystray` + `pillow` (the `[full]` extra). Headless boxes have no tray — use `yap run`.
"""

from __future__ import annotations

import sys
import threading  # noqa: F401  (App spins its own threads; kept for parity/clarity)
from typing import Any

from . import config

# Status → tray-dot colour + tooltip. A generated dot always works (no asset needed).
_COLORS = {
    "idle": (138, 43, 226),          # brand purple
    "listening": (220, 50, 50),      # red
    "transcribing": (235, 170, 30),  # amber
}
_LABEL = {
    "idle": "yap — ready (hold your hotkey)",
    "listening": "yap — listening…",
    "transcribing": "yap — transcribing…",
}


def _state_image(state: str, size: int = 64):
    """A simple filled-circle icon for the given state (RGBA, transparent bg)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill = _COLORS.get(state, _COLORS["idle"]) + (255,)
    pad = max(2, size // 8)
    draw.ellipse([pad, pad, size - pad, size - pad], fill=fill)
    return img


def run(cfg: dict[str, Any]) -> int:
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        print("yap app: the tray needs pystray + pillow.\n"
              "  pipx inject yap-dictation pystray pillow\n"
              "…or just run the daemon (no tray): yap run", file=sys.stderr)
        return 2

    import pystray
    from .app import App

    logic = App(cfg)
    state = {"s": "idle"}
    icon = None  # set below; referenced by _set via closure

    def _set(s: str) -> None:
        state["s"] = s
        if icon is None:
            return
        try:
            icon.icon = _state_image(s)
            icon.title = _LABEL.get(s, _LABEL["idle"])
        except Exception:
            pass

    def _toggle_engine(_icon, _item) -> None:
        new = "cloud" if logic.engine.name == "local" else "local"
        saved = config.load()
        saved["engine"] = new
        config.save(saved)
        try:
            _icon.notify(f"Engine set to '{new}'. Restart yap to apply.", "yap")
        except Exception:
            pass

    def _quit(_icon, _item) -> None:
        try:
            if listener is not None:
                listener.stop()
        except Exception:
            pass
        _icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda _i: _LABEL.get(state["s"], _LABEL["idle"]),
                         None, enabled=False),
        pystray.MenuItem(lambda _i: f"Engine: {logic.engine.name}  (click to switch)",
                         _toggle_engine),
        pystray.MenuItem("Quit yap", _quit),
    )
    icon = pystray.Icon("yap", _state_image("idle"), _LABEL["idle"], menu)
    logic.status_cb = _set

    listener = logic.start_background()  # hotkey + engine, off the tray loop
    icon.run()                          # blocks until Quit
    try:
        if listener is not None:
            listener.stop()
    except Exception:
        pass
    return 0
