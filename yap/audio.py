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


def _match_substring(name_sub: str):
    """First input device whose name contains `name_sub` (case-insensitive), or None."""
    import sounddevice as sd

    name_sub = str(name_sub).lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name_sub in dev["name"].lower():
            return idx
    return None


def _resolve_one(entry):
    """Resolve a single spec entry to an index, quietly (None if not found)."""
    if entry is None or entry == "":
        return None
    if isinstance(entry, int):
        return entry
    return _match_substring(entry)


def resolve_device(spec):
    """Resolve an input-device spec to a PortAudio index (None = system default).

    `spec` may be:
      * None / ""          -> system default mic
      * an int             -> that device index
      * a name substring   -> first input device whose name contains it
      * a list of the above -> tried in order, first match wins. Ideal for a laptop
        that docks to external displays: list your built-in mic first and the
        dock/display mic as a fallback, e.g.
        ["MacBook Pro Microphone", "Studio Display"]. Re-evaluated on every
        recording, so it adapts as you plug/unplug without losing your mic to
        whatever macOS just made the default.
    """
    if isinstance(spec, (list, tuple)):
        for entry in spec:
            idx = _resolve_one(entry)
            if idx is not None:
                return idx
        print(f"yap: none of input devices {list(spec)!r} found; using default mic.",
              file=sys.stderr)
        return None
    idx = _resolve_one(spec)
    if idx is None and spec not in (None, ""):
        print(f"yap: input device {spec!r} not found; using default mic.", file=sys.stderr)
    return idx


class Recorder:
    def __init__(self, cfg: dict[str, Any]):
        self.samplerate = int(cfg.get("samplerate", 16000))
        self.channels = int(cfg.get("channels", 1))
        self.device = cfg.get("device")  # int index, name substring, or None
        self.max_seconds = float(cfg.get("max_seconds", 120))

    def _resolve_device(self):
        return resolve_device(self.device)

    def record_until(self, stop: threading.Event) -> Optional["np.ndarray"]:
        """Block until `stop` is set (or max_seconds elapses). Return mono float32."""
        import sounddevice as sd

        q: "queue.Queue[np.ndarray]" = queue.Queue()

        def callback(indata, _frames, _time, status):
            if status:
                print(f"yap: audio status: {status}", file=sys.stderr)
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
                    print("yap: hit max recording length; stopping.", file=sys.stderr)
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


def list_devices(cfg: "dict | None" = None) -> str:
    """Human-readable list of input devices (for `yap devices`).

    Pass the loaded config to also show which mic yap will actually use given
    your `audio.device` setting — handy when external displays add extra mics.
    """
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

    spec = (cfg.get("audio") or {}).get("device") if cfg else None
    lines.append("")
    if spec in (None, "", [], ()):
        lines.append("yap will use: the system default mic.")
        lines.append("Pin one (or a fallback list) so docking doesn't steal your mic:")
        lines.append("  yap config set audio.device '\"MacBook Pro Microphone\"'")
        lines.append("  yap config set audio.device '[\"MacBook Pro Microphone\", \"Studio Display\"]'")
    else:
        idx = resolve_device(spec)
        if idx is None:
            lines.append(f"yap will use: system default (configured {spec!r} not present).")
        else:
            name = sd.query_devices()[idx]["name"]
            lines.append(f"yap will use: {idx}: {name}  (configured: {spec!r})")
    return "\n".join(lines)
