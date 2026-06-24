#!/usr/bin/env bash
# Build a self-contained yap on Linux (PyInstaller).
# Output: dist/yap/  (run dist/yap/yap). Needs PortAudio for the mic:
#   Debian/Ubuntu: sudo apt install libportaudio2
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${YAP_BUILD_PY:-}"
if [ -z "$PY" ]; then
  for c in python3.12 python3.11 python3.10 python3; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi
[ -n "$PY" ] || { echo "No python found." >&2; exit 1; }
echo "==> freezing with $("$PY" --version)"

VENV="$ROOT/.build-venv"
rm -rf "$VENV"; "$PY" -m venv "$VENV"; . "$VENV/bin/activate"
pip install -U pip wheel >/dev/null
pip install ".[full]" pyinstaller pillow >/dev/null

rm -rf build dist
pyinstaller packaging/yap.spec --noconfirm
deactivate || true
echo
echo "✓ built dist/yap/  — run:  ./dist/yap/yap run"
echo "Tip: for an AppImage, wrap dist/yap/ with appimagetool."
