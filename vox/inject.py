"""Cross-platform text injection at the cursor.

Two strategies:
  * "paste" (default): put text on the clipboard, then send Cmd/Ctrl+V.
    Fast and reliable across apps; optionally restores your prior clipboard.
  * "type": synthesize the keystrokes directly (no clipboard touch). Slower
    and can miss in some apps, but never clobbers your clipboard.

Clipboard access prefers `pyperclip`; falls back to native CLIs
(pbcopy/pbpaste on macOS, wl-copy/xclip on Linux, clip on Windows).
Keystrokes are sent with pynput.
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any, Optional


# ---------------------------------------------------------------- clipboard ---
def _native_copy(text: str) -> bool:
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        if sys.platform.startswith("win") or sys.platform == "cygwin":
            subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
            return True
        # Linux/BSD: try Wayland then X11
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True)
                return True
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    except Exception:
        return False
    return False


def _native_paste_read() -> Optional[str]:
    try:
        if sys.platform == "darwin":
            return subprocess.run(["pbpaste"], capture_output=True, check=True).stdout.decode()
        for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]):
            try:
                return subprocess.run(cmd, capture_output=True, check=True).stdout.decode()
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    except Exception:
        return None
    return None


def clipboard_set(text: str) -> bool:
    try:
        import pyperclip

        pyperclip.copy(text)
        return True
    except Exception:
        return _native_copy(text)


def clipboard_get() -> Optional[str]:
    try:
        import pyperclip

        return pyperclip.paste()
    except Exception:
        return _native_paste_read()


# ---------------------------------------------------------------- keystrokes --
def _paste_hotkey(kb) -> None:
    from pynput.keyboard import Key

    mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with kb.pressed(mod):
        kb.press("v")
        kb.release("v")


class Injector:
    def __init__(self, cfg: dict[str, Any]):
        self.method = cfg.get("method", "paste")
        self.restore_clipboard = bool(cfg.get("restore_clipboard", True))
        self.trailing_space = bool(cfg.get("trailing_space", True))
        self._kb = None

    def _keyboard(self):
        if self._kb is None:
            from pynput.keyboard import Controller

            self._kb = Controller()
        return self._kb

    def inject(self, text: str) -> None:
        if not text:
            return
        if self.trailing_space and not text.endswith((" ", "\n")):
            text = text + " "
        if self.method == "type":
            self._keyboard().type(text)
            return
        self._paste(text)

    def _paste(self, text: str) -> None:
        prior = clipboard_get() if self.restore_clipboard else None
        if not clipboard_set(text):
            print("vox: clipboard unavailable; falling back to typing.", file=sys.stderr)
            self._keyboard().type(text)
            return
        time.sleep(0.02)  # let the clipboard settle before pasting
        try:
            _paste_hotkey(self._keyboard())
        except Exception as e:
            print(f"vox: paste keystroke failed ({e}); typing instead.", file=sys.stderr)
            self._keyboard().type(text)
            return
        if self.restore_clipboard and prior is not None:
            time.sleep(0.15)  # ensure the paste consumed the clipboard first
            clipboard_set(prior)
