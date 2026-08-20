"""Generate the v2 (m5c) validator-evidence acceptance pack from REAL run output (EG-AT6-9).

The pack is never hand-authored: each ``authority_verdict`` claim is backed by a scorecard artifact
produced by a real vendored run, so ``claimed_status`` is the product verdict and ``ci_should_fail``
is whatever the Verdict Engine emitted — symmetric honesty by construction (alignment plan §8.17).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from evalglass.harness.loader import load_config
from evalglass.harness.runner import run_config
from tests.egts.host_repo import AuthorityState, make_vendored_host

SCHEMA_VERSION = "validator.evidence.v1"
CHECKPOINT = "EG-V2.acceptance"

#: One opt-in connector lane proves the EG-M5C-6 trust boundary in the pack. ``langsmith-trace`` is
#: enabled with no endpoint, so it resolves to a clean ``skipped`` lane_result — real side-channel
#: evidence that an opt-in connector carries no authority and leaves the verdict unchanged.
_CONNECTOR_LANE = "langsmith-trace"
_CONNECTOR_ARTIFACT_ID = "m5c-lane-langsmith-trace"
_CONNECTOR_DATASET_ROW = '{"input": "2+2", "output": "4", "reference": "4"}\n'
_CONNECTOR_CONFIG_HEAD = (
    "run:\n  id: connector\noutput:\n  dir: reports\n"
    "datasets:\n- path: datasets/connector.jsonl\n"
    "metrics:\n- name: exact_match\n  evaluator_ref: exact_match@1\n"
    "  lens: reference\n  score_type: binary\n  dataset: datasets/connector.jsonl\n"
)

#: One real run per claimed verdict: (claim id, authority state, claim text).
_CLAIMS = [
    (
        "fresh-install-is-informational",
        AuthorityState.FRESH_INFORMATIONAL,
        "A fresh install measures evidence but activates no gate: the verdict is informational "
        "and CI does not fail.",
    ),
    (
        "host-promoted-gate-passes",
        AuthorityState.HOST_PROMOTED_GATE,
        "A host-promoted gate (validated dataset + approved threshold + gating metric) passes "
        "through the single Verdict Engine and does not fail CI.",
    ),
    (
        "host-promoted-gate-fails-below-threshold",
        AuthorityState.HOST_GATE_FAIL,
        "A host-promoted gate whose measured value misses the approved threshold fails the run "
        "and fails CI (ci_should_fail true).",
    ),
    (
        "active-gate-without-honest-measurement-blocks",
        AuthorityState.HOST_GATE_BLOCKED,
        "An active gate whose evidence cannot be honestly measured (non_evaluable) blocks the run "
        "and fails CI — it is never silently passed.",
    ),
]


def _connector_evidence(base: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run a real in-process evaluation with an opt-in connector lane (no endpoint → a skipped
    lane_result) plus a no-lane control, and derive the connector artifact + integration_boundary
    claim from the real ``RunRecord``.

    In-process (not a vendored subprocess) on purpose: a registered lane's ``module`` string is not
    namespace-rewritten by vendoring (ADR 0011), so a vendored runtime cannot resolve it — the
    in-process runner is the canonical product path and the ``lane_result`` it records is real. The
    no-authority and verdict-unchanged invariants are PROVEN here (a violation fails the build), so
    the committed pack can never assert connector evidence the run does not support.
    """
    root = base / "pack-connector"
    (root / "datasets").mkdir(parents=True, exist_ok=True)
    (root / "datasets" / "connector.jsonl").write_text(_CONNECTOR_DATASET_ROW, encoding="utf-8")
    (root / "with_lane.yaml").write_text(
        _CONNECTOR_CONFIG_HEAD + f"lanes:\n- name: {_CONNECTOR_LANE}\n  enabled: true\n",
        encoding="utf-8",
    )
    (root / "no_lane.yaml").write_text(_CONNECTOR_CONFIG_HEAD, encoding="utf-8")
    with_lane = run_config(load_config(root / "with_lane.yaml"), root)
    no_lane = run_config(load_config(root / "no_lane.yaml"), root)

    lane_results = with_lane.to_dict().get("lane_results", [])
    connector = next((lr for lr in lane_results if lr.get("lane") == _CONNECTOR_LANE), None)
    if connector is None:
        raise RuntimeError(f"the {_CONNECTOR_LANE} lane produced no lane_result")
    # PROVEN, not asserted: the lane_result exposes no authority surface, and the verdict is
    # byte-identical to the no-lane run — a connector is a side channel, never a verdict path.
    authority_keys = {"score", "scores", "verdict", "authority", "can_gate", "ci_should_fail"}
    if authority_keys & set(connector):
        raise RuntimeError(
            f"connector lane_result carried an authority surface: {sorted(connector)}"
        )
    v_lane = json.dumps(with_lane.scorecard.to_dict()["verdict"], sort_keys=True)
    v_nolane = json.dumps(no_lane.scorecard.to_dict()["verdict"], sort_keys=True)
    if v_lane != v_nolane:
        raise RuntimeError("a connector lane changed the verdict — it must be a side channel only")

    artifact = {
        "id": _CONNECTOR_ARTIFACT_ID,
        "kind": "provenance",
        "authority": "product",
        "content": {
            "lane": connector["lane"],
            "optional": True,
            "treated_as_required": False,
            "status": connector["status"],
            "carried_authority": False,
            "verdict_unchanged": True,
        },
    }
    claim = {
        "id": "connector-lane-is-evidence-not-authority",
        "text": (
            "An opt-in trace-connector lane (langsmith-trace) is recorded by the runner seam as a "
            "side-channel lane_result (here: skipped, no endpoint) that carries no authority and "
            "leaves the verdict byte-identical; it is optional and never required. Per-provider "
            "normalization for all three connectors is proven required-tier in "
            "test_m5c_connector_proof.py, not in this pack."
        ),
        "risk_surfaces": ["lane"],
        "expected_families": ["integration_boundary"],
        "required_artifacts": [_CONNECTOR_ARTIFACT_ID],
    }
    return artifact, claim


def build_pack(base: Path) -> dict[str, Any]:
    """Build the m5c acceptance pack by running each state and reading its real Scorecard."""
    artifacts: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for claim_id, state, text in _CLAIMS:
        host = make_vendored_host(base, f"pack-{state.value}", authority_state=state)
        result = host.run(["run", "--config", "evals/evalglass.yaml"])
        if result.exit_code not in (0, 1) or result.scorecard is None:
            raise RuntimeError(f"pack run for {state.value} failed: exit={result.exit_code}")
        verdict = result.scorecard["verdict"]
        artifact_id = f"m5c-sc-{state.value}"
        artifacts.append(
            {
                "id": artifact_id,
                "kind": "scorecard",
                "authority": "product",
                "content": {
                    "verdict": verdict["verdict"],
                    "ci_should_fail": verdict["ci_should_fail"],
                },
            }
        )
        claims.append(
            {
                "id": claim_id,
                "text": text,
                "claimed_status": verdict["verdict"],
                "risk_surfaces": ["verdict", "authority"],
                "expected_families": ["authority_verdict"],
                "required_artifacts": [artifact_id],
            }
        )
    # Connector trust-boundary evidence (EG-R4-3): an opt-in lane is evidence-only, never authority.
    connector_artifact, connector_claim = _connector_evidence(base)
    artifacts.append(connector_artifact)
    claims.append(connector_claim)

    return {
        "schema_version": SCHEMA_VERSION,
        "checkpoint": CHECKPOINT,
        "source_boundary": {"product": [a["id"] for a in artifacts], "external_contracts": []},
        "claims": claims,
        "artifacts": artifacts,
    }


def overclaiming_variant(pack: dict[str, Any]) -> dict[str, Any]:
    """A FAILING variant: an EXTERNAL rendered surface claims ``pass`` over an informational run.

    This is the exact shape the validator-gate's ``authority_verdict`` family fails on — an external
    surface overclaiming beyond the product verdict — so the negative control is gate-faithful,
    not a local inequality on a field the gate ignores.
    """
    variant = copy.deepcopy(pack)
    informational = next(
        a for a in variant["artifacts"] if a["content"]["verdict"] == "informational"
    )
    report_id = "m5c-overclaiming-report"
    variant["artifacts"].append(
        {
            "id": report_id,
            "kind": "report",
            "authority": "external",
            "content": {"claimed_status": "pass"},  # overclaims the informational product verdict
        }
    )
    variant["source_boundary"]["external_contracts"].append(report_id)
    variant["claims"].append(
        {
            "id": "overclaiming-report",
            "text": "A rendered report claims pass while the product run was only informational.",
            "claimed_status": "pass",
            "risk_surfaces": ["verdict"],
            "expected_families": ["authority_verdict"],
            "required_artifacts": [informational["id"], report_id],
        }
    )
    return variant


def connector_sdk_required_variant(pack: dict[str, Any]) -> dict[str, Any]:
    """A FAILING variant: the opt-in connector lane is marked ``treated_as_required`` — i.e. the
    optional provider SDK is presented as a REQUIRED EvalGlass dependency (EG-R4-4).

    The validator-gate's ``integration_boundary`` family fails exactly this shape (an optional lane
    treated as required), so the negative control is gate-faithful, not a local field inequality.
    """
    variant = copy.deepcopy(pack)
    connector = next(a for a in variant["artifacts"] if a["id"] == _CONNECTOR_ARTIFACT_ID)
    connector["content"]["treated_as_required"] = True
    return variant


def connector_authority_overclaim_variant(pack: dict[str, Any]) -> dict[str, Any]:
    """A FAILING variant: an EXTERNAL surface claims the run *passed because a connector pull
    succeeded*, over an informational product run (EG-R4-4).

    A connector imports evidence, never authority; an external surface claiming connector success
    changed the verdict is the ``authority_verdict`` overclaim shape the gate fails.
    """
    variant = copy.deepcopy(pack)
    informational = next(
        a for a in variant["artifacts"] if a["content"].get("verdict") == "informational"
    )
    report_id = "connector-success-report"
    variant["artifacts"].append(
        {
            "id": report_id,
            "kind": "report",
            "authority": "external",
            # Overclaims: a connector success cannot upgrade an informational run to pass.
            "content": {"claimed_status": "pass", "rationale": "langsmith pull succeeded"},
        }
    )
    variant["source_boundary"]["external_contracts"].append(report_id)
    variant["claims"].append(
        {
            "id": "connector-success-changes-verdict",
            "text": "A report claims the run passed because the langsmith connector pull "
            "succeeded, over an informational product run.",
            "claimed_status": "pass",
            "risk_surfaces": ["verdict"],
            "expected_families": ["authority_verdict"],
            "required_artifacts": [informational["id"], report_id],
        }
    )
    return variant
