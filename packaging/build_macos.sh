#!/usr/bin/env bash
# Build a self-contained yap.app on macOS (PyInstaller).
# The app bundles its own Python + Whisper stack, so macOS shows "yap" (with
# your icon) in permission dialogs — not "Python".
#
# Usage:
#   ./packaging/build_macos.sh [path/to/icon.png]
#   YAP_BUILD_PY=python3.12 ./packaging/build_macos.sh     # pin the freeze Python
#   YAP_MENUBAR_ONLY=1 ./packaging/build_macos.sh          # hide the Dock icon
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 1. Pick a mature Python to freeze with (3.14 is brand new; prefer 3.12/3.11).
PY="${YAP_BUILD_PY:-}"
if [ -z "$PY" ]; then
  for c in python3.12 python3.11 python3.13 python3.10 python3; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi
[ -n "$PY" ] || { echo "No python found. brew install python@3.12" >&2; exit 1; }
echo "==> freezing with $("$PY" --version) ($PY)"

# 2. Clean, isolated build venv.
VENV="$ROOT/.build-venv"
rm -rf "$VENV"; "$PY" -m venv "$VENV"; . "$VENV/bin/activate"
pip install -U pip wheel >/dev/null
echo "==> installing yap + build tools (this pulls the Whisper stack)…"
pip install ".[full]" pyinstaller pillow >/dev/null

# 3. Turn your icon into a multi-resolution .icns.
ICON_PNG="${1:-$HOME/Library/Application Support/yap/icon.png}"
if [ -f "$ICON_PNG" ]; then
  WORK="$(mktemp -d)"; ISET="$WORK/yap.iconset"; mkdir -p "$ISET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$ICON_PNG" --out "$ISET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$ICON_PNG" --out "$ISET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ISET" -o "$WORK/yap.icns"
  export YAP_ICNS="$WORK/yap.icns"
  echo "==> icon: $YAP_ICNS"
else
  echo "==> no icon at '$ICON_PNG' (run 'yap icon <file>' first); building without one"
fi

# 4. Freeze.
rm -rf build dist
echo "==> running PyInstaller…"
pyinstaller packaging/yap.spec --noconfirm

# 5. Ad-hoc sign so the app's OWN bundled binary is the permission identity.
codesign --force --deep --sign - dist/yap.app 2>/dev/null || \
  echo "   (codesign skipped — app still runs)"

# 6. Install into ~/Applications.
DEST="$HOME/Applications"; mkdir -p "$DEST"
rm -rf "$DEST/yap.app"; cp -R dist/yap.app "$DEST/"
deactivate || true
echo
echo "✓ built $DEST/yap.app"
echo "Next: open it, then grant 'yap' Microphone + Accessibility + Input Monitoring"
echo "in System Settings → Privacy & Security. It now shows as yap, with your icon."
