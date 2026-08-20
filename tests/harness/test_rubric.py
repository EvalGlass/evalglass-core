"""Host-owned rubric loading + judge provenance (EG-M4-2).

A judge metric scores against a host-owned rubric (``evals/rubrics/*.md``, outside the
managed ``_evalglass/`` tree). The rubric's version, the prompt/model/parser refs, and a
**content fingerprint** enter the run's gating provenance, so changing the rubric — bumping
its version *or* editing its text without a bump — breaks baseline comparability (P14): you
cannot claim "no regression" across a rubric change. An unrelated change (a different example
set) stays comparable, so provenance is a sharp instrument, not a blunt one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.core import BaselineState, ComparableRunFingerprint
from evalglass.harness.config import RubricConfig, RuntimeConfig
from evalglass.harness.errors import SetupError
from evalglass.harness.rubric import load_rubric
from evalglass.harness.runner import run_config


def _write_rubric(root: Path, body: str = "# Faithfulness\nScore the answer 0..1.\n") -> None:
    rubrics = root / "rubrics"
    rubrics.mkdir(parents=True, exist_ok=True)
    (rubrics / "faithfulness.md").write_text(body, encoding="utf-8")


# --- loading: host-owned, fail-closed ---------------------------------------


def test_load_rubric_reads_and_fingerprints(tmp_path: Path) -> None:
    _write_rubric(tmp_path)
    ref = load_rubric(
        RubricConfig(path="rubrics/faithfulness.md", version="2", parser_version="json_score@1"),
        tmp_path,
    )
    assert ref.version == "2"
    assert ref.parser_version == "json_score@1"
    assert ref.content_fingerprint.startswith("sha256:")


def test_missing_rubric_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SetupError):
        load_rubric(RubricConfig(path="rubrics/nope.md"), tmp_path)


def test_rubric_path_escaping_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SetupError):
        load_rubric(RubricConfig(path="../secret.md"), tmp_path)


def test_rubric_under_managed_dir_fails_closed(tmp_path: Path) -> None:
    managed = tmp_path / "_evalglass"
    managed.mkdir()
    (managed / "r.md").write_text("x", encoding="utf-8")
    with pytest.raises(SetupError):
        load_rubric(RubricConfig(path="_evalglass/r.md"), tmp_path)


def test_rubric_symlink_into_managed_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "_evalglass").mkdir()
    (tmp_path / "_evalglass" / "secret.md").write_text("managed", encoding="utf-8")
    (tmp_path / "rubrics").mkdir()
    (tmp_path / "rubrics" / "link.md").symlink_to(tmp_path / "_evalglass" / "secret.md")
    with pytest.raises(SetupError):
        load_rubric(RubricConfig(path="rubrics/link.md"), tmp_path)


def test_rubric_invalid_utf8_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "rubrics").mkdir()
    (tmp_path / "rubrics" / "bad.md").write_bytes(b"\xff\xfe not utf8")
    with pytest.raises(SetupError):
        load_rubric(RubricConfig(path="rubrics/bad.md"), tmp_path)


# --- provenance: sensitivity + specificity ----------------------------------


def _cfg(tmp_path: Path, *, rubric_version: str = "1", example_id: str = "e1") -> RuntimeConfig:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"example_id": example_id, "input": "q", "output": "a", "reference": "a"})
        + "\n",
        encoding="utf-8",
    )
    raw: dict[str, Any] = {
        "datasets": [{"path": "d.jsonl", "status": "validated", "data_policy": "permitted"}],
        "judge": {"adapter": "fake", "default_value": 1.0},
        "metrics": [
            {
                "name": "exact_match",
                "evaluator_ref": "exact_match@1",
                "lens": "reference",
                "score_type": "binary",
                "required_evidence": ["judge"],
                "rubric": {"path": "rubrics/faithfulness.md", "version": rubric_version},
            }
        ],
    }
    return RuntimeConfig.from_mapping(raw)


def _comparable(tmp_path: Path, a: RuntimeConfig, b: RuntimeConfig) -> BaselineState:
    base = run_config(a, tmp_path).provenance
    cand = run_config(b, tmp_path).provenance
    return ComparableRunFingerprint(current=cand, baseline=base, requested=True).state


def test_rubric_version_change_breaks_comparability(tmp_path: Path) -> None:
    _write_rubric(tmp_path)
    state = _comparable(
        tmp_path, _cfg(tmp_path, rubric_version="1"), _cfg(tmp_path, rubric_version="2")
    )
    assert state is BaselineState.NOT_COMPARABLE


def test_rubric_content_edit_breaks_comparability(tmp_path: Path) -> None:
    # editing the rubric text WITHOUT bumping the version must still break comparability
    _write_rubric(tmp_path, "# v1\n")
    base = run_config(_cfg(tmp_path, rubric_version="1"), tmp_path).provenance
    _write_rubric(tmp_path, "# v1 but edited\n")
    cand = run_config(_cfg(tmp_path, rubric_version="1"), tmp_path).provenance
    assert ComparableRunFingerprint(current=cand, baseline=base, requested=True).state is (
        BaselineState.NOT_COMPARABLE
    )


def test_example_only_change_stays_comparable(tmp_path: Path) -> None:
    _write_rubric(tmp_path)
    state = _comparable(
        tmp_path,
        _cfg(tmp_path, example_id="e1"),
        _cfg(tmp_path, example_id="e2"),
    )
    assert state is BaselineState.COMPARABLE


# --- the rubric refs flow into the judge evidence ---------------------------


def test_judge_evidence_carries_rubric_refs(tmp_path: Path) -> None:
    from evalglass.adapters.judge_fake import FakeJudgeModel
    from evalglass.core import EvalUnit, Example, UnitKind
    from evalglass.harness.config import MetricConfig
    from evalglass.harness.judge import collect_judge_evidence

    _write_rubric(tmp_path)
    ref = load_rubric(
        RubricConfig(
            path="rubrics/faithfulness.md",
            version="3",
            prompt_ref="prompts/f@1",
            model_ref="fake-1",
            parser_version="json_score@1",
        ),
        tmp_path,
    )
    metric = MetricConfig.from_mapping(
        {
            "name": "faithfulness",
            "evaluator_ref": "judge_score@1",
            "lens": "non_reference",
            "score_type": "continuous",
            "score_range": [0.0, 1.0],
            "required_evidence": ["judge"],
        },
        0,
    )
    example = Example(
        example_id="e1",
        input="q",
        output="a",
        unit=EvalUnit(unit_id="e1", kind=UnitKind.CALL, trace_id="t"),
        context={"judge": {"value": 0.5}},
    )
    from evalglass.harness.plan import MetricView, build_plan

    view = MetricView(
        name=metric.spec.name,
        selector=metric.selector,
        is_judge=True,
        is_reference=False,
        prerequisites=["judge"],
        rubric_ref=ref.path,
    )
    plan = build_plan(run_id="t", subjects_in=[(example, True)], metrics=[view])
    evidence, _diags, _handled = collect_judge_evidence(
        FakeJudgeModel(), plan, {"s0": example}, rubrics={"faithfulness": ref}
    )
    assert evidence[0].rubric_ref == "rubrics/faithfulness.md"
    assert evidence[0].rubric_version == "3"
    assert evidence[0].prompt_ref == "prompts/f@1"
    assert evidence[0].model_ref == "fake-1"
    assert evidence[0].parser_version == "json_score@1"
