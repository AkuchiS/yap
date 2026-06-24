"""STT engine interface."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class Engine(Protocol):
    """A speech-to-text engine.

    Implementations accept either a path to a 16-bit/float WAV file or a mono
    float32 numpy array of samples, and return the recognized text.
    """

    name: str

    def transcribe_file(self, wav_path: str) -> str:
        ...

    def transcribe_array(self, samples: "np.ndarray", samplerate: int) -> str:
        ...

    def warmup(self) -> None:
        """Optionally pre-load models so the first real transcription is fast."""
        ...
