"""`yap doctor` — diagnose the things that actually break dictation:
permissions (macOS trust), whether the hotkey is seen, mic capture, clipboard.

This is the first thing to run when "nothing happens". It needs no GUI focus —
just run it and follow the prints.
"""

from __future__ import annotations

import platform
import sys
import time
from typing import Any


def _hr(title: str) -> None:
    print(f"\n=== {title} ===")


def check_trust(prompt: bool = False):
    """On macOS, report whether THIS process is trusted for input monitoring.

    Returns True/False, or None on non-mac / when the check can't run.
    With prompt=True, macOS shows the 'allow control' dialog and adds the app
    to the Accessibility list (toggle still has to be switched on by you).
    """
    if sys.platform != "darwin":
        print("  (not macOS — no Accessibility gate; skipping)")
        return None
    try:
        try:
            from ApplicationServices import (  # type: ignore
                AXIsProcessTrusted,
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
        except Exception:
            from HIServices import (  # type: ignore
                AXIsProcessTrusted,
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
    except Exception as e:
        print(f"  could not load the macOS trust API ({e}); pyobjc missing?")
        return None
    if prompt:
        trusted = bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    else:
        trusted = bool(AXIsProcessTrusted())
    if trusted:
        print("  ✓ TRUSTED — this process may monitor input and synthesize keys.")
    else:
        print("  ✗ NOT TRUSTED — macOS is blocking key monitoring for this process.")
        print("    Whatever app is shown below must be ON in BOTH")
        print("    Privacy & Security → Accessibility AND → Input Monitoring,")
        print("    then FULLY QUIT (Cmd+Q) and reopen that app.")
    return trusted


def keytest(cfg: dict[str, Any], seconds: int = 12) -> None:
    try:
        from pynput import keyboard
    except Exception as e:
        print(f"  ✗ pynput unavailable ({e}); install it: pip install pynput")
        return

    from .hotkey import key_sig, parse_combo_sigs

    combo = cfg["hotkey"]["combo"]
    try:
        expected = parse_combo_sigs(combo)
    except Exception as e:
        print(f"  could not parse hotkey {combo!r}: {e}")
        return
    pressed: set = set()
    seen = {"any": False}
    listener = {"l": None}

    def sigs(k):
        out = {key_sig(k)}
        try:
            out.add(key_sig(listener["l"].canonical(k)))
        except Exception:
            pass
        return out

    def on_press(k):
        seen["any"] = True
        s = sigs(k)
        pressed.update(s)
        print(f"  press    {str(k):22} sigs={sorted(s)}")
        if expected.issubset(pressed):
            print("  ✓✓ HOTKEY MATCH — in `yap run`, recording would START here.")

    def on_release(k):
        s = sigs(k)
        print(f"  release  {str(k):22} sigs={sorted(s)}")
        pressed.difference_update(s)

    print(f"  hotkey = {combo!r}   (expecting sigs: {expected})")
    print(f"  Watching for {seconds}s — press some keys, then HOLD your hotkey…")
    listener["l"] = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener["l"].start()
    time.sleep(seconds)
    listener["l"].stop()
    if not seen["any"]:
        print("  ✗ Saw NO key events at all → this is a trust/permission problem,")
        print("    not a key-choice problem. Fix Accessibility + Input Monitoring above.")
    else:
        print("  (If you saw your hotkey above but no MATCH line, the combo is wrong —")
        print("   copy the 'canonical=' value into hotkey.combo.)")


def mictest(cfg: dict[str, Any]) -> None:
    try:
        import numpy as np
        import sounddevice as sd
    except Exception as e:
        print(f"  ✗ audio libs unavailable: {e}")
        return
    sr = int(cfg["audio"].get("samplerate", 16000))
    try:
        print("  recording 0.8s — say something…")
        rec = sd.rec(int(0.8 * sr), samplerate=sr, channels=1, dtype="float32")
        sd.wait()
        peak = float(abs(rec).max())
        if peak < 1e-4:
            print(f"  ⚠ captured silence (peak {peak:.5f}) — mic permission, muted, or "
                  "wrong input device. Run `yap devices`.")
        else:
            print(f"  ✓ mic OK — peak amplitude {peak:.3f}")
    except Exception as e:
        print(f"  ✗ mic FAILED: {e}")


def cliptest() -> None:
    from .inject import clipboard_get, clipboard_set

    if clipboard_set("yap-doctor-probe"):
        got = clipboard_get()
        ok = (got == "yap-doctor-probe")
        print(f"  {'✓' if ok else '⚠'} clipboard set/get {'OK' if ok else f'mismatch: {got!r}'}")
    else:
        print("  ⚠ clipboard set failed — install pyperclip or xclip/wl-clipboard.")


def run(cfg: dict[str, Any], prompt: bool, seconds: int) -> int:
    print(f"yap doctor — {platform.platform()}")
    print(f"  python : {sys.executable}")
    print(f"  engine : {cfg.get('engine')}   hotkey: {cfg['hotkey']['combo']} "
          f"({cfg['hotkey']['mode']})")

    _hr("1. Accessibility / Input-Monitoring trust (macOS)")
    check_trust(prompt=prompt)

    _hr("2. Hotkey capture")
    keytest(cfg, seconds=seconds)

    _hr("3. Microphone")
    mictest(cfg)

    _hr("4. Clipboard")
    cliptest()

    print("\nDone. The #1 fix when section 2 saw no keys: add the app you ran this")
    print("from to Accessibility AND Input Monitoring, then Cmd+Q and reopen it.")
    print("Tip: `yap doctor --prompt` pops the macOS 'allow control' dialog for you.")
    return 0
