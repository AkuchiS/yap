"""Cloud STT via any OpenAI-compatible /audio/transcriptions endpoint.

Works with OpenAI, Groq, and self-hosted servers (whisper.cpp server,
faster-whisper-server, etc.) — just point `base_url` at them and set the
key env var. Bring your own key; nothing is hard-coded.

Uses only the stdlib (urllib) so cloud mode adds no extra dependency.
"""

from __future__ import annotations

import io
import os
import sys
import urllib.error
import urllib.request
import uuid
import wave
from typing import Any, Optional

import numpy as np


def _array_to_wav_bytes(samples: "np.ndarray", samplerate: int) -> bytes:
    """Encode a mono float32/-1..1 array as 16-bit PCM WAV bytes."""
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(pcm)
    return buf.getvalue()


def _multipart(fields: dict[str, str], filename: str, file_bytes: bytes) -> tuple[bytes, str]:
    """Build a multipart/form-data body (stdlib only)."""
    boundary = uuid.uuid4().hex
    nl = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            b"",
            str(value).encode(),
        ]
    parts += [
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode(),
        b"Content-Type: audio/wav",
        b"",
    ]
    body = nl.join(parts) + nl + file_bytes + nl + f"--{boundary}--".encode() + nl
    return body, f"multipart/form-data; boundary={boundary}"


class CloudWhisperEngine:
    name = "cloud"

    def __init__(self, cfg: dict[str, Any], prompt: Optional[str] = None):
        self.cfg = cfg
        self.prompt = prompt  # vocabulary biasing -> transcription "prompt" field
        self.base_url = cfg.get("base_url", "https://api.groq.com/openai/v1").rstrip("/")
        self.model = cfg.get("model", "whisper-large-v3-turbo")
        self.api_key = os.environ.get(cfg.get("api_key_env", "YAP_API_KEY") or "")

    def warmup(self) -> None:
        if not self.api_key:
            print(
                f"yap: warning: cloud engine selected but ${self.cfg.get('api_key_env')} "
                "is not set.",
                file=sys.stderr,
            )

    def _post(self, wav_bytes: bytes) -> str:
        if not self.api_key:
            raise RuntimeError(
                f"No API key: set the ${self.cfg.get('api_key_env')} environment variable, "
                "or switch to the local engine (`yap config set engine local`)."
            )
        fields = {"model": self.model}
        language: Optional[str] = self.cfg.get("language")
        if language:
            fields["language"] = language
        if self.prompt:
            fields["prompt"] = self.prompt
        body, content_type = _multipart(fields, "audio.wav", wav_bytes)
        req = urllib.request.Request(
            f"{self.base_url}/audio/transcriptions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": content_type,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                import json

                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"cloud STT HTTP {e.code}: {detail}") from None
        return (data.get("text") or "").strip()

    def transcribe_file(self, wav_path: str) -> str:
        with open(wav_path, "rb") as f:
            return self._post(f.read())

    def transcribe_array(self, samples: "np.ndarray", samplerate: int) -> str:
        return self._post(_array_to_wav_bytes(samples, samplerate))
