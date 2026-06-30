"""The dictation daemon: wire hotkey -> record -> transcribe -> clean -> inject."""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Optional

import numpy as np

from . import cleanup, config
from .audio import Recorder
from .hotkey import HotkeyListener, combo_warning, describe_mode
from .inject import Injector
from .integration import Integration
from .learn import VocabLearner
from .stt import build_engine
from .text import apply_replacements, build_prompt, normalize_case

_LEVELS = {"quiet": 0, "normal": 1, "debug": 2}

_WAYLAND_HELP = (
    "yap: Wayland session detected — the OS blocks apps from grabbing global\n"
    "     hotkeys, so the key listener won't fire in Wayland windows (no choice of\n"
    "     key fixes this). Bind a key in your compositor to drive yap instead:\n"
    "       Hyprland :  bind = SUPER, D, exec, yap toggle\n"
    "       GNOME/KDE:  add a custom shortcut that runs:  yap toggle\n"
    "     The control socket is up now, so `yap toggle` works while this runs."
)


class App:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.engine = build_engine(cfg)
        self.recorder = Recorder(cfg["audio"])
        self.injector = Injector(cfg["inject"])
        self.integration = Integration(cfg)
        self.learner = VocabLearner(cfg)
        self._refresh_prompt()  # fold any already-learned words into the glossary
        self.samplerate = int(cfg["audio"].get("samplerate", 16000))
        self.verbosity = _LEVELS.get(cfg.get("verbosity", "normal"), 1)
        # Optional callback for a GUI (menu-bar app) to reflect state:
        # called with "idle" | "listening" | "transcribing".
        self.status_cb = None
        # Optional GUI notifier for one-off messages (e.g. "Learned: DIME").
        self.notify_cb = None

        self._stop_event = threading.Event()
        self._record_thread: Optional[threading.Thread] = None
        self._audio: Optional[np.ndarray] = None
        self._busy = threading.Lock()  # don't start while still transcribing
        self._last_injection = ""      # what we last typed (for `relearn`)
        self._relearn_listener = None
        self._recording = False        # is dictation currently capturing? (for toggle)
        self._ipc = None               # control socket (Wayland keybind / scripts)

    def _status(self, state: str) -> None:
        if self.status_cb:
            try:
                self.status_cb(state)
            except Exception:
                pass

    def _refresh_prompt(self) -> None:
        """Rebuild the Whisper biasing prompt from manual + auto-learned words."""
        words = list(self.cfg.get("vocabulary", [])) + self.learner.words()
        try:
            self.engine.prompt = build_prompt(words)
        except Exception:
            pass

    def _notify(self, msg: str) -> None:
        """One-off message to the user — via the GUI notifier if set, else the log."""
        if self.notify_cb:
            try:
                self.notify_cb(msg)
                return
            except Exception:
                pass
        self._log(msg, 1)

    def _said(self, msg: str) -> str:
        self._notify(msg)
        return msg

    def on_relearn(self) -> str:
        """Learn from your last correction: diff the clipboard (your fixed text)
        against what yap last typed, save the changes, and hot-apply (no restart).
        Triggered by the relearn hotkey or the menu-bar / tray item."""
        from .inject import clipboard_get
        from .learn import diff_corrections

        last = (getattr(self, "_last_injection", "") or "").strip()
        if not last:
            return self._said("Nothing to relearn yet — dictate something first.")
        corrected = (clipboard_get() or "").strip()
        if not corrected or corrected == last:
            return self._said("Copy your corrected text first, then trigger relearn.")
        fixes, casings = diff_corrections(last, corrected)
        if not fixes and not casings:
            return self._said("No clear correction spotted between them.")
        cfg = config.load()
        cfg.setdefault("replacements", {}).update(fixes)
        vocab = cfg.setdefault("vocabulary", [])
        for c in casings:
            if c not in vocab:
                vocab.append(c)
        config.save(cfg)
        self.cfg = cfg  # hot-apply: the next utterance uses it (no restart)
        try:
            self._refresh_prompt()
        except Exception:
            pass
        return self._said("Learned: " + ", ".join(list(fixes.values()) + casings))

    def stop_relearn(self) -> None:
        if self._relearn_listener is not None:
            try:
                self._relearn_listener.stop()
            except Exception:
                pass

    # ---- hotkey callbacks ---------------------------------------------------
    def on_start(self):
        if not self._busy.acquire(blocking=False):
            return  # previous transcription still running; ignore
        self._stop_event.clear()
        self._audio = None

        def _rec():
            self._audio = self.recorder.record_until(self._stop_event)

        self._record_thread = threading.Thread(target=_rec, daemon=True)
        self._record_thread.start()
        self._recording = True
        # tell other voice apps: pause — and remember which app we're dictating into
        self._active_app = self.integration.record_started()
        self._status("listening")
        app_note = f" → {self._active_app}" if self._active_app else ""
        self._log(f"● listening…{app_note}", 1)

    def on_stop(self):
        self._recording = False
        self._stop_event.set()
        self._status("transcribing")
        self._log("◼ processing…", 2)
        # process off the hotkey thread so the listener stays responsive
        threading.Thread(target=self._finish, daemon=True).start()

    def toggle(self):
        """Flip dictation on/off. The entry point for an external trigger — a
        Wayland compositor keybind (`yap toggle`), a script, a Stream Deck —
        mirroring one press of the hotkey."""
        if self._recording:
            self.on_stop()
        else:
            self.on_start()

    def _ipc_command(self, cmd: str) -> str:
        """Dispatch a control-socket command (see `yap.ipc`). Runs on the socket
        thread; on_start/on_stop are already thread-safe (the hotkey calls them off
        the main thread too)."""
        c = (cmd or "").strip().lower()
        if c in ("toggle", ""):
            self.toggle()
            return "recording" if self._recording else "idle"
        if c in ("start", "press"):
            self.on_start()
            return "recording"
        if c in ("stop", "release"):
            self.on_stop()
            return "idle"
        if c == "relearn":
            return "ok " + self.on_relearn()
        if c in ("ping", "status"):
            return "recording" if self._recording else "idle"
        return f"err: unknown command {c!r}"

    def _log(self, msg: str, level: int = 1) -> None:
        # flush so messages appear immediately, even through a pipe
        if self.verbosity >= level:
            print(msg, file=sys.stderr, flush=True)

    def _finish(self):
        try:
            if self._record_thread is not None:
                self._record_thread.join()
            audio = self._audio
            if audio is None:
                self._log("… no audio captured (mic blocked or device busy?)", 1)
                return
            secs = audio.shape[0] / self.samplerate
            if audio.shape[0] < self.samplerate * 0.2:
                self._log(f"… too short ({secs:.2f}s), ignored", 2)
                return
            self._log(f"… transcribing {secs:.1f}s…", 2)
            # per-app profile: merge the frontmost app's overrides over the base for
            # this utterance (vocabulary biasing, cleanup, replacements, language).
            eff = config.profile_for(self.cfg, getattr(self, "_active_app", None))
            vocab = list(eff.get("vocabulary", [])) + self.learner.words()
            try:
                self.engine.prompt = build_prompt(vocab)
            except Exception:
                pass
            t0 = time.time()
            text = self.engine.transcribe_array(audio, self.samplerate)
            text = cleanup.maybe_clean(text, eff)
            text = apply_replacements(text, eff.get("replacements"))
            text = normalize_case(text, vocab)  # force your vocab's casing (akuchis -> AkuchiS)
            dt = time.time() - t0
            if not text:
                self._log("… no speech detected — try speaking louder/closer", 1)
                return
            self._log(f'✓ "{text}"', 1)
            self._log(f"  ({secs:.1f}s audio, {dt:.1f}s transcribe)", 2)
            self.injector.inject(text)
            self._log("… injected at cursor", 2)
            self._last_injection = text  # in-app relearn (hotkey / menu)
            try:  # also persist so the `yap relearn` CLI can use it
                (config.config_dir() / "last_injection.txt").write_text(text, encoding="utf-8")
            except Exception:
                pass
            # learn from what you just said; fold new words into future biasing
            learned = self.learner.observe(text)
            if learned:
                self._refresh_prompt()
                self._log(f"  + learned: {', '.join(learned)}", 1)
        except Exception as e:
            self._log(f"yap: error during transcription: {e}", 0)
            if self.verbosity >= _LEVELS["debug"]:
                import traceback

                traceback.print_exc()
        finally:
            # resume other voice apps, reporting the same app we paused for
            self.integration.record_stopped(getattr(self, "_active_app", None))
            self._status("idle")
            self._busy.release()

    # ---- lifecycle ----------------------------------------------------------
    def start_background(self, use_global_hotkey: bool = True):
        """Warm up and start the hotkey listener without blocking.

        Returns the listener. Used by GUIs (the menu-bar app) that own the main
        loop themselves. Call listener.stop() to shut down.

        Set ``use_global_hotkey=False`` to warm the engine and bring up the
        control socket WITHOUT the pynput listener — the macOS menu-bar app uses
        this and drives on_start/on_stop from its own main-thread Quartz key tap
        (see ``yap/mac_tap.py``), the only listener macOS 26 trusts in-process.
        Returns None in that case (the caller owns key capture).
        """
        combo = self.cfg["hotkey"]["combo"]
        mode = self.cfg["hotkey"]["mode"]
        warn = combo_warning(combo)
        if warn:
            self._log(f"yap: warning: {warn}", 0)
        try:
            self.engine.warmup()
        except Exception as e:
            self._log(f"yap: warmup failed: {e}", 0)
        self._status("idle")
        # optional second global hotkey: learn from your last correction
        # Control socket: lets an external trigger drive dictation. Essential on
        # Wayland (global hotkeys can't be grabbed there); harmless everywhere else.
        from . import ipc
        from .hotkey import is_wayland
        self._ipc = ipc.Server(self._ipc_command).start()
        if is_wayland():
            self._log(_WAYLAND_HELP, 0)

        if not use_global_hotkey:
            return None  # caller drives on_start/on_stop (macOS Quartz key tap)

        # ONE listener handles BOTH the dictation hotkey and relearn. Never start a
        # second pynput listener — two concurrent ones abort the process on macOS
        # 26 (both touch the Text Input Source API on different threads).
        relearn = (self.cfg.get("hotkey") or {}).get("relearn")
        listener = HotkeyListener(combo, mode, self.on_start, self.on_stop,
                                  relearn_combo=relearn,
                                  on_relearn=self.on_relearn).start()
        if not listener.started and not is_wayland():
            self._log(f"yap: global hotkey listener unavailable ({listener.error}). "
                      "Bind a key to `yap toggle` to dictate.", 0)
        return listener

    def run(self):
        combo = self.cfg["hotkey"]["combo"]
        mode = self.cfg["hotkey"]["mode"]

        self._log(f"yap {_version()} — engine: {self.engine.name}", 1)
        self._log(describe_mode(mode, combo), 1)
        self._log("Warming up model…", 1)
        listener = self.start_background()
        self._log("Ready. (Ctrl+C to quit)\n", 1)
        try:
            if listener.started:
                listener.join()
            elif self._ipc is not None:
                self._ipc.join()   # no global hotkey (Wayland/no-X): stay up for `yap toggle`
            else:
                listener.join()    # nothing to wait on; returns immediately
        except KeyboardInterrupt:
            self._log("\nyap: bye.", 1)
        finally:
            listener.stop()
            if self._ipc is not None:
                self._ipc.stop()
            self.stop_relearn()


def _version() -> str:
    from . import __version__

    return __version__
