"""Entry point for ``python -m tests.egts.cli``."""

from __future__ import annotations

import sys

from tests.egts.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
