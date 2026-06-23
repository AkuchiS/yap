"""Command-line interface for vox."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__, config


def _cmd_run(args) -> int:
    cfg = config.load()
    if args.engine:
        cfg["engine"] = args.engine
    if args.model:
        cfg["local"]["model"] = args.model
    from .app import App

    App(cfg).run()
    return 0


def _cmd_transcribe(args) -> int:
    """One-shot transcription of an audio file — works headless (no mic/GUI)."""
    cfg = config.load()
    if args.engine:
        cfg["engine"] = args.engine
    if args.model:
        cfg["local"]["model"] = args.model
    from .stt import build_engine

    engine = build_engine(cfg)
    text = engine.transcribe_file(args.file)
    from . import cleanup

    text = cleanup.maybe_clean(text, cfg)
    print(text)
    return 0


def _cmd_devices(_args) -> int:
    from .audio import list_devices

    print(list_devices())
    return 0


def _cmd_config(args) -> int:
    if args.action == "path":
        print(config.config_path())
    elif args.action == "init":
        print(f"wrote {config.ensure_exists()}")
    elif args.action == "show":
        print(json.dumps(config.load(), indent=2))
    elif args.action == "set":
        if not args.key or args.value is None:
            print("usage: vox config set <dotted.key> <json-value>", file=sys.stderr)
            return 2
        cfg = config.load()
        _set_dotted(cfg, args.key, _parse_value(args.value))
        path = config.save(cfg)
        print(f"set {args.key} = {args.value}  ({path})")
    else:  # pragma: no cover
        print(f"unknown config action {args.action!r}", file=sys.stderr)
        return 2
    return 0


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw  # treat as plain string


def _set_dotted(d: dict, dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
        if not isinstance(cur, dict):
            raise SystemExit(f"vox: {dotted}: {k} is not a section")
    cur[keys[-1]] = value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vox",
        description="Free, offline-first voice dictation — speak anywhere, get text at your cursor.",
    )
    p.add_argument("-V", "--version", action="version", version=f"vox {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="start the dictation daemon (hotkey -> text)")
    pr.add_argument("--engine", choices=["local", "cloud"], help="override engine")
    pr.add_argument("--model", help="override local model (e.g. small, large-v3)")
    pr.set_defaults(func=_cmd_run)

    pt = sub.add_parser("transcribe", help="transcribe an audio file and print the text")
    pt.add_argument("file", help="path to a .wav/.mp3/.m4a/... audio file")
    pt.add_argument("--engine", choices=["local", "cloud"], help="override engine")
    pt.add_argument("--model", help="override local model")
    pt.set_defaults(func=_cmd_transcribe)

    pd = sub.add_parser("devices", help="list microphone input devices")
    pd.set_defaults(func=_cmd_devices)

    pc = sub.add_parser("config", help="manage configuration")
    pc.add_argument("action", choices=["path", "init", "show", "set"])
    pc.add_argument("key", nargs="?", help="dotted key for 'set' (e.g. hotkey.mode)")
    pc.add_argument("value", nargs="?", help="JSON value for 'set' (e.g. '\"hold\"')")
    pc.set_defaults(func=_cmd_config)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError as e:
        print(f"vox: file not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"vox: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
