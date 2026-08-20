"""EGTS — the EvalGlass Testing System.

EGTS is the executable proof system for EvalGlass: it drives the real product
public surfaces, compares typed artifacts to declared scenario expectations, runs
negative controls, and emits coverage + evidence. It proves EvalGlass; it never
becomes EvalGlass (it never computes a verdict, grants authority, or normalizes
scores). See ``tests/CLAUDE.md`` and ``docs/`` (test build contract) for the full
contract, and ``tests/egts/README.md`` for the directory layout.

This is a Layer-2 proof harness, distinct from the fast Layer-1 unit tests under
``tests/{core,...}``. It is built per milestone in lockstep with the product.
"""

from __future__ import annotations
