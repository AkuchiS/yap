"""Global hotkey listener (pynput) supporting toggle and push-to-talk modes.

Combo syntax follows pynput, e.g. "<ctrl>+<alt>", "<cmd>+<shift>", "<f9>".

  * toggle : pressing the combo flips recording on/off.
  * hold   : recording runs only while every key in the combo is held down.
"""

from __future__ import annotations

import os
import sys
from typing import Callable


def is_wayland() -> bool:
    """True on a native Wayland session.

    Wayland deliberately blocks applications from grabbing global hotkeys, so the
    pynput listener can't see keypresses in native Wayland windows no matter which
    key you bind. The supported path there is a compositor keybind -> `yap toggle`
    (see `yap.ipc`).
    """
    return (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or bool(os.environ.get("WAYLAND_DISPLAY")))


def key_sig(key):
    """Normalize a pynput Key/KeyCode to a comparable signature.

    pynput parses "<alt_r>" into a KeyCode (vk 61 on macOS) but reports the
    live keypress as the named Key.alt_r — the same physical key, two different
    objects. Reducing both to ('vk', N) (or a char) lets them compare equal.
    """
    from pynput.keyboard import Key, KeyCode

    k = key.value if isinstance(key, Key) else key
    if isinstance(k, KeyCode):
        if k.vk is not None:
            return ("vk", k.vk)
        if k.char:
            return ("char", k.char.lower())
    return ("name", str(k))


def parse_combo_sigs(combo: str) -> set:
    """The set of key signatures that must all be held for `combo` to fire."""
    from pynput import keyboard

    return {key_sig(k) for k in keyboard.HotKey.parse(combo)}


class HotkeyListener:
    """A SINGLE global listener for both the dictation hotkey and (optionally) the
    relearn hotkey.

    Running two pynput keyboard listeners at once is fatal on macOS 26: each one
    queries the Text Input Source API on its own thread and the OS aborts when
    that happens concurrently. So relearn is handled inside this one listener, not
    a second `GlobalHotKeys`.
    """

    def __init__(self, combo: str, mode: str, on_start: Callable[[], None],
                 on_stop: Callable[[], None], relearn_combo: "str | None" = None,
                 on_relearn: "Callable[[], None] | None" = None):
        self.combo = combo
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop
        self.relearn_combo = relearn_combo or None
        self.on_relearn = on_relearn
        self._listener = None
        self._active = False  # currently recording?
        self.error = None     # set if the pynput backend couldn't start (e.g. no X)

    def _fire_relearn(self):
        if self.on_relearn:
            try:
                self.on_relearn()
            except Exception:
                pass

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

        # ONE listener carries both hotkeys (never spin up a second one).
        mapping = {self.combo: toggle}
        if self.relearn_combo:
            mapping[self.relearn_combo] = self._fire_relearn
        self._listener = keyboard.GlobalHotKeys(mapping)
        self._listener.start()

    # -- hold (push-to-talk) --------------------------------------------------
    def _start_hold(self):
        from pynput import keyboard

        expected = parse_combo_sigs(self.combo)
        relearn_expected = parse_combo_sigs(self.relearn_combo) if self.relearn_combo else None
        pressed: set = set()
        relearn_armed = [True]  # fire relearn once per full press, not per repeat

        def satisfied() -> bool:
            return expected.issubset(pressed)

        def sigs(key):
            # Record BOTH the raw and canonical signatures: pynput may hand the
            # live key over in either form (e.g. Right Option's raw vk 61 vs the
            # canonicalized generic-Option vk 58). Matching either avoids the
            # mismatch that silently breaks modifier hotkeys.
            out = {key_sig(key)}
            try:
                out.add(key_sig(self._listener.canonical(key)))
            except Exception:
                pass
            return out

        def on_press(key):
            pressed.update(sigs(key))
            if satisfied() and not self._active:
                self._active = True
                self.on_start()
            if relearn_expected and relearn_expected.issubset(pressed) and relearn_armed[0]:
                relearn_armed[0] = False  # debounce until released
                self._fire_relearn()

        def on_release(key):
            was = satisfied()
            pressed.difference_update(sigs(key))
            if was and not satisfied() and self._active:
                self._active = False
                self.on_stop()
            if relearn_expected and not relearn_expected.issubset(pressed):
                relearn_armed[0] = True

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.start()

    def start(self):
        # Starting the pynput backend can fail on a session with no reachable X
        # server (e.g. a headless or pure-Wayland login). Don't let that crash the
        # daemon — record the error and let the caller fall back to the control
        # socket (`yap toggle`). `started` stays False so callers know.
        try:
            if self.mode == "hold":
                self._start_hold()
            else:
                self._start_toggle()
        except Exception as e:  # noqa: BLE001
            self.error = e
            self._listener = None
        return self

    @property
    def started(self) -> bool:
        """Whether the pynput backend actually came up. (On Wayland it may come up
        via XWayland yet still see nothing from native Wayland windows.)"""
        return self._listener is not None

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


def combo_warning(combo: str) -> str | None:
    """Return a friendly heads-up if the chosen combo is known to be unusable."""
    norm = combo.lower().replace("<", "").replace(">", "")
    if "fn" in norm.split("+"):
        return (
            "The Fn/🌐 key can't be captured (it emits no real keypress, just a "
            "hardware flag). Try '<alt_r>' (Right Option), '<cmd_r>' (Right ⌘), "
            "or '<f9>' instead:  yap config set hotkey.combo '\"<alt_r>\"'"
        )
    return None
