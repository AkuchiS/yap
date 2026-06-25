"""Configuration: cross-platform paths, sane offline-first defaults, env overrides.

Config lives at:
  Linux/BSD : $XDG_CONFIG_HOME/yap/config.json   (~/.config/yap/config.json)
  macOS     : ~/Library/Application Support/yap/config.json
  Windows   : %APPDATA%\\yap\\config.json

Secrets are never stored in the file. API keys are read from environment
variables named by `*.api_key_env` so the config is safe to commit/share.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

APP_NAME = "yap"

DEFAULT_CONFIG: dict[str, Any] = {
    # "local"  -> faster-whisper on this machine (offline, free, private)
    # "cloud"  -> OpenAI-compatible /audio/transcriptions endpoint (BYOK)
    "engine": "local",
    "local": {
        # "auto" picks a model to match your machine (tiny/base on old hardware,
        # small on modern). Or pin one: tiny.en|base.en|small|medium|large-v3 …
        "model": "auto",
        "device": "auto",            # auto | cpu | cuda
        "compute_type": "auto",      # auto | int8 | int8_float16 | float16 | float32
        "language": None,            # None = auto-detect; or "en", "es", ...
        "beam_size": 1,
    },
    "cloud": {
        # Groq is a great default: OpenAI-compatible, very fast, generous free tier.
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3-turbo",
        "api_key_env": "YAP_API_KEY",
        "language": None,
    },
    # Optional second pass: clean up filler words / fix punctuation with an LLM.
    "cleanup": {
        "enabled": False,
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.0-flash-001",
        "api_key_env": "OPENROUTER_API_KEY",
        "prompt": (
            "You are a dictation post-processor. Rewrite the user's raw "
            "speech-to-text transcript into clean, correctly punctuated text. "
            "Remove filler words (um, uh, you know), fix obvious recognition "
            "errors from context, and apply natural capitalization. Do NOT add, "
            "answer, summarize, or editorialize — output ONLY the cleaned text, "
            "nothing else."
        ),
    },
    "hotkey": {
        # Default: push-to-talk on a single key (like Wispr's "hold to dictate").
        # macOS uses Right Option (⌥); elsewhere Right Ctrl. Both are one-finger
        # holds that don't collide with normal typing.
        #
        # NOTE: the macOS Fn/🌐 key can't be used here — it emits no real keypress,
        # only a hidden hardware flag that pynput cannot see. Good single-key
        # alternatives: "<alt_r>" (Right Option), "<cmd_r>" (Right ⌘), "<f9>".
        # For two-key combos use pynput syntax, e.g. "<ctrl>+<alt>".
        "combo": "<alt_r>" if sys.platform == "darwin" else "<ctrl_r>",
        # "hold"  : record only while the combo is held down (push-to-talk).
        # "toggle": press once to start, press again to stop.
        "mode": "hold",
    },
    "inject": {
        "method": "paste",           # "paste" (clipboard + Ctrl/Cmd+V) | "type"
        "restore_clipboard": True,   # put your old clipboard back after pasting
        "trailing_space": True,      # append a space so words don't run together
    },
    "audio": {
        "samplerate": 16000,
        "channels": 1,
        "device": None,              # input device index or name substring; None = default
        "max_seconds": 120,          # hard cap so a stuck recording can't run forever
    },
    # Words/names to bias recognition toward, so jargon and proper nouns come
    # out right (e.g. "PostgreSQL", "Anthropic"). Fed to Whisper as a hint prompt.
    "vocabulary": [],
    # Deterministic fix-ups applied after transcription, {heard: wanted}. Useful
    # when a word is *consistently* misheard, e.g. {"github": "GitHub"}.
    "replacements": {},
    # Auto-vocabulary: learn the proper nouns/jargon you repeat and add them to
    # your glossary automatically. min_count = times a word must appear before
    # it's learned; max_words caps the learned glossary so the prompt stays lean.
    "learning": {
        "enabled": True,
        "min_count": 3,
        "max_words": 80,
    },
    # Terminal chatter: "quiet" (errors only), "normal" (listening + result),
    # "debug" (every stage + tracebacks).
    "verbosity": "normal",
    # Play nice with other voice apps (e.g. your own assistant). yap only opens
    # the mic *while you hold the key*, so the device is free the rest of the
    # time. These hooks let you actively pause/resume another listener:
    #   on_record_start : shell command run the instant dictation begins
    #   on_record_stop  : shell command run after the text is injected
    #   state_file      : if set, yap writes {"active": true/false} here to poll
    "integration": {
        "on_record_start": "",
        "on_record_stop": "",
        "state_file": "",
    },
    # Menu-bar app appearance. icon = path to a custom Dock icon (PNG/ICNS);
    # empty means look for <config_dir>/icon.png (set it with `yap icon <file>`).
    "app": {
        "icon": "",
    },
}


def icon_path(cfg: dict[str, Any]) -> str | None:
    """Resolve the custom app/Dock icon: explicit config, else <config_dir>/icon.png."""
    explicit = (cfg.get("app", {}) or {}).get("icon") or ""
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)
    default = config_dir() / "icon.png"
    return str(default) if default.exists() else None


def config_dir() -> Path:
    override = os.environ.get("YAP_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict[str, Any]:
    """Return defaults deep-merged with the user's config file (if present)."""
    path = config_path()
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"yap: warning: could not read {path}: {e}", file=sys.stderr)
            user = {}
    else:
        user = {}
    return _deep_merge(DEFAULT_CONFIG, user)


def save(cfg: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return path


def ensure_exists() -> Path:
    """Write a default config file if none exists yet; return its path."""
    path = config_path()
    if not path.exists():
        save(DEFAULT_CONFIG)
    return path


def api_key_for(section: dict[str, Any]) -> str | None:
    """Resolve the API key for a cloud section from its configured env var."""
    env_name = section.get("api_key_env")
    if not env_name:
        return None
    return os.environ.get(env_name)
