"""Per-source-function view honest-boundary tests (EG-AT4-10; alignment plan §5.8, delta D5).

Attributing a trace span to a *source function* (call site) requires a correlation EvalGlass does
not have. Inventing one would be false confidence, so the per-source-function view ships nothing:
the honest ceiling is ``view --by-call`` (subject identity via ``example_id``/``unit_id``). This
slice asserts the boundary:

* subject identity is the ceiling — a ``Score`` carries ``example_id``/``unit_id`` but no
  ``source_function`` field;
* an **injected** ``source_function`` claim with no backing evidence is **dropped** at the trace
  normalization boundary (proven against the live mapper, with a negative control showing the leak
  guard fires);
* an **uncorrelated** span yields a ``Diagnostic`` (``trace_mapping_incomplete``), never a guessed
  attribution;
* the capability is **honestly deferred** — no lane is registered and the ``eg_m5c.yaml`` row stays
  ``not_started``.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from evalglass.adapters.trace_backend_stub import StubBackendTraceSource
from evalglass.core.scores import Score
from evalglass.harness.lanes import built_in_lanes
from tests.egts.checkers import CheckerError, check_envelopes_no_vendor_leak

_COVERAGE = Path(__file__).resolve().parents[1] / "egts" / "coverage" / "eg_m5c.yaml"
_PSF_ROW = "EG-M5C-7"


@dataclasses.dataclass
class _FakeEnvelope:
    """A stand-in envelope for the leak-guard negative control."""

    behavior: dict[str, object]
    metadata: dict[str, object]
    provenance: dict[str, object]


def test_subject_identity_is_the_honest_ceiling() -> None:
    """A Score carries by-call identity (example_id/unit_id) but no source-function attribution."""
    fields = {f.name for f in dataclasses.fields(Score)}
    assert {"example_id", "unit_id"} <= fields
    assert "source_function" not in fields


def test_injected_source_function_is_dropped_at_the_boundary(tmp_path: Path) -> None:
    """A span injecting a source_function claim (no backing evidence) is dropped at the boundary."""
    payload = {
        "spans": [
            {
                "trace_id": "t1",
                "source_function": "guessed.module.fn",
                "attributes": {"output.value": "hi", "source_function": "also.guessed"},
            }
        ]
    }
    (tmp_path / "be.json").write_text(json.dumps(payload), encoding="utf-8")
    read = StubBackendTraceSource(backend_path="be.json", root=tmp_path).read()
    assert read.diagnostics == []
    envelopes = [unit.envelope for unit in read.units]
    # The unbacked attribution never crosses into any core-visible section.
    check_envelopes_no_vendor_leak(envelopes, forbidden_keys=["source_function"])


def test_leak_guard_fires_on_a_source_function_attribution() -> None:
    """Negative control: the leak guard detects a source_function attribution if one leaked."""
    leaked = _FakeEnvelope(behavior={"source_function": "guessed.fn"}, metadata={}, provenance={})
    with pytest.raises(CheckerError):
        check_envelopes_no_vendor_leak([leaked], forbidden_keys=["source_function"])


def test_uncorrelated_span_gets_a_diagnostic_not_a_guess(tmp_path: Path) -> None:
    """A span with no resolvable call site is a Diagnostic, never a guessed attribution."""
    (tmp_path / "be.json").write_text(json.dumps({"spans": [{"attributes": {}}]}), encoding="utf-8")
    read = StubBackendTraceSource(backend_path="be.json", root=tmp_path).read()
    assert read.units == []
    assert read.diagnostics[0].code == "trace_mapping_incomplete"


def test_no_per_source_function_lane_is_registered() -> None:
    """The view is absent: no ``built_in_lanes()`` entry mentions source-function attribution."""
    names = built_in_lanes().names()
    assert not any("source" in name or "source-function" in name for name in names), names


def test_per_source_function_is_declared_not_exercised() -> None:
    """The per-source-function coverage row is an honest deferral: ``not_started`` + reason."""
    rows = yaml.safe_load(_COVERAGE.read_text(encoding="utf-8"))["rows"]
    row = next(r for r in rows if r["product_ticket"] == _PSF_ROW)
    assert row["status"] == "not_started"
    assert row.get("not_exercised_reason", "").strip(), "deferred row needs a real reason"
    assert "scenario_ids" not in row or not row["scenario_ids"]
