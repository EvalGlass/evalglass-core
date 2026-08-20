"""v2 (m5c) acceptance pack is honest and real-run-derived (EG-AT6-9; alignment plan §8.17).

The pack feeds the validator-gate. Its honesty is *symmetric* by construction: every claim's
``claimed_status`` equals the product verdict of its scorecard artifact, and ``ci_should_fail``
agrees with that status's exit class. The committed pack must equal one freshly built from real
runs (never hand-authored); an overclaiming variant is caught.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.egts.m5c_pack import (
    CHECKPOINT,
    SCHEMA_VERSION,
    build_pack,
    overclaiming_variant,
)

_PACK_PATH = Path(__file__).resolve().parents[1] / "evidence" / "m5c_acceptance.pack.json"

#: A claimed status whose exit class fails CI.
_CI_FAILING = frozenset({"fail", "blocked"})


def _committed() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    return data


def _artifacts_by_id(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {a["id"]: a for a in pack["artifacts"]}


def test_pack_schema_and_checkpoint() -> None:
    pack = _committed()
    assert pack["schema_version"] == SCHEMA_VERSION
    assert pack["checkpoint"] == CHECKPOINT
    assert pack["claims"], "the pack must carry at least one claim"


def test_every_artifact_is_product_authority() -> None:
    pack = _committed()
    assert pack["artifacts"]
    for artifact in pack["artifacts"]:
        assert artifact["authority"] == "product", f"{artifact['id']} is not product authority"


def test_each_claim_is_symmetric_with_its_scorecard() -> None:
    """claimed_status == the product verdict AND ci_should_fail agrees with its exit class.

    Scoped to the authority_verdict claims (those backed by a scorecard); the connector
    integration_boundary claim is backed by a lane_result provenance artifact, not a verdict, and
    is checked by ``test_connector_lane_claim_is_evidence_only``.
    """
    pack = _committed()
    by_id = _artifacts_by_id(pack)
    verdict_claims = [c for c in pack["claims"] if "claimed_status" in c]
    assert verdict_claims, "the pack must carry at least one authority_verdict claim"
    for claim in verdict_claims:
        scorecards = [
            by_id[a] for a in claim["required_artifacts"] if by_id[a]["kind"] == "scorecard"
        ]
        assert len(scorecards) == 1, f"{claim['id']} must reference exactly one scorecard"
        content = scorecards[0]["content"]
        assert claim["claimed_status"] == content["verdict"], (
            f"{claim['id']}: claimed_status != product verdict"
        )
        expected_ci = claim["claimed_status"] in _CI_FAILING
        assert content["ci_should_fail"] is expected_ci, (
            f"{claim['id']}: ci_should_fail disagrees with the claimed status's exit class"
        )


def test_pack_exercises_every_verdict_and_both_ci_directions() -> None:
    """Symmetric honesty is not one-directional: the pack covers all four product verdicts, so the
    exit-class agreement is tested on both ci-false (informational/pass) and ci-true (fail/blocked)
    claims and neither path can silently disappear on a regenerate."""
    statuses = {c.get("claimed_status") for c in _committed()["claims"]} - {None}
    assert {"informational", "pass", "fail", "blocked"} <= statuses, (
        f"pack is missing verdict(s): {statuses}"
    )


def test_committed_pack_matches_a_fresh_real_run(tmp_path: Path) -> None:
    """The committed pack is real-run-derived, not hand-authored: it equals a freshly built one."""
    assert build_pack(tmp_path) == _committed()


def test_connector_lane_claim_is_evidence_only() -> None:
    """The connector trust-boundary claim (EG-R4-3) is backed by a real lane_result provenance
    artifact that declares the lane optional and NOT treated as required, with no authority and an
    unchanged verdict — the integration_boundary shape the validator-gate passes."""
    pack = _committed()
    by_id = _artifacts_by_id(pack)
    claim = next(c for c in pack["claims"] if c["id"] == "connector-lane-is-evidence-not-authority")
    assert claim["expected_families"] == ["integration_boundary"]
    assert "claimed_status" not in claim, "a connector claim is not an authority_verdict claim"
    [artifact_id] = claim["required_artifacts"]
    content = by_id[artifact_id]["content"]
    assert by_id[artifact_id]["kind"] == "provenance"
    assert by_id[artifact_id]["authority"] == "product"
    assert content["lane"] == "langsmith-trace"
    assert content["optional"] is True
    assert (
        content["treated_as_required"] is False
    )  # the lane is never a required runtime dependency
    assert content["carried_authority"] is False
    assert content["verdict_unchanged"] is True


def test_overclaiming_variant_presents_the_gate_fail_shape() -> None:
    """Negative control (gate-faithful): an EXTERNAL surface overclaims beyond the product verdict.

    The validator-gate's ``authority_verdict`` family fails exactly this shape — an external
    rendered surface whose ``claimed_status`` exceeds the product run's verdict.
    """
    variant = overclaiming_variant(_committed())
    by_id = _artifacts_by_id(variant)
    claim = next(c for c in variant["claims"] if c["id"] == "overclaiming-report")
    product = next(
        by_id[a] for a in claim["required_artifacts"] if by_id[a]["authority"] == "product"
    )
    external = next(
        by_id[a] for a in claim["required_artifacts"] if by_id[a]["authority"] == "external"
    )
    assert product["content"]["verdict"] == "informational"
    assert external["content"]["claimed_status"] == "pass"  # overclaims a run that did not pass
    assert external["content"]["claimed_status"] != product["content"]["verdict"]
