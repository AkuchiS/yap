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


def _resample(audio: "np.ndarray", src_sr: int, dst_sr: int) -> "np.ndarray":
    """Lightweight linear resample (no scipy). src_sr -> dst_sr."""
    if src_sr == dst_sr or audio.size == 0:
        return audio.astype(np.float32)
    duration = audio.shape[0] / float(src_sr)
    n_out = int(round(duration * dst_sr))
    if n_out <= 0:
        return audio[:0].astype(np.float32)
    x_old = np.linspace(0.0, duration, num=audio.shape[0], endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class Recorder:
    def __init__(self, cfg: dict[str, Any]):
        self.target_sr = int(cfg.get("samplerate", 16000))
        self.capture_sr = cfg.get("capture_samplerate")  # None/0 = native rate
        self.channels = int(cfg.get("channels", 1))
        self.device = cfg.get("device")  # int, name substring, list, or None
        self.max_seconds = float(cfg.get("max_seconds", 120))

    def _resolve_device(self):
        return resolve_device(self.device)

    def _pick_capture_sr(self, device) -> int:
        """The rate to actually open the mic at. Many external-display/dock mics
        only run at 48 kHz, so forcing 16 kHz makes them open but deliver nothing —
        capture at the device's native rate and resample afterwards."""
        if self.capture_sr:
            return int(self.capture_sr)
        import sounddevice as sd

        try:
            info = (sd.query_devices(device, "input") if device is not None
                    else sd.query_devices(kind="input"))
            sr = int(round(info.get("default_samplerate") or 0))
            return sr if sr > 0 else self.target_sr
        except Exception:
            return self.target_sr

    def record_until(self, stop: threading.Event) -> Optional["np.ndarray"]:
        """Block until `stop` is set (or max_seconds elapses). Return mono float32
        at `target_sr`. Returns None — with a clear reason on stderr — if the mic
        can't be opened or delivers no audio."""
        import sounddevice as sd

        device = self._resolve_device()
        capture_sr = self._pick_capture_sr(device)
        q: "queue.Queue[np.ndarray]" = queue.Queue()

        def callback(indata, _frames, _time, status):
            if status:
                print(f"yap: audio status: {status}", file=sys.stderr)
            q.put(indata.copy())

        chunks: list[np.ndarray] = []
        max_frames = int(self.max_seconds * capture_sr)
        total = 0
        try:
            stream = sd.InputStream(
                samplerate=capture_sr,
                channels=self.channels,
                dtype="float32",
                device=device,
                callback=callback,
            )
        except Exception as e:
            print(f"yap: couldn't open mic (device={device!r} @ {capture_sr} Hz): {e}\n"
                  f"     run `yap devices`, then pin one: "
                  f"yap config set audio.device '\"<name>\"'", file=sys.stderr)
            return None
        with stream:
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
            print(f"yap: mic opened (device={device!r} @ {capture_sr} Hz) but no audio "
                  f"arrived — is the right input selected? run `yap devices`.", file=sys.stderr)
            return None
        audio = np.concatenate(chunks, axis=0)
        if audio.ndim > 1:  # downmix to mono
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak < 1e-4:  # frames arrived but flat-line → wrong/muted mic
            print(f"yap: captured audio is silent (peak={peak:.1e}) — the selected mic may "
                  f"be muted or wrong; run `yap devices`.", file=sys.stderr)
        return _resample(audio, capture_sr, self.target_sr)


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
