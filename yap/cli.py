"""Command-line interface for yap."""

from __future__ import annotations

import argparse
import json
import os
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
        from .learn import VocabLearner

        learned = VocabLearner(cfg).words()
        print("auto-learned:", ", ".join(learned) if learned else "(none yet)")
        return 0
    if args.action == "learned":
        from .learn import VocabLearner

        learned = VocabLearner(cfg).words()
        print("\n".join(learned) if learned else "(nothing learned yet)")
        return 0
    if args.action == "forget":
        from .learn import VocabLearner

        learner = VocabLearner(cfg)
        gone = [w for w in args.words if learner.forget(w)]
        print(f"forgot {gone or '(nothing matched)'}")
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

    print(list_devices(config.load()))
    return 0


def _cmd_license(args) -> int:
    from . import licensing

    if args.verify:
        secret = os.environ.get(licensing.SECRET_ENV, "")
        if not secret:
            print(f"yap: set {licensing.SECRET_ENV} to verify a code", file=sys.stderr)
            return 2
        res = licensing.verify_code(args.verify, secret)
        print(json.dumps(res, indent=2))
        return 0 if res["valid"] else 1
    print(licensing.summary())
    return 0


def _bundled_sample() -> str:
    """Path to the built-in self-test clip (works frozen via _MEIPASS or in-repo)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "jfk.wav")
        if os.path.exists(p):
            return p
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "tests", "jfk.wav")


def _cmd_selftest(args) -> int:
    """Transcribe a known clip via the array path — verifies the STT stack
    (no microphone, GUI, or audio-decode libs needed). Great post-freeze check."""
    import time
    import wave

    import numpy as np

    path = args.file or _bundled_sample()
    with wave.open(path, "rb") as w:
        sr, ch, sw, n = (w.getframerate(), w.getnchannels(),
                         w.getsampwidth(), w.getnframes())
        raw = w.readframes(n)
    dtype = {1: np.int8, 2: "<i2", 4: "<i4"}.get(sw, "<i2")
    audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    audio /= float(1 << (8 * sw - 1))
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)

    cfg = config.load()
    if args.engine:
        cfg["engine"] = args.engine
    from .stt import build_engine

    engine = build_engine(cfg)
    t0 = time.time()
    text = engine.transcribe_array(audio, sr)
    dt = time.time() - t0
    expect = "fellow americans"
    ok = expect in text.lower()
    print(f'selftest: "{text}"')
    print(f"  [{dt:.1f}s, engine={engine.name}]  {'PASS ✓' if ok else 'CHECK ⚠ (unexpected text)'}")
    return 0 if ok else 1


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
    from . import icons

    if args.no_round or icons.iconify(str(src), str(dest)) is False:
        shutil.copyfile(src, dest)
        if not args.no_round:
            print("note: install Pillow for OS-appropriate rounding "
                  "(pipx inject yap-dictation pillow)")
        print(f"installed icon (as-is) → {dest}")
    else:
        shape = "squircle" if sys.platform == "darwin" else "rounded"
        print(f"installed icon ({shape} for your OS) → {dest}")
    print("relaunch 'yap app' to see it in the Dock.")
    return 0


def _cmd_bundle(args) -> int:
    from . import bundle

    app = bundle.build(config.load(), args.dest, login=args.login,
                       menubar_only=args.menubar_only)
    return 0 if app else 2


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

    pl = sub.add_parser("license", help="show install date + early-adopter code")
    pl.add_argument("--verify", metavar="CODE",
                    help=f"verify a grandfather code (needs {'YAP_LICENSE_SECRET'})")
    pl.set_defaults(func=_cmd_license)

    ps = sub.add_parser("selftest", help="verify the STT engine on a known clip")
    ps.add_argument("--file", help="a 16-bit PCM wav to test (default: built-in clip)")
    ps.add_argument("--engine", choices=["local", "cloud"], help="override engine")
    ps.set_defaults(func=_cmd_selftest)

    pv = sub.add_parser("vocab", help="teach yap your words (names, jargon, fixes)")
    pv.add_argument("action",
                    choices=["list", "add", "remove", "fix", "learned", "forget"])
    pv.add_argument("words", nargs="*", help="word(s); for 'fix': <heard> <wanted>")
    pv.set_defaults(func=_cmd_vocab)

    pa = sub.add_parser("app", help="run the macOS menu-bar app (like Wispr)")
    pa.set_defaults(func=_cmd_app)

    pi = sub.add_parser("icon", help="set a custom Dock icon for the app")
    pi.add_argument("path", nargs="?", help="image file (PNG/ICNS); omit to show current")
    pi.add_argument("--no-round", action="store_true",
                    help="install the image as-is, without OS-appropriate rounding")
    pi.set_defaults(func=_cmd_icon)

    pb = sub.add_parser("bundle", help="build a macOS .app (double-click, login, own icon)")
    pb.add_argument("--dest", default="~/Applications",
                    help="where to write yap.app (default ~/Applications)")
    pb.add_argument("--login", action="store_true", help="also launch yap at login")
    pb.add_argument("--menubar-only", action="store_true",
                    help="hide the Dock icon (menu-bar accessory only)")
    pb.set_defaults(func=_cmd_bundle)

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
    from . import licensing

    licensing.stamp_install()  # records first-run date once (local, no telemetry)
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
