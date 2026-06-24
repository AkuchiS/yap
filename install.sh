#!/usr/bin/env sh
# yap installer — the simple "got it from GitHub" path.
#
#   git clone https://github.com/AkuchiS/yap.git
#   cd yap && ./install.sh
#   yap run
#
# Installs yap in an isolated pipx environment (no system Python pollution).
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
OS="$(uname -s)"

say() { printf '%s\n' "$*"; }
say "Installing yap…"

# 1. Python 3.9+
if ! command -v python3 >/dev/null 2>&1; then
  say "✗ Python 3.9+ is required but not found."
  case "$OS" in
    Darwin) say "  Install it:  brew install python      (or https://python.org)";;
    *)      say "  Install python3 with your package manager (e.g. apt install python3).";;
  esac
  exit 1
fi

# 2. pipx (isolated installs; bootstrap it if missing)
if command -v pipx >/dev/null 2>&1; then
  PIPX="pipx"
else
  say "Installing pipx (one-time)…"
  python3 -m pip install --user -q pipx || {
    say "✗ Could not install pipx. Try:  python3 -m pip install --user pipx"; exit 1; }
  python3 -m pipx ensurepath >/dev/null 2>&1 || true
  PIPX="python3 -m pipx"
fi

# 3. Install yap with the full desktop extras (menu-bar app, clipboard, icons).
say "Installing yap + dependencies (first run downloads a small speech model)…"
$PIPX install --force ".[full]"

say ""
say "✓ yap installed."
case "$OS" in
  Darwin)
    say "Run it:   yap run        (hold Right Option, speak, release — text appears at your cursor)"
    say ""
    say "First time on macOS, grant your terminal permission:"
    say "  System Settings → Privacy & Security → Accessibility   (add your terminal)"
    say "                                       → Input Monitoring (add your terminal)"
    say "  Microphone is requested automatically the first time you dictate."
    ;;
  Linux)
    say "Run it:   yap run"
    say "If the mic doesn't open, install PortAudio:  sudo apt install libportaudio2"
    ;;
  *)
    say "Run it:   yap run"
    ;;
esac
say ""
say "If 'yap' isn't found, open a NEW terminal window (pipx just updated your PATH)."
