"""Shared provider-connector boundary helpers (EG-R0-3; ADR 0033).

The three live connectors (Langfuse / Phoenix / LangSmith, EG-R1…R3) share one boundary so they
stay consistent without a second trace runtime. These helpers prove that boundary *before* any real
SDK adapter merges:

- a missing optional extra / endpoint / credential is a clean :class:`MissingPrerequisite`
  (a skip), never an ``ImportError`` crash or a fabricated score;
- a malformed provider payload becomes a provider-specific :class:`Diagnostic`;
- only ``TraceEnvelope``/``EvalUnit`` cross the boundary — vendor wrapper keys never reach the
  core-visible path;
- the helpers are stdlib-only by static analysis (the SDK is imported lazily, by name, inside the
  lane call path) so importing them never requires a provider SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from evalglass.adapters._connector_boundary import (
    collect_pages,
    lazy_import,
    normalize_spans,
    read_env_credential,
    require_prerequisite,
)
from evalglass.harness.lanes import MissingPrerequisite
from evalglass.harness.ports import TraceRead, TraceUnit
from tests.egts.checkers import check_envelopes_no_vendor_leak

# --- lazy SDK import ---------------------------------------------------------


def test_lazy_import_returns_present_module() -> None:
    assert lazy_import("json", extra="langfuse-trace").dumps({"a": 1}) == '{"a": 1}'


def test_lazy_import_missing_extra_is_missing_prerequisite() -> None:
    with pytest.raises(MissingPrerequisite) as exc:
        lazy_import("evalglass._no_such_provider_sdk", extra="langfuse-trace")
    # The message names the extra and the pip install hint — never an opaque ImportError.
    assert "langfuse-trace" in str(exc.value)


# --- endpoint / credential prerequisites -------------------------------------


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_require_prerequisite_blank_is_missing_prerequisite(blank: str | None) -> None:
    with pytest.raises(MissingPrerequisite):
        require_prerequisite(blank, what="endpoint")


def test_require_prerequisite_returns_stripped_value() -> None:
    assert require_prerequisite("  https://host  ", what="endpoint") == "https://host"


def test_read_env_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EG_TEST_TOKEN", raising=False)
    assert read_env_credential("EG_TEST_TOKEN") is None
    monkeypatch.setenv("EG_TEST_TOKEN", "  ")
    assert read_env_credential("EG_TEST_TOKEN") is None  # blank reads as absent
    monkeypatch.setenv("EG_TEST_TOKEN", "  s3cret ")
    assert read_env_credential("EG_TEST_TOKEN") == "s3cret"


# --- span normalization (in-memory, reusing the shared span mapping) ---------

#: A provider-shaped span list (open-convention attributes); the boundary maps known fields only.
_GOOD_SPANS = [
    {
        "trace_id": "t1",
        "span_id": "s1",
        "attributes": {"output.value": "hi", "llm.model_name": "m"},
    },
    {"trace_id": "t2", "span_id": "s2", "attributes": {"output.value": "yo"}},
]


def _neutral_metadata(span: Mapping[str, Any]) -> dict[str, Any]:
    del span
    return {"provider": "fake"}


def _normalize(spans: object) -> TraceRead:
    return normalize_spans(
        spans,
        name="fake-trace",
        source="fake-connector",
        data_policy="permitted",
        provenance={"trace": "fake-trace", "provider": "fake"},
        build_metadata=_neutral_metadata,
        malformed_code="fake_malformed_response",
        location="fake://query",
    )


def test_normalize_spans_yields_envelopes_with_no_vendor_leak() -> None:
    read = _normalize(_GOOD_SPANS)
    assert isinstance(read, TraceRead)
    assert read.diagnostics == []
    assert [u.envelope.behavior["output"] for u in read.units] == ["hi", "yo"]
    assert all(isinstance(u, TraceUnit) for u in read.units)
    check_envelopes_no_vendor_leak(
        [u.envelope for u in read.units],
        forbidden_keys=["_langfuse_internal", "cursor", "project_id", "_vendor"],
    )


def test_normalize_spans_non_list_is_malformed_diagnostic() -> None:
    read = _normalize({"not": "a list"})
    assert read.units == []
    assert read.diagnostics[0].code == "fake_malformed_response"


def test_normalize_spans_bad_span_is_diagnostic_others_survive() -> None:
    read = _normalize([{"no": "id or output"}, _GOOD_SPANS[0]])
    assert [u.envelope.behavior["output"] for u in read.units] == ["hi"]
    assert len(read.diagnostics) == 1
    assert read.diagnostics[0].severity.value == "error"


def test_normalize_spans_metadata_failure_is_isolated_per_span() -> None:
    """A provider build_metadata that raises on one span becomes a diagnostic; others still map."""

    def flaky_metadata(span: Mapping[str, Any]) -> dict[str, Any]:
        if span.get("span_id") == "boom":
            raise KeyError("missing usage field")
        return {"provider": "fake"}

    read = normalize_spans(
        [
            {"trace_id": "t1", "span_id": "boom", "attributes": {"output.value": "x"}},
            {"trace_id": "t2", "span_id": "s2", "attributes": {"output.value": "ok"}},
        ],
        name="fake-trace",
        source="fake-connector",
        data_policy="permitted",
        provenance={"trace": "fake-trace"},
        build_metadata=flaky_metadata,
        malformed_code="fake_malformed_response",
        location="fake://query",
    )
    assert [u.envelope.behavior["output"] for u in read.units] == ["ok"]
    assert len(read.diagnostics) == 1
    assert read.diagnostics[0].code == "fake_malformed_response"


def test_normalize_spans_drops_top_level_vendor_wrapper() -> None:
    # The connector hands only the spans list; a vendor wrapper alongside it never reaches here,
    # and per-span vendor keys outside `attributes` are ignored by the mapping.
    spans = [
        {
            "trace_id": "t1",
            "span_id": "s1",
            "_vendor": {"obj": object()},
            "attributes": {"output.value": "hi"},
        }
    ]
    read = _normalize(spans)
    assert read.diagnostics == []
    check_envelopes_no_vendor_leak([u.envelope for u in read.units], forbidden_keys=["_vendor"])


# --- pagination --------------------------------------------------------------


def test_collect_pages_single_page() -> None:
    items, diagnostics = collect_pages(
        lambda cursor: {"spans": [1, 2], "cursor": None},
        items_key="spans",
        cursor_key="cursor",
        malformed_code="fake_malformed_response",
        location="fake://q",
    )
    assert items == [1, 2]
    assert diagnostics == []


def test_collect_pages_follows_cursor_without_duplicates() -> None:
    pages: dict[str | None, Mapping[str, Any]] = {
        None: {"spans": [1], "cursor": "c2"},
        "c2": {"spans": [2], "cursor": None},
    }
    items, diagnostics = collect_pages(
        lambda cursor: pages[cursor],
        items_key="spans",
        cursor_key="cursor",
        malformed_code="fake_malformed_response",
        location="fake://q",
    )
    assert items == [1, 2]
    assert diagnostics == []


def test_collect_pages_cursor_loop_stops_with_diagnostic() -> None:
    # A provider that keeps returning the same cursor must not loop forever or duplicate.
    items, diagnostics = collect_pages(
        lambda cursor: {"spans": [1], "cursor": "stuck"},
        items_key="spans",
        cursor_key="cursor",
        malformed_code="fake_malformed_response",
        location="fake://q",
        max_pages=10,
    )
    assert diagnostics, "a repeated cursor must surface a diagnostic"
    assert len(items) < 10  # bounded, not an infinite/duplicating loop


def test_collect_pages_fetch_error_is_diagnostic_not_crash() -> None:
    def boom(cursor: str | None) -> Mapping[str, Any]:
        raise RuntimeError("provider down")

    items, diagnostics = collect_pages(
        boom,
        items_key="spans",
        cursor_key="cursor",
        malformed_code="fake_malformed_response",
        location="fake://q",
    )
    assert items == []
    assert diagnostics[0].code == "fake_malformed_response"


def test_collect_pages_missing_items_key_is_diagnostic() -> None:
    items, diagnostics = collect_pages(
        lambda cursor: {"wrong_key": []},
        items_key="spans",
        cursor_key="cursor",
        malformed_code="fake_malformed_response",
        location="fake://q",
    )
    assert items == []
    assert diagnostics[0].code == "fake_malformed_response"


def test_collect_pages_error_page_preserves_prior_items() -> None:
    pages: dict[str | None, Mapping[str, Any]] = {None: {"spans": [1], "cursor": "c2"}}

    def fetch(cursor: str | None) -> Mapping[str, Any]:
        if cursor == "c2":
            raise TimeoutError("page 2 timed out")
        return pages[cursor]

    items, diagnostics = collect_pages(
        fetch,
        items_key="spans",
        cursor_key="cursor",
        malformed_code="fake_malformed_response",
        location="fake://q",
    )
    assert items == [1]  # page 1 kept; the failed page 2 is a diagnostic, not a silent drop
    assert diagnostics
