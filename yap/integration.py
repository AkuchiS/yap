"""Cooperative, context-aware handoff with other voice apps (e.g. another assistant).

yap already releases the microphone the moment you let go of the hotkey — it only
opens the input stream while you're holding it. These hooks go further: they let
another always-listening app *actively* pause while you dictate and resume right
after, and they carry **context** so that pause can be smart.

Every hook command runs with these environment variables set, and the same data
is written to the optional state_file as JSON:

    YAP_EVENT       "start" | "stop"
    YAP_OS          sys.platform, e.g. "darwin" | "win32" | "linux"
    YAP_ACTIVE_APP  the frontmost app you're dictating into (best-effort; may be empty)

So a hook can decide per-OS and per-app — e.g. *don't* pause the assistant if
YAP_ACTIVE_APP is the assistant itself, or behave differently in Slack vs an editor.

Flow per dictation:
    hold key  -> active(True)  -> on_record_start   (context: where you're typing)
    release   -> transcribe + inject
    done      -> active(False) -> on_record_stop
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Optional

from .activeapp import frontmost_app


class Integration:
    def __init__(self, cfg: dict[str, Any]):
        ic = cfg.get("integration", {}) or {}
        self.on_start = ic.get("on_record_start") or ""
        self.on_stop = ic.get("on_record_stop") or ""
        self.state_file = ic.get("state_file") or ""

    def _context_env(self, event: str, app: Optional[str]) -> dict:
        import os

        env = dict(os.environ)
        env["YAP_EVENT"] = event
        env["YAP_OS"] = sys.platform
        env["YAP_ACTIVE_APP"] = app or ""
        return env

    def _run(self, command: str, event: str, app: Optional[str]) -> None:
        if not command:
            return
        try:
            # fire-and-forget; never block dictation on the hook
            subprocess.Popen(command, shell=True, env=self._context_env(event, app))
        except Exception as e:
            print(f"yap: integration hook failed: {e}", file=sys.stderr)

    def _write_state(self, active: bool, app: Optional[str]) -> None:
        if not self.state_file:
            return
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({"active": active, "os": sys.platform,
                           "active_app": app or ""}, f)
        except Exception as e:
            print(f"yap: could not write state file: {e}", file=sys.stderr)

    def record_started(self) -> Optional[str]:
        # Capture the focused app at the moment dictation begins — that's the app
        # you're dictating INTO, before any paste shifts focus. Returned so the
        # matching stop event can report the same app.
        app = frontmost_app()
        self._write_state(True, app)
        self._run(self.on_start, "start", app)
        return app

    def record_stopped(self, app: Optional[str] = None) -> None:
        self._write_state(False, app)
        self._run(self.on_stop, "stop", app)
