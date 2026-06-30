"""Guards for the macOS 26 Text-Input-Source crash fix:
  1. macOS paste must NOT go through pynput (it calls TIS on a 2nd thread).
  2. Relearn must be folded into the single listener, not a second one.

Run:  python -m pytest tests/test_macos_safety.py  (or: python tests/test_macos_safety.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yap import inject
from yap.hotkey import HotkeyListener


def test_macos_paste_is_tis_free():
    """On darwin, _send_paste uses raw Quartz events, never pynput's Controller."""
    inj = inject.Injector({"method": "paste"})
    inj._keyboard = lambda: (_ for _ in ()).throw(  # blow up if pynput is touched
        AssertionError("pynput Controller used on macOS — would crash macOS 26"))

    calls, saved_plat, saved_fn = [], sys.platform, inject._mac_send_cmd_v
    try:
        sys.platform = "darwin"
        inject._mac_send_cmd_v = lambda: calls.append("quartz")
        inj._send_paste()
    finally:
        sys.platform = saved_plat
        inject._mac_send_cmd_v = saved_fn
    assert calls == ["quartz"]


def test_macos_type_is_tis_free():
    """On darwin, typing goes via osascript (separate process), never pynput."""
    inj = inject.Injector({"method": "type"})
    inj._keyboard = lambda: (_ for _ in ()).throw(AssertionError("pynput used on macOS"))

    seen, saved_plat, saved_fn = [], sys.platform, inject._mac_osascript
    try:
        sys.platform = "darwin"
        inject._mac_osascript = lambda script, *a: seen.append((script, a))
        inj._type_text("hello world")
    finally:
        sys.platform = saved_plat
        inject._mac_osascript = saved_fn
    assert seen and seen[0][1] == ("hello world",)


def test_relearn_folded_into_single_listener():
    """Relearn is carried by the one HotkeyListener — no second listener exists."""
    fired = []
    hl = HotkeyListener("<ctrl_r>", "hold", lambda: None, lambda: None,
                        relearn_combo="<ctrl>+<alt>+l",
                        on_relearn=lambda: fired.append(1))
    assert hl.relearn_combo == "<ctrl>+<alt>+l"
    hl._fire_relearn()
    assert fired == [1]
    # a relearn callback that raises must never take the listener down
    HotkeyListener("<ctrl_r>", "hold", lambda: None, lambda: None,
                   relearn_combo="<f8>",
                   on_relearn=lambda: 1 / 0)._fire_relearn()  # no exception escapes


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
