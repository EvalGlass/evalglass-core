"""Deterministic evaluator loading (EG-M1-4).

Resolves a metric's ``evaluator_ref`` to an effect-free ``Evaluator`` callable: built-ins by
name, or a host-owned file by ``path.py:function``. Loading host code is the one place the
harness imports host Python — it is explicit (config-declared, no discovery) and fails closed
as a setup error on any problem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalglass.core import (
    Direction,
    EvaluatorContext,
    EvalUnit,
    EvidenceBundle,
    Example,
    Lens,
    MetricSpec,
    Score,
    ScoreStatus,
    ScoreType,
    UnitKind,
)
from evalglass.harness.errors import SetupError
from evalglass.harness.evaluator_loader import load_evaluator

_HOST_EVAL = """
from evalglass.core import Score, ScoreStatus, Validity


def evaluate(example, context, evidence):
    return Score(
        metric=context.spec.name, value=1.0, status=ScoreStatus.SCORED,
        validity=Validity.VALID, evaluator_version="host@1",
    )
"""


def _example() -> Example:
    return Example(
        example_id="e1",
        input="2+2",
        output="4",
        reference="4",
        unit=EvalUnit(unit_id="u1", kind=UnitKind.CALL, trace_id="t1"),
    )


def _ctx(name: str = "exact_match") -> EvaluatorContext:
    spec = MetricSpec(
        name=name,
        version="1",
        lens=Lens.REFERENCE,
        granularity=UnitKind.CALL,
        score_type=ScoreType.BINARY,
        direction=Direction.HIGHER_IS_BETTER,
        evaluator_ref=f"{name}@1",
    )
    return EvaluatorContext(spec=spec)


@pytest.mark.parametrize(
    "ref", ["exact_match@1", "exact_match", "set_overlap", "field_presence", "structural_shape"]
)
def test_builtins_resolve(ref: str, tmp_path: Path) -> None:
    evaluator = load_evaluator(ref, tmp_path)
    assert callable(evaluator)


def test_builtin_runs(tmp_path: Path) -> None:
    evaluator = load_evaluator("exact_match@1", tmp_path)
    score = evaluator(_example(), _ctx(), EvidenceBundle())
    assert isinstance(score, Score)
    assert score.status is ScoreStatus.SCORED
    assert score.value == pytest.approx(1.0)


def test_unknown_ref_is_setup_error(tmp_path: Path) -> None:
    with pytest.raises(SetupError) as exc:
        load_evaluator("does_not_exist", tmp_path)
    assert exc.value.diagnostic.code == "evaluator_unknown"


def test_unknown_builtin_version_is_setup_error(tmp_path: Path) -> None:
    # A requested @version that the built-in does not provide must be rejected, not aliased.
    with pytest.raises(SetupError) as exc:
        load_evaluator("exact_match@99", tmp_path)
    assert exc.value.diagnostic.code == "evaluator_unknown"


def test_host_module_is_registered_in_sys_modules(tmp_path: Path) -> None:
    # Normal import semantics: the module must be in sys.modules while it executes.
    (tmp_path / "h.py").write_text(
        "import sys\n\nassert __name__ in sys.modules\n" + _HOST_EVAL, encoding="utf-8"
    )
    assert callable(load_evaluator("h.py:evaluate", tmp_path))


def test_host_file_resolves_and_runs(tmp_path: Path) -> None:
    (tmp_path / "evaluators").mkdir()
    (tmp_path / "evaluators" / "h.py").write_text(_HOST_EVAL, encoding="utf-8")
    evaluator = load_evaluator("evaluators/h.py:evaluate", tmp_path)
    score = evaluator(_example(), _ctx("host"), EvidenceBundle())
    assert isinstance(score, Score)
    assert score.value == pytest.approx(1.0)


def test_host_file_not_found_is_setup_error(tmp_path: Path) -> None:
    with pytest.raises(SetupError) as exc:
        load_evaluator("evaluators/missing.py:evaluate", tmp_path)
    assert exc.value.diagnostic.code == "evaluator_file_not_found"


def test_host_missing_attribute_is_setup_error(tmp_path: Path) -> None:
    (tmp_path / "h.py").write_text(_HOST_EVAL, encoding="utf-8")
    with pytest.raises(SetupError) as exc:
        load_evaluator("h.py:nope", tmp_path)
    assert exc.value.diagnostic.code == "evaluator_attr_missing"


def test_host_non_callable_is_setup_error(tmp_path: Path) -> None:
    (tmp_path / "h.py").write_text("evaluate = 42\n", encoding="utf-8")
    with pytest.raises(SetupError) as exc:
        load_evaluator("h.py:evaluate", tmp_path)
    assert exc.value.diagnostic.code == "evaluator_not_callable"


def test_host_import_error_is_setup_error(tmp_path: Path) -> None:
    (tmp_path / "h.py").write_text("import nonexistent_pkg_xyz\n", encoding="utf-8")
    with pytest.raises(SetupError) as exc:
        load_evaluator("h.py:evaluate", tmp_path)
    assert exc.value.diagnostic.code == "evaluator_import_failed"


def test_bad_ref_shape_is_setup_error(tmp_path: Path) -> None:
    with pytest.raises(SetupError) as exc:
        load_evaluator("file:noseparator.py", tmp_path)
    assert exc.value.diagnostic.code == "evaluator_unknown"
