"""The macOS main-thread key tap: combo parsing + the press/release state machine.

The Quartz glue (MacTap) only runs on macOS, but its decision logic lives in the
Quartz-free `_Hotkeys` / `parse_combo`, so we can prove off a Mac that the right
keycodes fire on_start/on_stop/relearn — which is the whole point of moving
capture in-process.

Run:  python -m pytest tests/test_mac_tap.py  (or: python tests/test_mac_tap.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yap.mac_tap import _Hotkeys, parse_combo

# Quartz virtual keycodes used below: Right Option 61, Left Option 58,
# Right Control 62, Left Command 55, Left Shift 56, D 2, F9 101.


def test_parse_combo_default_right_option():
    assert parse_combo("<alt_r>") == [{61}]


def test_parse_combo_generic_modifier_matches_either_side():
    assert parse_combo("<alt>") == [{58, 61}]


def test_parse_combo_multikey_and_letters():
    assert parse_combo("<cmd>+<shift>+d") == [{54, 55}, {56, 60}, {2}]
    assert parse_combo("<f9>") == [{101}]


def test_parse_combo_empty():
    assert parse_combo("") == []
    assert parse_combo(None) == []


def _machine(combo="<alt_r>", mode="hold", **kw):
    events = []
    hk = _Hotkeys(parse_combo(combo), mode,
                  on_start=lambda: events.append("start"),
                  on_stop=lambda: events.append("stop"),
                  on_relearn=lambda: events.append("relearn"),
                  relearn=parse_combo(kw.get("relearn")) if kw.get("relearn") else None)
    return hk, events


def test_hold_fires_on_press_and_release():
    hk, events = _machine("<alt_r>", "hold")
    hk.feed(61, True)
    assert events == ["start"]
    hk.feed(61, False)
    assert events == ["start", "stop"]


def test_hold_ignores_wrong_key():
    hk, events = _machine("<alt_r>", "hold")
    hk.feed(58, True)   # Left Option — not the bound key
    hk.feed(58, False)
    assert events == []


def test_hold_generic_modifier_either_side():
    hk, events = _machine("<alt>", "hold")
    hk.feed(58, True); hk.feed(58, False)   # left works
    hk.feed(61, True); hk.feed(61, False)   # right works
    assert events == ["start", "stop", "start", "stop"]


def test_hold_multikey_needs_all():
    hk, events = _machine("<ctrl_r>+<alt_r>", "hold")
    hk.feed(62, True)            # only control so far
    assert events == []
    hk.feed(61, True)           # now both → start
    assert events == ["start"]
    hk.feed(61, False)          # release one → stop
    assert events == ["start", "stop"]


def test_hold_repeat_keydown_does_not_restart():
    hk, events = _machine("<alt_r>", "hold")
    hk.feed(61, True)
    hk.feed(61, True)   # key-repeat: must NOT fire a second start
    assert events == ["start"]


def test_toggle_flips_each_full_press():
    hk, events = _machine("<f9>", "toggle")
    hk.feed(101, True); hk.feed(101, False)   # press 1 → start
    hk.feed(101, True); hk.feed(101, False)   # press 2 → stop
    assert events == ["start", "stop"]


def test_relearn_fires_once_per_press_and_rearms():
    hk, events = _machine("<alt_r>", "hold", relearn="<ctrl_l>+<cmd_l>")
    hk.feed(59, True)            # left control
    hk.feed(55, True)           # left command → relearn fires once
    hk.feed(55, True)           # still held → must NOT refire
    assert events == ["relearn"]
    hk.feed(55, False); hk.feed(59, False)  # release → re-arm
    hk.feed(59, True); hk.feed(55, True)    # again → fires again
    assert events == ["relearn", "relearn"]


def test_callback_exception_never_escapes():
    hk = _Hotkeys(parse_combo("<alt_r>"), "hold",
                  on_start=lambda: 1 / 0, on_stop=lambda: None)
    hk.feed(61, True)   # raising on_start must be swallowed, tap stays alive
    hk.feed(61, False)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
