"""Frozen-app entry point.

Double-click (no args) launches the menu-bar app; any args run the normal CLI,
so the same binary serves both `yap.app` and `yap <subcommand>`.
"""

import sys

from yap.cli import main

if len(sys.argv) == 1:
    sys.argv.append("app")

raise SystemExit(main())
