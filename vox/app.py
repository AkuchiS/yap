"""The dictation daemon: wire hotkey -> record -> transcribe -> clean -> inject."""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Optional

import numpy as np

from . import cleanup
from .audio import Recorder
from .hotkey import HotkeyListener, combo_warning, describe_mode
from .inject import Injector
from .stt import build_engine


class App:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.engine = build_engine(cfg)
        self.recorder = Recorder(cfg["audio"])
        self.injector = Injector(cfg["inject"])
        self.samplerate = int(cfg["audio"].get("samplerate", 16000))
        self.echo = bool(cfg.get("echo", True))

        self._stop_event = threading.Event()
        self._record_thread: Optional[threading.Thread] = None
        self._audio: Optional[np.ndarray] = None
        self._busy = threading.Lock()  # don't start while still transcribing

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
        self._log("● recording… (speak now, release to transcribe)")

    def on_stop(self):
        self._stop_event.set()
        self._log("◼ stopped — processing…")
        # process off the hotkey thread so the listener stays responsive
        threading.Thread(target=self._finish, daemon=True).start()

    def _log(self, msg: str) -> None:
        # flush so stage markers appear immediately, even through a pipe
        print(msg, file=sys.stderr, flush=True)

    def _finish(self):
        try:
            if self._record_thread is not None:
                self._record_thread.join()
            audio = self._audio
            if audio is None:
                self._log("… no audio captured (mic blocked or device busy?)")
                return
            secs = audio.shape[0] / self.samplerate
            if audio.shape[0] < self.samplerate * 0.2:
                self._log(f"… too short ({secs:.2f}s), ignored")
                return
            self._log(f"… transcribing {secs:.1f}s of audio…")
            t0 = time.time()
            text = self.engine.transcribe_array(audio, self.samplerate)
            text = cleanup.maybe_clean(text, self.cfg)
            dt = time.time() - t0
            if not text:
                self._log(f"… no speech detected ({dt:.1f}s stt) — try speaking louder/closer")
                return
            self._log(f'✓ [{secs:.1f}s audio, {dt:.1f}s stt] "{text}"')
            self._log("… injecting text at cursor…")
            self.injector.inject(text)
            self._log("✓ done")
        except Exception as e:
            import traceback

            self._log(f"vox: error during transcription: {e}")
            traceback.print_exc()
        finally:
            self._busy.release()

    # ---- lifecycle ----------------------------------------------------------
    def run(self):
        combo = self.cfg["hotkey"]["combo"]
        mode = self.cfg["hotkey"]["mode"]

        print(f"vox {_version()} — engine: {self.engine.name}", file=sys.stderr)
        warn = combo_warning(combo)
        if warn:
            print(f"vox: warning: {warn}", file=sys.stderr)
        print(describe_mode(mode, combo), file=sys.stderr)
        print("Warming up model…", file=sys.stderr)
        try:
            self.engine.warmup()
        except Exception as e:
            print(f"vox: warmup failed: {e}", file=sys.stderr)
        print("Ready. (Ctrl+C to quit)\n", file=sys.stderr)

        listener = HotkeyListener(combo, mode, self.on_start, self.on_stop).start()
        try:
            listener.join()
        except KeyboardInterrupt:
            print("\nvox: bye.", file=sys.stderr)
        finally:
            listener.stop()


def _version() -> str:
    from . import __version__

    return __version__
