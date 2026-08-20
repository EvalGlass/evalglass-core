"""EG-AT0-5 — golden engine: determinism, drift sensitivity, total normalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.egts.golden import (
    SCENARIOS,
    assert_matches_golden,
    normalize_text,
    render_artifacts,
)
from tests.egts.host_repo import AuthorityState, make_vendored_host

pytestmark = [pytest.mark.fixture_e2e, pytest.mark.slow]


@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS))
def test_rendered_artifacts_match_committed_golden(scenario_id: str, tmp_path: Path) -> None:
    """A fresh real run reproduces the committed golden exactly (specificity)."""
    artifacts = render_artifacts(scenario_id, tmp_path)
    assert_matches_golden(scenario_id, artifacts)


def test_golden_drift_sensitivity_on_verdict_mutation(tmp_path: Path) -> None:
    """Mutating informational→pass in the emitted scorecard must raise (no false green)."""
    artifacts = dict(render_artifacts("fresh_informational", tmp_path))
    artifacts["scorecard.json"] = artifacts["scorecard.json"].replace(
        '"verdict": "informational"', '"verdict": "pass"'
    )
    with pytest.raises(AssertionError, match="golden drift"):
        assert_matches_golden("fresh_informational", artifacts)


def test_golden_normalization_is_total(tmp_path: Path) -> None:
    """Every masked location is genuinely nondeterministic; every unmasked one is stable.

    Two independent hosts produce: byte-identical typed JSON + report (so the
    empty JSON mask set is justified), and CLI stdout that *differs* only in the
    host path (so the one text mask is both necessary and sufficient).
    """
    h1 = make_vendored_host(tmp_path, "tot1", authority_state=AuthorityState.FRESH_INFORMATIONAL)
    h2 = make_vendored_host(tmp_path, "tot2", authority_state=AuthorityState.FRESH_INFORMATIONAL)
    r1 = h1.run(["run", "--config", "evals/evalglass.yaml", "--format", "ci"])
    r2 = h2.run(["run", "--config", "evals/evalglass.yaml", "--format", "ci"])

    # Unmasked typed artifacts are identical across hosts → empty JSON mask is correct.
    assert r1.scorecard == r2.scorecard
    assert r1.runrecord == r2.runrecord

    # The text mask is NECESSARY: raw stdout differs only in the host path...
    assert r1.stdout != r2.stdout
    # ...and SUFFICIENT: after masking, the two are identical.
    assert normalize_text(r1.stdout, h1.root) == normalize_text(r2.stdout, h2.root)
