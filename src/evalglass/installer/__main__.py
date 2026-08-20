"""``python -m evalglass.installer`` entry point — delegates to the CLI (ADR 0010)."""

from __future__ import annotations

import sys

from evalglass.installer.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
