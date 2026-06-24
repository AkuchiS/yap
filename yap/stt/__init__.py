"""Speech-to-text engines."""

from __future__ import annotations

from typing import Any

from .base import Engine


def build_engine(cfg: dict[str, Any]) -> Engine:
    """Construct the STT engine selected in config (`engine`: local | cloud)."""
    from ..text import build_prompt

    kind = cfg.get("engine", "local")
    prompt = build_prompt(cfg.get("vocabulary"))
    if kind == "local":
        from .local_whisper import LocalWhisperEngine

        return LocalWhisperEngine(cfg["local"], prompt=prompt)
    if kind == "cloud":
        from .cloud_openai import CloudWhisperEngine

        return CloudWhisperEngine(cfg["cloud"], prompt=prompt)
    raise ValueError(f"unknown engine {kind!r} (expected 'local' or 'cloud')")
