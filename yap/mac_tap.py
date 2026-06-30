"""Main-thread Quartz CGEventTap hotkey listener for the in-process macOS app.

Why this exists (read before touching it):

  * pynput's listener queries the Text Input Source (TIS) API on its OWN thread.
    Inside an NSApplication (the menu-bar app) macOS 26 hard-aborts when TIS is
    touched off the main thread. So pynput can't drive the hotkey in-process.
  * Putting the listener in a SPAWNED child process dodged the crash but macOS
    TCC does not extend Yap.app's Accessibility/Input-Monitoring grant to a
    process it spawns → the child was "not trusted" and the mic was silent.

The path that satisfies both constraints: a CGEventTap added to the MAIN run
loop of the Yap.app process itself. The callback fires on the MAIN thread (no
TIS abort), and it's the very process the user granted permission to (trusted).

The press/release decision logic lives in `_Hotkeys`, deliberately free of any
Quartz import so it can be unit-tested off a Mac (the rest of this file can only
be exercised on macOS). `MacTap` is the thin Quartz glue around it.
"""

from __future__ import annotations

from typing import Callable, Optional


# -- Quartz virtual keycodes (kVK_*) for the keys yap hotkeys actually use ------
# Generic modifier names map to BOTH sides so "<alt>" fires on either Option key,
# while side-specific names ("<alt_r>") pin to one. yap's default is Right Option.
_NAME_TO_VK: dict[str, set[int]] = {
    "alt": {58, 61}, "alt_l": {58}, "alt_r": {61}, "alt_gr": {61},
    "option": {58, 61}, "opt": {58, 61},
    "cmd": {54, 55}, "cmd_l": {55}, "cmd_r": {54}, "command": {54, 55},
    "win": {54, 55}, "super": {54, 55},
    "ctrl": {59, 62}, "ctrl_l": {59}, "ctrl_r": {62}, "control": {59, 62},
    "shift": {56, 60}, "shift_l": {56}, "shift_r": {60},
    "f1": {122}, "f2": {120}, "f3": {99}, "f4": {118}, "f5": {96}, "f6": {97},
    "f7": {98}, "f8": {100}, "f9": {101}, "f10": {109}, "f11": {103},
    "f12": {111}, "f13": {105}, "f14": {107}, "f15": {113},
    "space": {49}, "enter": {36}, "return": {36}, "tab": {48},
    "esc": {53}, "escape": {53},
}

# ANSI letter/digit keycodes, so toggle combos like "<cmd>+<shift>+d" work too.
_CHAR_VK: dict[str, int] = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45,
    "m": 46, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26,
    "8": 28, "9": 25, "0": 29,
}

# Device-dependent modifier flag bits (IOKit NX_DEVICE*KEYMASK). On a
# flagsChanged event the modifier is DOWN iff its bit is set in the event flags —
# this is how we tell a press from a release, and left from right.
_MOD_MASK: dict[int, int] = {
    56: 0x02, 60: 0x04,    # shift  L / R
    59: 0x01, 62: 0x2000,  # control L / R
    58: 0x20, 61: 0x40,    # option  L / R
    55: 0x08, 54: 0x10,    # command L / R
}


def parse_combo(combo: Optional[str]) -> list[set[int]]:
    """Turn a pynput-style combo ("<cmd>+<shift>+d") into a list of keycode sets:
    one set per token, each holding every Quartz vk that satisfies that token.
    The combo is held when EVERY set has a member currently pressed."""
    if not combo:
        return []
    tokens: list[set[int]] = []
    for part in str(combo).split("+"):
        name = part.strip().strip("<>").lower()
        if not name:
            continue
        sig = _NAME_TO_VK.get(name)
        if sig is None and name in _CHAR_VK:
            sig = {_CHAR_VK[name]}
        if sig:
            tokens.append(set(sig))
    return tokens


def _safe(fn: Optional[Callable[[], None]]) -> None:
    if fn is None:
        return
    try:
        fn()
    except Exception:
        # A transcription/inject error must never tear the key tap down.
        pass


class _Hotkeys:
    """Pure press/release state machine — no Quartz, so it's unit-testable.

    `feed(vk, down)` drives on_start / on_stop / on_relearn exactly like the
    pynput HotkeyListener, but keyed on Quartz virtual keycodes.
    """

    def __init__(self, expected: list[set[int]], mode: str,
                 on_start: Callable[[], None], on_stop: Callable[[], None],
                 relearn: Optional[list[set[int]]] = None,
                 on_relearn: Optional[Callable[[], None]] = None):
        self.expected = expected
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop
        self.relearn = relearn or None
        self.on_relearn = on_relearn
        self._pressed: set[int] = set()
        self._active = False        # is dictation currently capturing?
        self._combo_down = False    # toggle-mode debounce (fire once per press)
        self._relearn_armed = True  # relearn debounce

    def _satisfied(self, tokens: Optional[list[set[int]]]) -> bool:
        return bool(tokens) and all(s & self._pressed for s in tokens)

    def feed(self, vk: int, down: bool) -> None:
        if down:
            self._pressed.add(vk)
        else:
            self._pressed.discard(vk)
        self._evaluate()

    def _evaluate(self) -> None:
        sat = self._satisfied(self.expected)
        if self.mode == "hold":
            if sat and not self._active:
                self._active = True
                _safe(self.on_start)
            elif not sat and self._active:
                self._active = False
                _safe(self.on_stop)
        else:  # toggle: each full press flips state, once
            if sat and not self._combo_down:
                self._combo_down = True
                if self._active:
                    self._active = False
                    _safe(self.on_stop)
                else:
                    self._active = True
                    _safe(self.on_start)
            elif not sat:
                self._combo_down = False

        if self.relearn:
            rsat = self._satisfied(self.relearn)
            if rsat and self._relearn_armed:
                self._relearn_armed = False
                _safe(self.on_relearn)
            elif not rsat:
                self._relearn_armed = True


class MacTap:
    """Quartz glue: an event tap on the main run loop feeding a `_Hotkeys`."""

    def __init__(self, machine: _Hotkeys):
        self.machine = machine
        self.ok = False
        self.error: Optional[str] = None
        self._tap = None
        self._source = None
        self._cb = None  # strong ref so pyobjc doesn't collect the callback

    def _handle(self, _proxy, etype, event, _refcon):
        try:
            import Quartz

            if etype in (Quartz.kCGEventTapDisabledByTimeout,
                         Quartz.kCGEventTapDisabledByUserInput):
                if self._tap is not None:  # the OS paused us — turn it back on
                    Quartz.CGEventTapEnable(self._tap, True)
                return event
            vk = int(Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode))
            if etype == Quartz.kCGEventFlagsChanged:
                mask = _MOD_MASK.get(vk)
                flags = Quartz.CGEventGetFlags(event)
                self.machine.feed(vk, bool(mask and (flags & mask)))
            elif etype == Quartz.kCGEventKeyDown:
                self.machine.feed(vk, True)
            elif etype == Quartz.kCGEventKeyUp:
                self.machine.feed(vk, False)
        except Exception:
            pass
        return event  # listen-only: returning the event is a no-op, but required

    def start(self) -> "MacTap":
        try:
            import Quartz
        except Exception as e:  # pragma: no cover - macOS only
            self.error = f"Quartz unavailable: {e}"
            return self
        if not self.machine.expected:
            self.error = "hotkey combo not recognized for the macOS key tap"
            return self
        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
                | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
                | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged))
        self._cb = self._handle
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,        # session-wide keystrokes
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,  # observe only; never swallow keys
            mask, self._cb, None)
        if not tap:
            # CGEventTapCreate returns NULL when the process lacks the grant.
            self.error = ("couldn't create the keyboard tap — grant Yap "
                          "Accessibility AND Input Monitoring, then reopen Yap")
            return self
        self._tap = tap
        self._source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        # Attach to the MAIN run loop → the callback fires on the main thread,
        # which is the rule macOS 26 enforces for a UI app touching TIS.
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetMain(), self._source,
                                  Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self.ok = True
        return self

    def stop(self) -> None:
        try:
            import Quartz

            if self._tap is not None:
                Quartz.CGEventTapEnable(self._tap, False)
            if self._source is not None:
                Quartz.CFRunLoopRemoveSource(Quartz.CFRunLoopGetMain(),
                                             self._source,
                                             Quartz.kCFRunLoopCommonModes)
        except Exception:
            pass


def start(cfg: dict, on_start: Callable[[], None], on_stop: Callable[[], None],
          on_relearn: Optional[Callable[[], None]] = None) -> MacTap:
    """Build and install a main-thread key tap from the loaded config. Call on the
    MAIN thread (e.g. in the rumps App's __init__). Returns the MacTap; check
    `.ok` — if False, `.error` says why (almost always: permission not granted)."""
    hk = cfg.get("hotkey", {}) or {}
    combo = hk.get("combo", "<alt_r>")
    mode = hk.get("mode", "hold")
    expected = parse_combo(combo)
    relearn = parse_combo(hk.get("relearn")) if hk.get("relearn") else None
    machine = _Hotkeys(expected, mode, on_start, on_stop, relearn, on_relearn)
    return MacTap(machine).start()
