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
pip install ".[full]" pyinstaller pillow pyobjc-framework-ApplicationServices >/dev/null

# 3. Turn your icon into a multi-resolution .icns (shaped to the macOS squircle).
#    Default to the icon committed in the repo so builds are self-contained;
#    fall back to ~/Downloads or the config dir; or pass a path as arg 1.
ICON_SRC="${1:-}"
if [ -z "$ICON_SRC" ]; then
  for c in "$ROOT/packaging/yap-icon.png" "$HOME/Downloads/yap-icon.png" \
           "$HOME/Library/Application Support/yap/icon.png"; do
    [ -f "$c" ] && { ICON_SRC="$c"; break; }
  done
fi
if [ -f "$ICON_SRC" ]; then
  WORK="$(mktemp -d)"; ROUNDED="$WORK/rounded.png"
  # Round to the squircle (transparent corners + inset) so it sits like a native
  # icon, not a hard square. Pillow is already in the build venv.
  if ICON_SRC="$ICON_SRC" ROUNDED="$ROUNDED" python - <<'PY'
import os, sys
try:
    from yap.icons import iconify
    sys.exit(0 if iconify(os.environ["ICON_SRC"], os.environ["ROUNDED"], "darwin") else 1)
except Exception as e:
    print("   (icon rounding skipped: %s)" % e); sys.exit(1)
PY
  then SRC="$ROUNDED"; else SRC="$ICON_SRC"; fi
  ISET="$WORK/yap.iconset"; mkdir -p "$ISET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$SRC" --out "$ISET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$SRC" --out "$ISET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ISET" -o "$WORK/yap.icns"
  export YAP_ICNS="$WORK/yap.icns"
  echo "==> icon: $YAP_ICNS (squircle)"
else
  echo "==> no icon at '$ICON_SRC' (pass one: ./packaging/build_macos.sh path/to/icon.png); building without"
fi

# 4. Clean up any earlier installs so you don't end up with duplicate menu-bar
#    icons or a stale login agent launching an old copy.
echo "==> cleaning up previous installs…"
launchctl unload "$HOME/Library/LaunchAgents/com.yap.dictation.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.yap.dictation.plist"
pkill -f "Applications/[Yy]ap.app" 2>/dev/null || true
rm -rf "$HOME/Applications/yap.app" "$HOME/Applications/Yap.app" \
       "/Applications/yap.app" "/Applications/Yap.app" 2>/dev/null || true

# 5. Freeze.
rm -rf build dist
echo "==> running PyInstaller…"
pyinstaller packaging/yap.spec --noconfirm

# 6. Ad-hoc sign so the app's OWN bundled binary is the permission identity.
codesign --force --deep --sign - dist/Yap.app 2>/dev/null || \
  echo "   (codesign skipped — app still runs)"

# 7. Install into /Applications (the one Finder's sidebar + Launchpad show) if we
#    can write there; otherwise fall back to ~/Applications.
if cp -R dist/Yap.app /Applications/ 2>/dev/null; then
  DEST="/Applications"
else
  DEST="$HOME/Applications"; mkdir -p "$DEST"
  rm -rf "$DEST/Yap.app"; cp -R dist/Yap.app "$DEST/"
  echo "   (couldn't write to /Applications — installed to ~/Applications;"
  echo "    drag Yap.app to /Applications to put it in the main Applications folder)"
fi
deactivate || true
echo
echo "✓ built $DEST/Yap.app"
echo "Next: open it (double-click in Finder, or 'open $DEST/Yap.app'), then grant"
echo "'Yap' Microphone + Accessibility + Input Monitoring in Privacy & Security."
