"""EGTS-M5C-3 — prompt-optimizer handoff proof (Route Proof, Trust Proof).

Proves the real product :class:`~evalglass.adapters.optimizer_handoff.OptimizerHandoffSink` (EG-H2)
over a **real-run** Scorecard produced by ``run_config``:

* ``m5c.optimizer.write_only_handoff`` — the handoff writes only ``reports/optimizer/findings.json``
  and leaves host-owned truth (datasets / evaluators / rubrics / config / baselines) byte-unchanged;
* ``m5c.optimizer.no_write_back`` — a mutating optimizer that writes back into ``datasets/`` is
  detectably wrong (the host-owned snapshot diff fires);
* ``m5c.optimizer.no_recompute`` — the findings echo the Scorecard verdict verbatim, and the
  adapter imports no Verdict Engine / authority resolver / aggregator.

The handoff is opt-in, import-isolated, and removable. Scenario ids map to EG-M5C-3; the full
validator-gate acceptance pack (lane-result evidence) is rebuilt in EG-H5-4.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.adapters.optimizer_handoff import OptimizerHandoffSink
from evalglass.harness.lanes import LaneResult, LaneStatus
from tests.egts.host_repo import snapshot
from tests.egts.lane_conformance import (
    assert_lane_is_opt_in_and_declared,
    assert_lane_result_is_authority_free,
)
from tests.scorecard_factory import informational_record

_HOST_OWNED = {
    "datasets/gold.jsonl": '{"id": "ex1", "input": "hi", "output": "hello"}\n',
    "evaluators/custom.py": "# host-owned scorer\n",
    "rubrics/quality.md": "# host-owned rubric\n",
    "evalglass.yaml": "version: 1\n",
    "baselines/main.json": '{"run_id": "base"}\n',
}
_FINDINGS = "reports/optimizer/findings.json"


def _seed_host_owned(root: Path) -> dict[str, str]:
    for rel, body in _HOST_OWNED.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    return {rel: h for rel, h in snapshot(root).items() if rel.replace("\\", "/") in _HOST_OWNED}


def test_m5c_optimizer_write_only_handoff(tmp_path: Path) -> None:
    """m5c.optimizer.write_only_handoff — over a real-run Scorecard the handoff's ONLY change to
    the host tree is the findings artifact; every pre-existing host file (the real-run dataset plus
    the seeded datasets / evaluators / rubrics / config / baselines) is byte-identical. Removable.

    The before/after compares the FULL host tree (not a hand-listed subset), so a write-back to any
    host-owned path — including the real-run ``d.jsonl`` — is caught, not just the seeded files.
    """
    assert_lane_is_opt_in_and_declared("optimizer-handoff")
    record = informational_record(tmp_path)  # writes the real-run dataset under the host root
    _seed_host_owned(tmp_path)
    before = snapshot(tmp_path)  # the FULL host tree, not just a hand-listed subset
    result = OptimizerHandoffSink(root=tmp_path).export(record.scorecard)
    assert result.status is LaneStatus.RAN
    after = snapshot(tmp_path)
    added = {rel.replace("\\", "/") for rel in set(after) - set(before)}
    assert added == {_FINDINGS}, f"the handoff changed unexpected host paths: {added}"
    for rel in before:
        assert after[rel] == before[rel], f"the handoff mutated host-owned file: {rel}"
    assert_lane_result_is_authority_free(result, record.scorecard, record.scorecard.to_dict())


def test_m5c_optimizer_no_recompute(tmp_path: Path) -> None:
    """m5c.optimizer.no_recompute — the findings echo the Scorecard verdict byte-for-byte; the
    Scorecard is consumed read-only and the adapter imports no meaning engine."""
    record = informational_record(tmp_path)
    before = record.scorecard.to_dict()
    OptimizerHandoffSink(root=tmp_path).export(record.scorecard)
    assert record.scorecard.to_dict() == before
    findings = json.loads((tmp_path / _FINDINGS).read_text(encoding="utf-8"))
    assert findings["verdict"] == before["verdict"]

    from evalglass.adapters import optimizer_handoff as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("core.verdict", "resolve_authority", "core.authority", "core.aggregation", "Verdict(")
    assert [t for t in banned if t in src] == []


def test_negctl_m5c_optimizer_no_write_back(tmp_path: Path) -> None:
    """m5c.optimizer.no_write_back (negative control) — a mutating optimizer that writes back into
    datasets/ is detectably wrong: the host-owned snapshot diff fires."""
    before = _seed_host_owned(tmp_path)

    def _mutating_optimizer(root: Path) -> LaneResult:
        (root / "datasets" / "gold.jsonl").write_text("tuned\n", encoding="utf-8")
        return LaneResult(lane="optimizer", status=LaneStatus.RAN, report="auto-tuned")

    _mutating_optimizer(tmp_path)
    after = {
        rel: h for rel, h in snapshot(tmp_path).items() if rel.replace("\\", "/") in _HOST_OWNED
    }
    assert after != before
    assert after["datasets/gold.jsonl"] != before["datasets/gold.jsonl"]
