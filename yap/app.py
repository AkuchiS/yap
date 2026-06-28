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
from .text import apply_replacements, build_prompt

_LEVELS = {"quiet": 0, "normal": 1, "debug": 2}


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

        self._stop_event = threading.Event()
        self._record_thread: Optional[threading.Thread] = None
        self._audio: Optional[np.ndarray] = None
        self._busy = threading.Lock()  # don't start while still transcribing

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
        # tell other voice apps: pause — and remember which app we're dictating into
        self._active_app = self.integration.record_started()
        self._status("listening")
        app_note = f" → {self._active_app}" if self._active_app else ""
        self._log(f"● listening…{app_note}", 1)

    def on_stop(self):
        self._stop_event.set()
        self._status("transcribing")
        self._log("◼ processing…", 2)
        # process off the hotkey thread so the listener stays responsive
        threading.Thread(target=self._finish, daemon=True).start()

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
            try:
                self.engine.prompt = build_prompt(
                    list(eff.get("vocabulary", [])) + self.learner.words())
            except Exception:
                pass
            t0 = time.time()
            text = self.engine.transcribe_array(audio, self.samplerate)
            text = cleanup.maybe_clean(text, eff)
            text = apply_replacements(text, eff.get("replacements"))
            dt = time.time() - t0
            if not text:
                self._log("… no speech detected — try speaking louder/closer", 1)
                return
            self._log(f'✓ "{text}"', 1)
            self._log(f"  ({secs:.1f}s audio, {dt:.1f}s transcribe)", 2)
            self.injector.inject(text)
            self._log("… injected at cursor", 2)
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
    def start_background(self):
        """Warm up and start the hotkey listener without blocking.

        Returns the listener. Used by GUIs (the menu-bar app) that own the main
        loop themselves. Call listener.stop() to shut down.
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
        return HotkeyListener(combo, mode, self.on_start, self.on_stop).start()

    def run(self):
        combo = self.cfg["hotkey"]["combo"]
        mode = self.cfg["hotkey"]["mode"]

        self._log(f"yap {_version()} — engine: {self.engine.name}", 1)
        self._log(describe_mode(mode, combo), 1)
        self._log("Warming up model…", 1)
        listener = self.start_background()
        self._log("Ready. (Ctrl+C to quit)\n", 1)
        try:
            listener.join()
        except KeyboardInterrupt:
            self._log("\nyap: bye.", 1)
        finally:
            listener.stop()


def _version() -> str:
    from . import __version__

    return __version__
