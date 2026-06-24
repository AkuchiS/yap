"""Auto-vocabulary: learn the words you actually use.

yap watches your transcripts and counts the "learnable" tokens — acronyms
(JARVIS, NASA), CamelCase (JavaScript, GitHub), and mid-sentence proper nouns
(names, places). Once you've used one `min_count` times it's promoted into your
personal glossary, which biases future recognition toward spelling it right.

Safety rails so it never degrades accuracy:
  * only repeated words get promoted (one-offs are ignored),
  * sentence-initial capitalization is skipped (that's grammar, not a name),
  * words already in your manual vocabulary are left alone,
  * the learned glossary is capped (keep the most frequent), so the Whisper
    prompt never grows unbounded.

Counts persist to <config_dir>/learned.json, so it keeps learning across runs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import config_dir

# A token: starts with a letter, may contain letters/digits/'-_.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'_-]*")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CAMEL = re.compile(r"[a-z][A-Z]")

# Don't "learn" these even if capitalized mid-sentence (common words, weekdays…).
_STOP = {
    "i", "i'm", "i'd", "i'll", "i've", "ok", "okay", "the", "a", "an", "and",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "mr", "mrs", "ms", "dr",
}


def extract_candidates(text: str) -> list[str]:
    """Proper-noun-ish tokens worth learning (preserving their casing)."""
    out: list[str] = []
    for sentence in _SENT_SPLIT.split(text or ""):
        words = list(_WORD.finditer(sentence))
        for i, m in enumerate(words):
            w = m.group(0)
            if len(w) < 2 or w.lower() in _STOP:
                continue
            if w.isupper():                         # acronym: JARVIS, NASA
                out.append(w)
            elif _CAMEL.search(w):                  # CamelCase: JavaScript
                out.append(w)
            elif w[0].isupper() and i > 0:          # mid-sentence proper noun
                out.append(w)
    return out


class VocabLearner:
    def __init__(self, cfg: dict[str, Any]):
        lc = cfg.get("learning", {}) or {}
        self.enabled = bool(lc.get("enabled", True))
        self.min_count = int(lc.get("min_count", 3))
        self.max_words = int(lc.get("max_words", 80))
        self.path = config_dir() / "learned.json"
        self._manual = {str(w).lower() for w in cfg.get("vocabulary", []) if str(w).strip()}
        self._counts: dict[str, int] = self._load()
        self._promoted = self._compute_promoted()

    def _load(self) -> dict[str, int]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return {str(k): int(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._counts, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _compute_promoted(self) -> list[str]:
        eligible = [(w, c) for w, c in self._counts.items()
                    if c >= self.min_count and w.lower() not in self._manual]
        # most frequent first, capped
        eligible.sort(key=lambda wc: (-wc[1], wc[0]))
        return [w for w, _ in eligible[: self.max_words]]

    def observe(self, text: str) -> list[str]:
        """Count words from a transcript. Return any words newly promoted."""
        if not self.enabled or not text.strip():
            return []
        before = set(self._promoted)
        for w in extract_candidates(text):
            if w.lower() in self._manual:
                continue
            self._counts[w] = self._counts.get(w, 0) + 1
        self._promoted = self._compute_promoted()
        self._save()
        return [w for w in self._promoted if w not in before]

    def words(self) -> list[str]:
        """The current learned glossary (promoted words)."""
        return list(self._promoted)

    def forget(self, word: str) -> bool:
        """Drop a learned word and stop it being relearned immediately."""
        hit = False
        for key in [k for k in self._counts if k.lower() == word.lower()]:
            del self._counts[key]
            hit = True
        if hit:
            self._promoted = self._compute_promoted()
            self._save()
        return hit
