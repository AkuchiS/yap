"""Cooperative handoff with other voice apps (e.g. your JARVIS).

yap already releases the microphone the moment you let go of the hotkey — it
only opens the input stream while you're holding it. These hooks go further:
they let another always-listening app *actively* pause while you dictate and
resume right after, so it doesn't treat your dictation as a command.

Flow per dictation:
    hold key  -> active(True)  -> run on_record_start  (tell JARVIS: pause)
    release   -> transcribe + inject
    done      -> active(False) -> run on_record_stop    (tell JARVIS: resume)
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


class Integration:
    def __init__(self, cfg: dict[str, Any]):
        ic = cfg.get("integration", {}) or {}
        self.on_start = ic.get("on_record_start") or ""
        self.on_stop = ic.get("on_record_stop") or ""
        self.state_file = ic.get("state_file") or ""

    def _run(self, command: str) -> None:
        if not command:
            return
        try:
            # fire-and-forget; never block dictation on the hook
            subprocess.Popen(command, shell=True)
        except Exception as e:
            print(f"yap: integration hook failed: {e}", file=sys.stderr)

    def _write_state(self, active: bool) -> None:
        if not self.state_file:
            return
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({"active": active}, f)
        except Exception as e:
            print(f"yap: could not write state file: {e}", file=sys.stderr)

    def record_started(self) -> None:
        self._write_state(True)
        self._run(self.on_start)

    def record_stopped(self) -> None:
        self._write_state(False)
        self._run(self.on_stop)
