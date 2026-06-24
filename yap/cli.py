"""Command-line interface for yap."""

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
    if args.quiet:
        cfg["verbosity"] = "quiet"
    if args.debug:
        cfg["verbosity"] = "debug"
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
    from .text import apply_replacements

    text = cleanup.maybe_clean(text, cfg)
    text = apply_replacements(text, cfg.get("replacements"))
    print(text)
    return 0


def _cmd_vocab(args) -> int:
    cfg = config.load()
    vocab = cfg.setdefault("vocabulary", [])
    repl = cfg.setdefault("replacements", {})
    if args.action == "list":
        print("vocabulary:", ", ".join(vocab) if vocab else "(empty)")
        if repl:
            print("replacements:")
            for k, v in repl.items():
                print(f"  {k!r} -> {v!r}")
        return 0
    if args.action == "add":
        added = [w for w in args.words if w not in vocab]
        vocab.extend(added)
        config.save(cfg)
        print(f"added {added or '(nothing new)'}; vocabulary now {len(vocab)} words")
        return 0
    if args.action == "remove":
        cfg["vocabulary"] = [w for w in vocab if w not in args.words]
        config.save(cfg)
        print(f"vocabulary now {len(cfg['vocabulary'])} words")
        return 0
    if args.action == "fix":
        if len(args.words) != 2:
            print("usage: yap vocab fix <heard> <wanted>", file=sys.stderr)
            return 2
        repl[args.words[0]] = args.words[1]
        config.save(cfg)
        print(f"added replacement {args.words[0]!r} -> {args.words[1]!r}")
        return 0
    return 2


def _cmd_devices(_args) -> int:
    from .audio import list_devices

    print(list_devices())
    return 0


def _cmd_doctor(args) -> int:
    from . import doctor

    return doctor.run(config.load(), prompt=args.prompt, seconds=args.seconds)


def _cmd_app(_args) -> int:
    from . import menubar

    return menubar.run(config.load())


def _cmd_icon(args) -> int:
    import shutil
    from pathlib import Path

    cfg = config.load()
    if not args.path:
        cur = config.icon_path(cfg)
        print(f"current icon: {cur or '(none — default interpreter icon)'}")
        print("set one with:  yap icon /path/to/image.png")
        return 0
    src = Path(args.path).expanduser()
    if not src.exists():
        print(f"yap: no such file: {src}", file=sys.stderr)
        return 1
    dest = config.config_dir() / "icon.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    print(f"installed icon → {dest}")
    print("relaunch 'yap app' to see it in the Dock.")
    return 0


def _cmd_hardware(_args) -> int:
    from . import hardware

    print("yap hardware:")
    print(hardware.summary())
    print("\nUsing model 'auto' adapts to this. Pin one with: "
          "yap config set local.model '\"small\"'")
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
            print("usage: yap config set <dotted.key> <json-value>", file=sys.stderr)
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
            raise SystemExit(f"yap: {dotted}: {k} is not a section")
    cur[keys[-1]] = value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yap",
        description="Free, offline-first voice dictation — speak anywhere, get text at your cursor.",
    )
    p.add_argument("-V", "--version", action="version", version=f"yap {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="start the dictation daemon (hotkey -> text)")
    pr.add_argument("--engine", choices=["local", "cloud"], help="override engine")
    pr.add_argument("--model", help="override local model (e.g. small, large-v3)")
    pr.add_argument("--quiet", action="store_true", help="errors only, no chatter")
    pr.add_argument("--debug", action="store_true", help="verbose per-stage logging")
    pr.set_defaults(func=_cmd_run)

    pt = sub.add_parser("transcribe", help="transcribe an audio file and print the text")
    pt.add_argument("file", help="path to a .wav/.mp3/.m4a/... audio file")
    pt.add_argument("--engine", choices=["local", "cloud"], help="override engine")
    pt.add_argument("--model", help="override local model")
    pt.set_defaults(func=_cmd_transcribe)

    pd = sub.add_parser("devices", help="list microphone input devices")
    pd.set_defaults(func=_cmd_devices)

    pv = sub.add_parser("vocab", help="teach yap your words (names, jargon, fixes)")
    pv.add_argument("action", choices=["list", "add", "remove", "fix"])
    pv.add_argument("words", nargs="*", help="word(s); for 'fix': <heard> <wanted>")
    pv.set_defaults(func=_cmd_vocab)

    pa = sub.add_parser("app", help="run the macOS menu-bar app (like Wispr)")
    pa.set_defaults(func=_cmd_app)

    pi = sub.add_parser("icon", help="set a custom Dock icon for the app")
    pi.add_argument("path", nargs="?", help="image file (PNG/ICNS); omit to show current")
    pi.set_defaults(func=_cmd_icon)

    ph = sub.add_parser("hardware", help="show detected specs + recommended model")
    ph.set_defaults(func=_cmd_hardware)

    pdoc = sub.add_parser("doctor", help="diagnose permissions, hotkey, mic, clipboard")
    pdoc.add_argument("--prompt", action="store_true",
                      help="pop the macOS 'allow control' permission dialog")
    pdoc.add_argument("--seconds", type=int, default=12,
                      help="how long to watch for key events (default 12)")
    pdoc.set_defaults(func=_cmd_doctor)

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
        print(f"yap: file not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"yap: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
