"""J11 author-metric — a proposed metric measures but does not gate (EG-AT6-5).

Alignment plan §F 8.5. A newly authored metric over a proposed dataset can produce a value, but a
value is not permission: it stays ``can_gate=false`` / informational, the host-owned
``authority.json`` is never touched by a run, and a non-scored metric never fabricates a ``0.0``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.egts.host_repo import AuthorityState, CliResult, VendoredHost

pytestmark = pytest.mark.fixture_e2e


def _proposed_run(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> tuple[VendoredHost, CliResult]:
    host = make_host(AuthorityState.PROPOSED_DATASET)
    result = vendored_run(host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0
    assert result.scorecard is not None
    return host, result


def test_reference_metric_on_a_proposed_dataset_cannot_gate(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> None:
    _, result = _proposed_run(make_host, vendored_run)
    scorecard = result.scorecard
    assert scorecard is not None
    assert scorecard["verdict"]["verdict"] == "informational"
    for metric, authority in scorecard["authority"].items():
        assert authority["can_gate"] is False, f"{metric} gates over a proposed dataset"
        assert authority["level"] == "informational"
        assert "dataset_proposed" in authority["reasons"]


def test_a_scored_value_is_not_gating_authority(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> None:
    """The metric scores a real value, yet still cannot gate — number is not permission."""
    _, result = _proposed_run(make_host, vendored_run)
    scorecard = result.scorecard
    assert scorecard is not None
    scored = [m for m in scorecard["metrics"] if m["status_counts"].get("scored")]
    assert scored, "expected at least one scored metric"
    assert all(m["value"] is not None for m in scored)
    assert all(scorecard["authority"][m["metric"]]["can_gate"] is False for m in scored)


def test_a_run_does_not_touch_authority_json(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> None:
    host = make_host(AuthorityState.PROPOSED_DATASET)
    authority = host.evals_dir / "authority.json"
    before = authority.read_text(encoding="utf-8")
    vendored_run(host, "run", "--config", "evals/evalglass.yaml")
    assert authority.read_text(encoding="utf-8") == before, (
        "a run mutated host-owned authority.json"
    )


def test_a_real_non_scored_score_is_null_never_a_fabricated_zero(
    make_host: Callable[..., VendoredHost], vendored_run: Callable[..., CliResult]
) -> None:
    """no-0.0 over a REAL non-scored score: the worst-source state dilutes one example to
    ``non_evaluable``; its per-example value is ``null``, never ``0.0``."""
    host = make_host(AuthorityState.WORST_SOURCE_DILUTED)
    result = vendored_run(host, "run", "--config", "evals/evalglass.yaml")
    assert result.exit_code == 0
    assert result.runrecord is not None
    non_scored = [s for s in result.runrecord["scores"] if s["status"] != "scored"]
    assert non_scored, "the worst-source state should produce at least one non-scored example"
    for score in non_scored:
        assert score["value"] is None, (
            f"{score['status']} score fabricated value {score['value']!r}"
        )
