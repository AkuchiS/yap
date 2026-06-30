"""Yap — free, offline-first, cross-platform voice dictation.

Hold a hotkey, speak, and your words appear at the cursor in any app.
Local Whisper by default (no cloud, no telemetry); bring-your-own-key for
cloud speed when you want it.
"""

__version__ = "0.1.7"

# Keep startup/shutdown quiet: HuggingFace's "set a HF_TOKEN" rate-limit notice
# (we only ever download public Whisper models) and the benign leaked-semaphore
# message multiprocessing prints when CTranslate2/audio threadpools tear down.
import os as _os
import warnings as _warnings

_os.environ.setdefault("HF_HUB_VERBOSITY", "error")
_os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
_warnings.filterwarnings("ignore", message=".*leaked semaphore.*")
