"""Speech-to-text engines."""

from __future__ import annotations

from typing import Any

from .base import Engine


def build_engine(cfg: dict[str, Any]) -> Engine:
    """Construct the STT engine selected in config (`engine`: local | cloud)."""
    kind = cfg.get("engine", "local")
    if kind == "local":
        from .local_whisper import LocalWhisperEngine

        return LocalWhisperEngine(cfg["local"])
    if kind == "cloud":
        from .cloud_openai import CloudWhisperEngine

        return CloudWhisperEngine(cfg["cloud"])
    raise ValueError(f"unknown engine {kind!r} (expected 'local' or 'cloud')")
