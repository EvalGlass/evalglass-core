"""EvalGlass — open-source, vendored evaluation framework for agentic AI projects.

This is the public top-level package. The architectural seams live in:

* :mod:`evalglass.core`     — the effect-free Evaluation Core (no I/O, no vendor SDKs).
* :mod:`evalglass.harness`  — the Runtime Harness (effectful orchestration).
* :mod:`evalglass.adapters` — concrete adapters behind ports.

See ``CLAUDE.md`` for the architecture boundary and trust-model rules.
"""

__version__ = "0.2.2"
__all__ = ["__version__"]
