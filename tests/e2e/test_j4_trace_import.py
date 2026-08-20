"""J4 trace import — OTel / OpenInference / local, vendor-neutral and local (EG-AT6-4).

Alignment plan §F 8.4. Imported behavior is normalized at the edge: no vendor/convention token
crosses into the core-visible artifacts, malformed spans become diagnostics (never silent drops),
imported data is local + proposed, and a live pull is refused before any effect.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from evalglass.adapters.trace_backend_stub import StubBackendTraceSource
from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource
from evalglass.adapters.trace_open_convention import OpenConventionTraceSource
from evalglass.harness.config import TraceConfig
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import TraceRead, TraceSource
from tests.egts.checkers import check_envelopes_no_vendor_leak
from tests.egts.host_repo import CliResult
from tests.fixtures import traces as F2

pytestmark = pytest.mark.fixture_e2e

#: Open-convention / vendor tokens that must never appear in a core-visible artifact.
_CONVENTION_TOKENS = ("gen_ai.", "input.value", "output.value", "llm.")


def _source(fmt: str, path: Path, root: Path) -> TraceSource:
    cfg = TraceConfig.from_mapping(
        {"path": path.name, "format": fmt, "data_policy": "permitted"}, 0
    )
    if fmt == "local":
        return LocalJsonlTraceSource(cfg, root=root)
    return OpenConventionTraceSource(cfg, root=root)


_WRITERS = {
    "opentelemetry": F2.write_otel_export,
    "openinference": F2.write_openinference_export,
    "local": F2.write_local_trace_jsonl,
}
_MALFORMED = {
    "opentelemetry": F2.write_otel_export_malformed,
    "openinference": F2.write_openinference_export_malformed,
    "local": F2.write_local_trace_jsonl_malformed,
}


@pytest.mark.parametrize("fmt", sorted(_WRITERS))
def test_trace_import_normalizes_without_vendor_token(fmt: str, tmp_path: Path) -> None:
    fixture = _WRITERS[fmt](tmp_path)
    read: TraceRead = _source(fmt, fixture.path, tmp_path).read()
    assert read.diagnostics == []
    assert len(read.units) == fixture.expected_count
    envelopes = [u.envelope for u in read.units]
    # No vendor wrapper key (the dotted convention attribute key, or a raw span container) appears
    # in ANY envelope section.
    forbidden = [fixture.convention_token] if fixture.convention_token else []
    check_envelopes_no_vendor_leak(envelopes, forbidden_keys=[*forbidden, "attributes", "context"])
    # The evaluator-visible *behavior* is vendor-neutral: only normalized keys, no convention token.
    behavior_blob = json.dumps([e.behavior for e in envelopes])
    for token in (*_CONVENTION_TOKENS, "opentelemetry", "openinference"):
        assert token not in behavior_blob, f"{fmt} import leaked {token!r} into behavior"
    assert all(set(e.behavior) <= {"input", "output"} for e in envelopes)
    # The source convention is recorded honestly in *provenance* (source-tracking), never behavior —
    # so a reader can audit where a record came from without a vendor object crossing the boundary.
    if fixture.convention_token:
        assert all(e.provenance.get("convention") == fmt for e in envelopes)


@pytest.mark.parametrize("fmt", sorted(_MALFORMED))
def test_trace_import_malformed_span_is_a_diagnostic(fmt: str, tmp_path: Path) -> None:
    bad_path = _MALFORMED[fmt](tmp_path)
    read = _source(fmt, bad_path, tmp_path).read()
    # A malformed span surfaces as a diagnostic — never a silent drop with a clean read.
    assert read.diagnostics, f"{fmt} malformed import produced no diagnostic"


def test_imported_quickstart_artifacts_carry_identity_and_no_vendor_token(
    bundled_example_run: Callable[..., CliResult],
) -> None:
    """A real run over a local trace import: scores carry identity; artifacts are vendor-free."""
    result = bundled_example_run()
    assert result.exit_code == 0
    assert result.runrecord is not None
    assert result.scorecard is not None
    scores = result.runrecord["scores"]
    assert scores
    for score in scores:
        assert score["example_id"], "imported score missing example_id"
        assert score["unit_id"], "imported score missing unit_id"
    blob = json.dumps(result.runrecord) + json.dumps(result.scorecard)
    for token in _CONVENTION_TOKENS:
        assert token not in blob, f"a convention token leaked into the artifacts: {token!r}"


def test_live_pull_is_refused_before_any_effect() -> None:
    """A live pull with no configured endpoint is a clean MissingPrerequisite — no network."""
    with pytest.raises(MissingPrerequisite):
        StubBackendTraceSource(backend_path=None, root=Path("."))
