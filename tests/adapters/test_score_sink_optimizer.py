"""Prompt-optimizer handoff contract tests (EG-AT4-5; alignment plan §5.3, delta D5).

The prompt-optimizer handoff is a *next*-status, **not-yet-built** capability. Like the
hosted-dashboard sink, there is no optimizer module to import — fabricating one would be a
false-confidence lane. We prove the *contract any optimizer handoff must satisfy*, modeled
hermetically and pinned by a snapshot of a host-owned ``evals/`` tree:

* **write-only** — the handoff exports findings derived from the typed Scorecard into
  ``reports/`` and never writes back into host-owned truth (datasets / evaluators / rubrics /
  ``evalglass.yaml`` / baselines / ``authority.json``);
* **no return path to authority/verdict** — it recomputes nothing; the verdict it reports is
  echoed verbatim from the Scorecard and the ``LaneResult`` carries no authority field;
* a **mutating** optimizer (auto-tune that writes back into ``datasets/``) is the bound we
  forbid; the negative control proves the no-mutation snapshot diff actually fires.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core import Scorecard
from evalglass.harness.lanes import LaneResult, LaneStatus
from tests.egts.checkers import check_lane_grants_no_authority
from tests.egts.host_repo import snapshot
from tests.scorecard_factory import informational_scorecard as _scorecard

#: Host-owned truth seeded into the test ``evals/`` tree — none of it may be written by a handoff.
_HOST_OWNED = {
    "datasets/gold.jsonl": '{"id": "ex1", "input": "hi", "output": "hello"}\n',
    "evaluators/custom.py": "# host-owned scorer\n",
    "rubrics/quality.md": "# host-owned rubric\n",
    "evalglass.yaml": "version: 1\n",
    "baselines/main.json": '{"run_id": "base"}\n',
    "authority.json": "{}\n",
}

_FORBIDDEN_RESULT_ATTRS = ("score", "scores", "value", "verdict", "authority", "ci_should_fail")


def _make_evals(root: Path) -> Path:
    evals = root / "evals"
    for rel, body in _HOST_OWNED.items():
        dest = evals / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    return evals


def _host_owned_snapshot(evals: Path) -> dict[str, str]:
    """Hash everything under ``evals/`` except the write-allowed ``reports/`` output area."""
    # Normalize separators so the reports/ exclusion holds regardless of OS path style.
    return {
        rel: h
        for rel, h in snapshot(evals).items()
        if not rel.replace("\\", "/").startswith("reports/")
    }


def _optimizer_handoff(scorecard: Scorecard, *, evals: Path) -> LaneResult:
    """A conforming handoff: derive findings from the typed Scorecard, write ONLY to reports/."""
    findings = {
        "verdict": scorecard.to_dict()["verdict"],  # echoed verbatim, never recomputed
        "suggestions": ["review the lowest-scoring metric"],
    }
    out = evals / "reports" / "optimizer-handoff.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(findings, sort_keys=True), encoding="utf-8")
    return LaneResult(lane="optimizer", status=LaneStatus.RAN, report="wrote handoff findings")


def _mutating_optimizer(scorecard: Scorecard, *, evals: Path) -> LaneResult:
    """DELIBERATELY WRONG: auto-tunes by writing back into host-owned datasets — forbidden."""
    (evals / "datasets" / "gold.jsonl").write_text("tuned by optimizer\n", encoding="utf-8")
    return LaneResult(lane="optimizer", status=LaneStatus.RAN, report="auto-tuned the dataset")


def test_optimizer_handoff_writes_only_findings_not_host_truth(tmp_path: Path) -> None:
    """No write to datasets / evaluators / rubrics / config / baselines / authority.json."""
    evals = _make_evals(tmp_path)
    before = _host_owned_snapshot(evals)
    _optimizer_handoff(_scorecard(tmp_path), evals=evals)
    after = _host_owned_snapshot(evals)
    assert after == before, "the handoff mutated host-owned truth"
    # The only thing it created is the one-way findings file under reports/.
    assert (evals / "reports" / "optimizer-handoff.json").exists()


def test_optimizer_handoff_result_grants_no_authority(tmp_path: Path) -> None:
    evals = _make_evals(tmp_path)
    result = _optimizer_handoff(_scorecard(tmp_path), evals=evals)
    check_lane_grants_no_authority(result)
    present = [attr for attr in _FORBIDDEN_RESULT_ATTRS if hasattr(result, attr)]
    assert present == [], f"optimizer LaneResult carries forbidden attribute(s): {present}"


def test_optimizer_handoff_does_not_recompute_verdict(tmp_path: Path) -> None:
    """The handoff echoes the Scorecard verdict verbatim; it never re-derives meaning."""
    evals = _make_evals(tmp_path)
    scorecard = _scorecard(tmp_path)
    before = scorecard.to_dict()
    _optimizer_handoff(scorecard, evals=evals)
    assert scorecard.to_dict() == before  # Scorecard consumed read-only
    findings = json.loads((evals / "reports" / "optimizer-handoff.json").read_text())
    assert findings["verdict"] == before["verdict"]  # echoed, byte-for-byte, not recomputed


def test_optimizer_handoff_deletion_invariant_verdict_identity(tmp_path: Path) -> None:
    """Removable: running the handoff leaves the verdict byte-identical."""
    evals = _make_evals(tmp_path)
    scorecard = _scorecard(tmp_path)
    verdict_before = json.dumps(scorecard.to_dict()["verdict"], sort_keys=True)
    _optimizer_handoff(scorecard, evals=evals)
    assert json.dumps(scorecard.to_dict()["verdict"], sort_keys=True) == verdict_before


def test_negctl_optimizer_handoff_mutates_host_truth_is_detected(tmp_path: Path) -> None:
    """Negative control: the no-mutation snapshot diff fires for an auto-tuning optimizer.

    Proves the write-only assertion is not tautological — a handoff that writes back into
    ``datasets/`` is detectably wrong (its host-owned snapshot changes).
    """
    evals = _make_evals(tmp_path)
    before = _host_owned_snapshot(evals)
    _mutating_optimizer(_scorecard(tmp_path), evals=evals)
    after = _host_owned_snapshot(evals)
    assert after != before  # the bound the conforming handoff must never cross
    assert after["datasets/gold.jsonl"] != before["datasets/gold.jsonl"]
