"""Optional LLM post-processing: tidy punctuation, strip filler words.

Off by default (raw Whisper output is already good). When enabled, sends the
transcript to any OpenAI-compatible chat endpoint (OpenRouter by default).
Bring your own key. Fails *open*: if the LLM call errors, you still get the
raw transcript rather than nothing.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def maybe_clean(text: str, cfg: dict[str, Any]) -> str:
    cc = cfg.get("cleanup", {})
    if not cc.get("enabled") or not text.strip():
        return text
    api_key = os.environ.get(cc.get("api_key_env", "") or "")
    if not api_key:
        print(
            f"vox: cleanup enabled but ${cc.get('api_key_env')} is not set; "
            "using raw transcript.",
            file=sys.stderr,
        )
        return text
    try:
        return _chat(text, cc, api_key)
    except Exception as e:  # fail open — never lose the user's words
        print(f"vox: cleanup failed ({e}); using raw transcript.", file=sys.stderr)
        return text


def _chat(text: str, cc: dict[str, Any], api_key: str) -> str:
    base_url = cc.get("base_url", "https://openrouter.ai/api/v1").rstrip("/")
    payload = {
        "model": cc.get("model", "google/gemini-2.0-flash-001"),
        "temperature": 0,
        "messages": [
            {"role": "system", "content": cc.get("prompt", "")},
            {"role": "user", "content": text},
        ],
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Optional OpenRouter attribution headers (harmless elsewhere):
            "HTTP-Referer": "https://github.com/vox-dictation/vox",
            "X-Title": "vox",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    out = data["choices"][0]["message"]["content"].strip()
    return out or text
