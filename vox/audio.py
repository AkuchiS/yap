"""Microphone capture via sounddevice (PortAudio).

Records mono float32 frames into a queue while a threading.Event stays set,
so the daemon can start on hotkey-down and stop on hotkey-up (or toggle).
"""

from __future__ import annotations

import queue
import sys
import threading
from typing import Any, Optional

import numpy as np


class Recorder:
    def __init__(self, cfg: dict[str, Any]):
        self.samplerate = int(cfg.get("samplerate", 16000))
        self.channels = int(cfg.get("channels", 1))
        self.device = cfg.get("device")  # int index, name substring, or None
        self.max_seconds = float(cfg.get("max_seconds", 120))

    def _resolve_device(self):
        if self.device is None or self.device == "":
            return None
        if isinstance(self.device, int):
            return self.device
        # match by name substring (case-insensitive)
        import sounddevice as sd

        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and str(self.device).lower() in dev["name"].lower():
                return idx
        print(f"vox: input device {self.device!r} not found; using default.", file=sys.stderr)
        return None

    def record_until(self, stop: threading.Event) -> Optional["np.ndarray"]:
        """Block until `stop` is set (or max_seconds elapses). Return mono float32."""
        import sounddevice as sd

        q: "queue.Queue[np.ndarray]" = queue.Queue()

        def callback(indata, _frames, _time, status):
            if status:
                print(f"vox: audio status: {status}", file=sys.stderr)
            q.put(indata.copy())

        chunks: list[np.ndarray] = []
        max_frames = int(self.max_seconds * self.samplerate)
        total = 0
        with sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            device=self._resolve_device(),
            callback=callback,
        ):
            while not stop.is_set():
                try:
                    chunk = q.get(timeout=0.1)
                except queue.Empty:
                    continue
                chunks.append(chunk)
                total += chunk.shape[0]
                if total >= max_frames:
                    print("vox: hit max recording length; stopping.", file=sys.stderr)
                    break
        # drain anything still queued
        while True:
            try:
                chunks.append(q.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return None
        audio = np.concatenate(chunks, axis=0)
        if audio.ndim > 1:  # downmix to mono
            audio = audio.mean(axis=1)
        return audio.astype(np.float32)


def list_devices() -> str:
    """Human-readable list of input devices (for `vox devices`)."""
    try:
        import sounddevice as sd
    except Exception as e:  # pragma: no cover - depends on host
        return f"sounddevice unavailable: {e}"
    lines = ["Input devices (index: name):"]
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            mark = "  <- default" if idx == default_in else ""
            lines.append(f"  {idx}: {dev['name']} ({dev['max_input_channels']} ch){mark}")
    return "\n".join(lines)
