"""Real ``OptimizerHandoffSink`` adapter tests (EG-H2-5/6).

The prompt-optimizer handoff ships this tranche as a *next*-status, stdlib-only SCORE_SINK lane. It
is a **write-only** evidence handoff: it derives findings from the typed Scorecard and writes them
under ``reports/optimizer/`` so an external optimizer can consume them. It is never an automation
authority — it does not tune prompts, it has no return path into host-owned truth, and it recomputes
nothing (the verdict it records is echoed verbatim from the Scorecard).

These exercise the **real product class**:

* **write-only** — only ``reports/optimizer/findings.json`` is created; datasets / evaluators /
  rubrics / ``evalglass.yaml`` / baselines / ``authority.json`` are byte-unchanged (a host-owned
  snapshot diff is the guard, with a mutating-optimizer negative control proving it fires);
* **no recompute** — the findings echo ``scorecard.to_dict()["verdict"]`` byte-for-byte; the
  adapter imports no ``core.verdict`` / ``resolve_authority`` / aggregator;
* **authority-free + removable** — a ``LaneResult`` only, the verdict stays byte-identical, and a
  destination escaping the host root fails closed to ``BLOCKED``.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.adapters.optimizer_handoff import OptimizerHandoffSink
from evalglass.harness.lanes import LaneResult, LaneStatus
from tests.egts.host_repo import snapshot
from tests.scorecard_factory import informational_scorecard as _scorecard

#: Host-owned truth seeded into the run root — none of it may be written by the handoff.
_HOST_OWNED = {
    "datasets/gold.jsonl": '{"id": "ex1", "input": "hi", "output": "hello"}\n',
    "evaluators/custom.py": "# host-owned scorer\n",
    "rubrics/quality.md": "# host-owned rubric\n",
    "evalglass.yaml": "version: 1\n",
    "baselines/main.json": '{"run_id": "base"}\n',
    "authority.json": "{}\n",
}

_FINDINGS = "reports/optimizer/findings.json"
_FORBIDDEN_RESULT_ATTRS = ("score", "scores", "value", "verdict", "authority", "ci_should_fail")


def _seed_host_owned(root: Path) -> dict[str, str]:
    for rel, body in _HOST_OWNED.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    return {rel: h for rel, h in snapshot(root).items() if rel.replace("\\", "/") in _HOST_OWNED}


def test_optimizer_writes_only_findings_not_host_truth(tmp_path: Path) -> None:
    """No write to datasets / evaluators / rubrics / config / baselines / authority.json."""
    before = _seed_host_owned(tmp_path)
    result = OptimizerHandoffSink(root=tmp_path).export(_scorecard(tmp_path))
    assert result.status is LaneStatus.RAN
    after = {
        rel: h for rel, h in snapshot(tmp_path).items() if rel.replace("\\", "/") in _HOST_OWNED
    }
    assert after == before, "the handoff mutated host-owned truth"
    assert (tmp_path / _FINDINGS).is_file()


def test_optimizer_findings_echo_the_verdict_verbatim(tmp_path: Path) -> None:
    """The handoff echoes the Scorecard verdict byte-for-byte; it never re-derives meaning."""
    scorecard = _scorecard(tmp_path)
    before = scorecard.to_dict()
    OptimizerHandoffSink(root=tmp_path).export(scorecard)
    assert scorecard.to_dict() == before  # Scorecard consumed read-only
    findings = json.loads((tmp_path / _FINDINGS).read_text(encoding="utf-8"))
    assert findings["verdict"] == before["verdict"]  # echoed, byte-for-byte, not recomputed


def test_optimizer_result_grants_no_authority(tmp_path: Path) -> None:
    result = OptimizerHandoffSink(root=tmp_path).export(_scorecard(tmp_path))
    present = [attr for attr in _FORBIDDEN_RESULT_ATTRS if hasattr(result, attr)]
    assert present == [], f"optimizer LaneResult carries forbidden attribute(s): {present}"
    assert isinstance(result.status, LaneStatus)


def test_optimizer_deletion_invariant_verdict_identity(tmp_path: Path) -> None:
    """Removable: running the handoff leaves the verdict byte-identical."""
    scorecard = _scorecard(tmp_path)
    verdict_before = json.dumps(scorecard.to_dict()["verdict"], sort_keys=True)
    OptimizerHandoffSink(root=tmp_path).export(scorecard)
    assert json.dumps(scorecard.to_dict()["verdict"], sort_keys=True) == verdict_before


def test_optimizer_adapter_imports_no_verdict_or_authority_engine() -> None:
    """A handoff renders typed artifacts; it never recomputes meaning. Its source must import no
    Verdict Engine / authority resolver / aggregator."""
    from evalglass.adapters import optimizer_handoff as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("core.verdict", "resolve_authority", "core.authority", "core.aggregation", "Verdict(")
    leaked = [token for token in banned if token in src]
    assert leaked == [], f"the optimizer handoff imports a meaning engine: {leaked}"


def test_optimizer_refuses_symlinked_findings_target(tmp_path: Path) -> None:
    """Fail-closed: a pre-planted symlink at the findings path is refused before writing, so the
    handoff cannot follow it to clobber a host-truth or out-of-root file."""
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("host secret\n", encoding="utf-8")
    target_dir = tmp_path / "reports" / "optimizer"
    target_dir.mkdir(parents=True)
    (target_dir / "findings.json").symlink_to(outside)

    result = OptimizerHandoffSink(root=tmp_path).export(_scorecard(tmp_path))
    assert result.status is LaneStatus.BLOCKED
    assert result.diagnostics[0].code == "optimizer_handoff_symlink_refused"
    assert outside.read_text(encoding="utf-8") == "host secret\n"  # never followed/overwritten


def test_negctl_mutating_optimizer_is_detected(tmp_path: Path) -> None:
    """Negative control: the no-mutation snapshot diff fires for an optimizer that writes back.

    Proves the write-only assertion is not tautological — a handoff that writes into ``datasets/``
    is detectably wrong (its host-owned snapshot changes).
    """
    before = _seed_host_owned(tmp_path)

    def _mutating_optimizer(root: Path) -> LaneResult:
        (root / "datasets" / "gold.jsonl").write_text("tuned by optimizer\n", encoding="utf-8")
        return LaneResult(lane="optimizer", status=LaneStatus.RAN, report="auto-tuned the dataset")

    _mutating_optimizer(tmp_path)
    after = {
        rel: h for rel, h in snapshot(tmp_path).items() if rel.replace("\\", "/") in _HOST_OWNED
    }
    assert after != before
    assert after["datasets/gold.jsonl"] != before["datasets/gold.jsonl"]
