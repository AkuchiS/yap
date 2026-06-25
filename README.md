# yap — free voice dictation, everywhere

[![Release](https://img.shields.io/github/v/release/AkuchiS/yap?color=8A2BE2)](https://github.com/AkuchiS/yap/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/AkuchiS/yap/total?color=8A2BE2)](https://github.com/AkuchiS/yap/releases)
[![License: MIT](https://img.shields.io/github/license/AkuchiS/yap?color=8A2BE2)](LICENSE)
![Platforms](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-8A2BE2)

Hold a hotkey, speak, and your words appear at the cursor **in any app** — editor,
browser, chat, terminal. A free, open-source, offline-first alternative to
Wispr Flow / SuperWhisper.

- 🔒 **Private by default** — local Whisper runs on your machine. No cloud, no
  account, no telemetry, no screenshots of your screen. Your voice never leaves
  the device unless *you* choose a cloud engine.
- ♾️ **No limits, no subscription** — Wispr Flow's free tier caps you at 2,000
  words/week and then asks for $12–15/mo. yap is MIT-licensed and unlimited.
- 🖥️ **Cross-platform** — macOS, Windows, Linux. One config, same behaviour.
- ⚡ **Fast** — sub-real-time on CPU with the `base` model; instant with a GPU or
  a cloud key (Groq's Whisper turbo is blazing).
- 🔌 **Bring your own everything** — point it at OpenAI, Groq, or a self-hosted
  Whisper server. Optional LLM cleanup pass via any OpenAI-compatible endpoint
  (OpenRouter by default).

```
  you: (hold Right Option ⌥)  "send him the q3 numbers by friday"
  yap: Send him the Q3 numbers by Friday.        ← typed at your cursor
```

## How it compares

| | Wispr Flow | **yap** |
|---|---|---|
| Price | $12–15/mo (free tier: 2k words/wk) | **Free, unlimited** |
| Offline mode | ❌ cloud only | ✅ **local Whisper by default** |
| Sends audio to a server | Always | Only if you opt into a cloud engine |
| Screenshots active window | Yes (for "context") | **Never** |
| Open source | ❌ | ✅ MIT |
| Platforms | Mac/Win/iOS/Android | Mac/Win/Linux |

## Install

Requires **Python 3.9+**. The local engine downloads a small Whisper model on
first use. Clone, run the installer, go:

```bash
git clone https://github.com/AkuchiS/yap.git
cd yap
./install.sh
yap run
```

`./install.sh` sets up an isolated [pipx](https://pipx.pypa.io) environment so
nothing pollutes your system Python. Then hold **Right Option**, speak, release —
your words land at the cursor.

> Prefer a one-liner? `pipx install git+https://github.com/AkuchiS/yap`
> does the same thing.

### Per-OS extras

- **macOS** — grant your terminal **Accessibility** and **Microphone** permission:
  *System Settings → Privacy & Security → Accessibility / Microphone*. Without
  Accessibility, the paste keystroke is silently ignored.
- **Linux (X11)** — works out of the box. For clipboard fallback install one of
  `xclip` / `xsel`. On **Wayland**, install `wl-clipboard`; some compositors
  restrict synthetic keystrokes — use `--engine local` with
  `inject.method = "type"` if paste doesn't land.
- **Windows** — no extra steps; run from a normal terminal.

## Usage

```bash
yap run                       # start the daemon; hold your hotkey and talk
yap app                       # macOS menu-bar app (like Wispr)
yap transcribe meeting.m4a    # one-shot: transcribe a file, print the text
yap vocab add PostgreSQL      # teach it your words (see below)
yap hardware                  # show your specs + the model it'll auto-pick
yap doctor                    # diagnose permissions / hotkey / mic / clipboard
yap devices                   # list microphones
yap config show               # print effective config
```

### Adapts to your machine

The default model is `"auto"` — yap detects your CPU/RAM/chip and picks a size
that stays responsive: `tiny.en` on very old/light machines, `base.en` on a
2019-era laptop, `small.en` on modern hardware, GPU-accelerated if you have
CUDA. Run `yap hardware` to see the pick, or pin one with
`yap config set local.model '"small"'`.

### Plays nice with other voice apps (context-aware handoff)

yap only holds the mic *while you hold the hotkey*, so it doesn't fight your
other tools. If you run your own always-listening assistant, point the
integration hooks at it so it pauses while you dictate and resumes after:

```bash
yap config set integration.on_record_start '"myassistant pause"'
yap config set integration.on_record_stop  '"myassistant resume"'
```

Each hook runs with **context** in its environment, so the handoff can be smart
about the OS and *which app you're dictating into*:

| var | value |
|---|---|
| `YAP_EVENT` | `start` or `stop` |
| `YAP_OS` | `darwin` / `win32` / `linux` |
| `YAP_ACTIVE_APP` | the frontmost app (e.g. `Slack`, `Code`, `Terminal`) |

For example, *don't* pause your assistant when you're dictating **into** it:

```bash
yap config set integration.on_record_start \
  '"[ \"$YAP_ACTIVE_APP\" = \"MyAssistant\" ] || myassistant pause"'
yap config set integration.on_record_stop \
  '"[ \"$YAP_ACTIVE_APP\" = \"MyAssistant\" ] || myassistant resume"'
```

Same context is written to `integration.state_file` as
`{"active": bool, "os": "...", "active_app": "..."}` if you'd rather poll.

By default yap is **push-to-talk on a single key** (like Wispr's "hold to
dictate"): **hold Right Option ⌥** on macOS (Right Ctrl elsewhere), speak, and
release to transcribe.

### Choosing a hotkey

```bash
yap config set hotkey.combo '"<alt_r>"'    # Right Option ⌥ (macOS default)
yap config set hotkey.combo '"<cmd_r>"'    # Right Command
yap config set hotkey.combo '"<f9>"'       # a function key
yap config set hotkey.combo '"<ctrl>+<alt>"'   # a two-key combo
yap config set hotkey.mode  '"toggle"'     # press to start, press to stop
```

> **Why not the Fn / 🌐 key?** It's the obvious one-finger choice, but on macOS
> the Fn key emits no real keypress — only a hidden hardware flag — so the
> cross-platform input library can't see it. Right Option gives you the same
> one-key feel and works reliably. (A native Fn backend is on the roadmap.)

## Teach it your words

Like Wispr, yap can learn the names and jargon you use so they come out right
instead of being guessed at ("PostgreSQL", not "post grey sequel"):

```bash
yap vocab add PostgreSQL Anthropic Kubernetes # bias recognition toward these
yap vocab fix "github" "GitHub"               # always rewrite a misheard word
yap vocab list
```

`vocab add` feeds Whisper a glossary hint (helps it *spell* unfamiliar words);
`vocab fix` is a guaranteed find/replace for words it *consistently* mangles.

### It also learns on its own

By default yap **watches what you dictate** and learns the proper nouns, jargon,
and acronyms you use repeatedly — adding them to your glossary automatically
(capped, persisted, and never one-offs). So names like `PostgreSQL` or `Kubernetes`
start coming out right after you've used them a few times, with no effort.

```bash
yap vocab learned          # see what it's picked up
yap vocab forget Foo       # drop something it learned by mistake
```

Tune or disable it in config under `learning` (`enabled`, `min_count`,
`max_words`). It only ever learns repeated words and is capped, so it can't run
away or hurt accuracy.

## Quiet vs. verbose

By default yap prints just `● listening…` and the final `✓ "transcript"`.
Want silence (e.g. running it as a background app)? `yap run --quiet`.
Debugging? `yap run --debug` narrates every stage.

## Configuration

Config is a JSON file (`yap config path` to find it). Secrets are **never**
stored here — API keys are read from environment variables. Common tweaks:

```bash
# Use a cloud engine for speed (bring your own key):
export YAP_API_KEY=gsk_...                 # e.g. a Groq key
yap config set engine '"cloud"'

# Turn on the optional LLM cleanup pass (punctuation, filler removal):
export OPENROUTER_API_KEY=sk-or-...
yap config set cleanup.enabled true

# Choose a specific microphone (index from `yap devices`):
yap config set audio.device 3

# Paste vs. direct typing:
yap config set inject.method '"type"'      # if clipboard paste misbehaves
```

Engines:

| `engine` | What runs | Cost | Privacy |
|---|---|---|---|
| `local` *(default)* | faster-whisper on your CPU/GPU | free | audio never leaves the machine |
| `cloud` | any OpenAI-compatible `/audio/transcriptions` | your key | audio sent to that endpoint |

Local model sizes (set `local.model`): `auto` *(default — adapts to your
machine)*, `tiny.en`, `base.en`, `small`, `medium`, `large-v3`. Bigger = more
accurate, slower, more RAM.

## Build a real, standalone app

For a proper app that shows **yap + your icon** in macOS permission dialogs (not
"Python") and needs no separate Python install, freeze it with PyInstaller. The
app bundles its own interpreter + the Whisper stack.

```bash
yap icon ~/Downloads/yap-icon.png        # (optional) your icon first

# macOS  → ~/Applications/yap.app
./packaging/build_macos.sh

# Linux  → dist/yap/  (sudo apt install libportaudio2 for the mic)
./packaging/build_linux.sh

# Windows → dist\yap\yap.exe
powershell -ExecutionPolicy Bypass -File .\packaging\build_windows.ps1
```

Tips: set `YAP_BUILD_PY=python3.12` to freeze with a specific (mature) Python;
`YAP_MENUBAR_ONLY=1` hides the macOS Dock icon. After building on macOS, open the
app and grant **yap** Microphone + Accessibility + Input Monitoring — now shown
under the yap name and icon. Verify any build with `yap selftest`.

### Quick wrapper app (no freeze)

If you just want a Dock launcher fast and don't mind that permissions show under
"Python", `yap bundle --login` makes a lightweight `~/Applications/yap.app` that
calls your installed yap. Good for personal use; the frozen build above is the
one to ship.

## Run it on login (other platforms)

- **Linux** — `install/yap.service` (a user systemd unit), or add `yap run` to
  your desktop's autostart.
- **Windows** — a shortcut to `yap run` in the Startup folder.

See [`install/`](install/) for ready-made helpers.

## macOS permissions (read this if the hotkey "does nothing")

yap needs two macOS permissions: **Input Monitoring** (to see your hotkey) and
**Accessibility** (to type at your cursor). macOS doesn't always prompt — so the
reliable way is to add yap **by hand**:

1. System Settings → Privacy & Security → **Input Monitoring** → click **`+`** →
   press **⌘⇧G**, enter `/Applications/Yap.app`, **Add**, toggle it **on**.
2. Do the same under **Accessibility**.
3. **Quit yap fully and reopen it** — grants only take effect on relaunch.

Running the CLI (`yap run`) from a terminal instead of the app? Grant **your
terminal app** those two permissions rather than Yap.app.

**Rebuilt the app and it stopped working?** An unsigned app's identity changes
every build, so old grants go stale and show "on" but don't apply. Reset and
re-add: `tccutil reset All com.yap.dictation`, then repeat the steps above. (A
single downloaded build doesn't have this problem — it's only an issue when you
rebuild repeatedly.)

## Privacy

With the default `local` engine, yap is **100% offline** — disconnect your
network and it still works. It records audio only while you hold/toggle the
hotkey, keeps nothing on disk, and phones no one home. Cloud engines and the
optional cleanup pass are strictly opt-in and only ever talk to the endpoint
*you* configure.

## Support

yap is free and open source — built by a retired veteran, in his spare time,
because dictation shouldn't be locked behind a subscription. If it saves you
time, a small donation helps cover real costs (like Apple's $99/yr signing fee
for warning-free Mac builds) and keeps it moving. Totally optional — yap is, and
always will be, free.

❤️ [**Sponsor on GitHub**](https://github.com/sponsors/AkuchiS)

## License

MIT — see [LICENSE](LICENSE). Built on
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) /
[OpenAI Whisper](https://github.com/openai/whisper).
