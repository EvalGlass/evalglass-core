"""Enable ``python -m _evalglass.harness`` as the clean CLI entrypoint (EG-MDU-5).

Invoking the CLI as ``python -m _evalglass.harness.cli`` triggers a benign ``runpy`` warning,
because importing the ``harness`` package eagerly imports ``cli`` before ``cli`` runs as
``__main__``. Running ``python -m _evalglass.harness`` goes through this module instead, so ``cli``
is imported normally (never as ``__main__``) and no warning is emitted. Behaviour is identical.
"""

from __future__ import annotations

from evalglass.harness.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
