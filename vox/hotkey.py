"""Global hotkey listener (pynput) supporting toggle and push-to-talk modes.

Combo syntax follows pynput, e.g. "<ctrl>+<alt>", "<cmd>+<shift>", "<f9>".

  * toggle : pressing the combo flips recording on/off.
  * hold   : recording runs only while every key in the combo is held down.
"""

from __future__ import annotations

import sys
from typing import Callable


class HotkeyListener:
    def __init__(self, combo: str, mode: str, on_start: Callable[[], None],
                 on_stop: Callable[[], None]):
        self.combo = combo
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop
        self._listener = None
        self._active = False  # currently recording?

    # -- toggle ---------------------------------------------------------------
    def _start_toggle(self):
        from pynput import keyboard

        def toggle():
            if self._active:
                self._active = False
                self.on_stop()
            else:
                self._active = True
                self.on_start()

        self._listener = keyboard.GlobalHotKeys({self.combo: toggle})
        self._listener.start()

    # -- hold (push-to-talk) --------------------------------------------------
    def _start_hold(self):
        from pynput import keyboard

        expected = set(keyboard.HotKey.parse(self.combo))
        pressed: set = set()

        def satisfied() -> bool:
            return expected.issubset(pressed)

        def on_press(key):
            pressed.add(self._listener.canonical(key))
            if satisfied() and not self._active:
                self._active = True
                self.on_start()

        def on_release(key):
            was = satisfied()
            pressed.discard(self._listener.canonical(key))
            if was and not satisfied() and self._active:
                self._active = False
                self.on_stop()

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.start()

    def start(self):
        if self.mode == "hold":
            self._start_hold()
        else:
            self._start_toggle()
        return self

    def join(self):
        if self._listener is not None:
            self._listener.join()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()


def describe_mode(mode: str, combo: str) -> str:
    if mode == "hold":
        return f"Hold {combo} and speak; release to transcribe."
    return f"Press {combo} to start, press again to stop & transcribe."
