"""Local, offline STT using faster-whisper (CTranslate2).

Runs entirely on your machine. No audio ever leaves the device.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np


def _resolve_device(device: str) -> tuple[str, str]:
    """Return (device, default_compute_type) honoring 'auto'."""
    if device != "auto":
        return device, ("float16" if device == "cuda" else "int8")
    try:
        import ctranslate2  # bundled with faster-whisper

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


class LocalWhisperEngine:
    name = "local"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self._model = None  # lazy: don't pay load cost until first use

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        device, default_ct = _resolve_device(self.cfg.get("device", "auto"))
        compute_type = self.cfg.get("compute_type", "auto")
        if compute_type == "auto":
            compute_type = default_ct
        self._model = WhisperModel(
            self.cfg.get("model", "base.en"),
            device=device,
            compute_type=compute_type,
        )
        return self._model

    def warmup(self) -> None:
        self._ensure_model()

    def _decode(self, audio) -> str:
        model = self._ensure_model()
        language: Optional[str] = self.cfg.get("language")
        segments, _info = model.transcribe(
            audio,
            language=language,
            beam_size=int(self.cfg.get("beam_size", 1)),
            vad_filter=True,  # trim leading/trailing silence -> faster, cleaner
        )
        return "".join(seg.text for seg in segments).strip()

    def transcribe_file(self, wav_path: str) -> str:
        return self._decode(wav_path)

    def transcribe_array(self, samples: "np.ndarray", samplerate: int) -> str:
        # faster-whisper expects mono float32 at 16 kHz.
        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samplerate != 16000:
            audio = _resample_to_16k(audio, samplerate)
        return self._decode(audio)


def _resample_to_16k(audio: "np.ndarray", sr: int) -> "np.ndarray":
    """Lightweight linear resample to 16 kHz (no scipy dependency)."""
    if sr == 16000:
        return audio
    duration = audio.shape[0] / float(sr)
    n_out = int(round(duration * 16000))
    if n_out <= 0:
        return audio
    x_old = np.linspace(0.0, duration, num=audio.shape[0], endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)
