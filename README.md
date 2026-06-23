# vox — free voice dictation, everywhere

Hold a hotkey, speak, and your words appear at the cursor **in any app** — editor,
browser, chat, terminal. A free, open-source, offline-first alternative to
Wispr Flow / SuperWhisper.

- 🔒 **Private by default** — local Whisper runs on your machine. No cloud, no
  account, no telemetry, no screenshots of your screen. Your voice never leaves
  the device unless *you* choose a cloud engine.
- ♾️ **No limits, no subscription** — Wispr Flow's free tier caps you at 2,000
  words/week and then asks for $12–15/mo. vox is MIT-licensed and unlimited.
- 🖥️ **Cross-platform** — macOS, Windows, Linux. One config, same behaviour.
- ⚡ **Fast** — sub-real-time on CPU with the `base` model; instant with a GPU or
  a cloud key (Groq's Whisper turbo is blazing).
- 🔌 **Bring your own everything** — point it at OpenAI, Groq, or a self-hosted
  Whisper server. Optional LLM cleanup pass via any OpenAI-compatible endpoint
  (OpenRouter by default).

```
  you: (hold Ctrl+Alt)  "send him the q3 numbers by friday"
  vox: Send him the Q3 numbers by Friday.        ← typed at your cursor
```

## How it compares

| | Wispr Flow | **vox** |
|---|---|---|
| Price | $12–15/mo (free tier: 2k words/wk) | **Free, unlimited** |
| Offline mode | ❌ cloud only | ✅ **local Whisper by default** |
| Sends audio to a server | Always | Only if you opt into a cloud engine |
| Screenshots active window | Yes (for "context") | **Never** |
| Open source | ❌ | ✅ MIT |
| Platforms | Mac/Win/iOS/Android | Mac/Win/Linux |

## Install

Requires **Python 3.9+**. The local engine downloads a small Whisper model on
first use (~150 MB for `base`).

```bash
git clone https://github.com/vox-dictation/vox
cd vox
pip install .            # add [full] for the recommended clipboard helper:  pip install ".[full]"
```

Or without cloning:

```bash
pip install vox-dictation        # once published to PyPI
```

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
vox run                       # start the daemon; hold Ctrl+Alt and talk
vox run --engine local --model small      # bigger local model, more accuracy
vox transcribe meeting.m4a    # one-shot: transcribe a file, print the text
vox devices                   # list microphones
vox config show               # print effective config
vox config path               # where the config file lives
```

Press **Ctrl+Alt** (default) to start recording, press again to stop and type.
Prefer push-to-talk? Switch to hold mode:

```bash
vox config set hotkey.mode '"hold"'        # record only while the keys are held
vox config set hotkey.combo '"<cmd>+<shift>"'
```

## Configuration

Config is a JSON file (`vox config path` to find it). Secrets are **never**
stored here — API keys are read from environment variables. Common tweaks:

```bash
# Use a cloud engine for speed (bring your own key):
export VOX_API_KEY=gsk_...                 # e.g. a Groq key
vox config set engine '"cloud"'

# Turn on the optional LLM cleanup pass (punctuation, filler removal):
export OPENROUTER_API_KEY=sk-or-...
vox config set cleanup.enabled true

# Choose a specific microphone (index from `vox devices`):
vox config set audio.device 3

# Paste vs. direct typing:
vox config set inject.method '"type"'      # if clipboard paste misbehaves
```

Engines:

| `engine` | What runs | Cost | Privacy |
|---|---|---|---|
| `local` *(default)* | faster-whisper on your CPU/GPU | free | audio never leaves the machine |
| `cloud` | any OpenAI-compatible `/audio/transcriptions` | your key | audio sent to that endpoint |

Local model sizes (set `local.model`): `tiny.en`, `base.en` *(default)*,
`small`, `medium`, `large-v3`. Bigger = more accurate, slower, more RAM.

## Run it on login (optional)

- **macOS / Linux** — add `vox run` to your login items / a user systemd service.
- **Windows** — a shortcut to `vox run` in the Startup folder.

See [`install/`](install/) for ready-made helpers.

## Privacy

With the default `local` engine, vox is **100% offline** — disconnect your
network and it still works. It records audio only while you hold/toggle the
hotkey, keeps nothing on disk, and phones no one home. Cloud engines and the
optional cleanup pass are strictly opt-in and only ever talk to the endpoint
*you* configure.

## License

MIT — see [LICENSE](LICENSE). Built on
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) /
[OpenAI Whisper](https://github.com/openai/whisper).
