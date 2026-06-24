#!/usr/bin/env sh
# yap installer for macOS / Linux.
# Usage:  ./install/install.sh           (installs into the current Python)
#         PIPX=1 ./install/install.sh    (isolated install via pipx)
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

echo "yap installer"
echo "  project: $ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.9+ first." >&2
  exit 1
fi

if [ "${PIPX:-0}" = "1" ] && command -v pipx >/dev/null 2>&1; then
  echo "  installing with pipx (isolated)…"
  pipx install --force ".[full]"
else
  echo "  installing with pip…"
  python3 -m pip install --user ".[full]"
fi

echo
echo "Done. Try:  yap run"
case "$(uname -s)" in
  Darwin)
    echo "macOS: grant your terminal Microphone + Accessibility permission in"
    echo "       System Settings → Privacy & Security, or the paste won't land."
    ;;
  Linux)
    echo "Linux: for clipboard fallback install xclip/xsel (X11) or wl-clipboard (Wayland)."
    ;;
esac
