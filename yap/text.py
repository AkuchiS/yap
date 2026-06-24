"""Vocabulary biasing + deterministic replacements — the 'remembers my words' bit.

Two complementary mechanisms, mirroring what makes Wispr feel personalized:

  * build_prompt(): turns your vocabulary list into a Whisper "initial prompt".
    Whisper biases its output toward spellings it has just seen, so listing
    "JARVIS", "Anthropic", "Kubernetes" nudges it to transcribe them correctly
    instead of guessing ("Java", "philanthropic", "cube an eddies").

  * apply_replacements(): whole-word, case-insensitive find/replace for the
    cases Whisper *consistently* gets wrong, e.g. {"jarvis": "JARVIS"}.
"""

from __future__ import annotations

import re
from typing import Optional


def build_prompt(vocabulary, base: Optional[str] = None) -> Optional[str]:
    words = [str(w).strip() for w in (vocabulary or []) if str(w).strip()]
    parts = []
    if base:
        parts.append(base.strip())
    if words:
        # A short, comma-separated glossary is the most reliable biasing form.
        parts.append("Glossary: " + ", ".join(words) + ".")
    return " ".join(parts) if parts else None


def apply_replacements(text: str, replacements) -> str:
    if not text or not replacements:
        return text
    out = text
    for heard, wanted in replacements.items():
        if not heard:
            continue
        # \b doesn't hug non-word edges, so allow leading/trailing non-word chars.
        pattern = re.compile(r"(?<!\w)" + re.escape(str(heard)) + r"(?!\w)", re.IGNORECASE)
        out = pattern.sub(str(wanted), out)
    return out
