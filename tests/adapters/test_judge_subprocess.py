"""SubprocessJudgeModel — a host command judge over JSON in/out (ADR 0042).

The beta-proven pattern: the harness runs a host-declared ``argv`` as a child process, feeding
``{example_id, metric, input, output, reference, rubric}`` on stdin and expecting
``{value|score, rationale}`` on stdout. Every failure edge (non-zero exit, timeout, spawn
failure, malformed / non-finite output) becomes non-``OK`` evidence with no value — a failed
judge is never a low score. Effectful by design (it owns the subprocess); hermetic in tests
(the child is a `sys.executable -c` script, no network).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from evalglass.adapters.judge_subprocess import SubprocessJudgeModel
from evalglass.core import JudgeEvidenceStatus
from evalglass.harness.ports import JudgeRequest

# A judge script that reflects a fixed verdict; overridden per test via a different body.
_OK = "import sys,json; json.load(sys.stdin); print(json.dumps({'value':0.7,'rationale':'graded'}))"
_ECHO_RUBRIC = (
    "import sys,json; d=json.load(sys.stdin);"
    " print(json.dumps({'value': 1.0 if d.get('rubric') else 0.0}))"
)


def _judge(script: str, root: Path, *, timeout_s: float = 30.0) -> SubprocessJudgeModel:
    return SubprocessJudgeModel(
        command=(sys.executable, "-c", script), root=root, timeout_s=timeout_s
    )


def _req(rubric_ref: str | None = None) -> JudgeRequest:
    return JudgeRequest(
        example_id="e1",
        metric="m.faithfulness",
        input="ctx",
        output={"a": 1},
        rubric_ref=rubric_ref,
    )


def test_scores_a_command_judge(tmp_path: Path) -> None:
    result = _judge(_OK, tmp_path).judge(_req())
    assert result.status is JudgeEvidenceStatus.OK
    assert result.parsed_value == 0.7
    assert result.rationale == "graded"


def test_accepts_the_score_key(tmp_path: Path) -> None:
    script = "import sys,json; sys.stdin.read(); print(json.dumps({'score':0.4}))"
    assert _judge(script, tmp_path).judge(_req()).parsed_value == 0.4


@pytest.mark.parametrize(("raw", "expected"), [(1.5, 1.0), (-0.3, 0.0), (0.25, 0.25)])
def test_clamps_to_unit_range(tmp_path: Path, raw: float, expected: float) -> None:
    script = f"import sys,json; sys.stdin.read(); print(json.dumps({{'value':{raw}}}))"
    assert _judge(script, tmp_path).judge(_req()).parsed_value == expected


def test_rubric_text_is_passed_to_the_judge(tmp_path: Path) -> None:
    (tmp_path / "rubrics").mkdir()
    (tmp_path / "rubrics" / "r.md").write_text("score the grounded fraction", encoding="utf-8")
    result = _judge(_ECHO_RUBRIC, tmp_path).judge(_req(rubric_ref="rubrics/r.md"))
    assert result.parsed_value == 1.0  # the child saw a non-empty rubric


def test_absent_rubric_is_tolerated(tmp_path: Path) -> None:
    # A judge metric may carry no rubric; the call still runs (empty rubric), never a hard fail.
    assert _judge(_ECHO_RUBRIC, tmp_path).judge(_req(rubric_ref=None)).parsed_value == 0.0


def test_rubric_path_escape_is_refused(tmp_path: Path) -> None:
    result = _judge(_OK, tmp_path).judge(_req(rubric_ref="../../etc/passwd"))
    assert result.status is JudgeEvidenceStatus.PROVIDER_ERROR
    assert result.parsed_value is None


def test_nonzero_exit_is_provider_error(tmp_path: Path) -> None:
    result = _judge("import sys; sys.exit(3)", tmp_path).judge(_req())
    assert result.status is JudgeEvidenceStatus.PROVIDER_ERROR
    assert result.parsed_value is None


def test_spawn_failure_is_provider_error(tmp_path: Path) -> None:
    model = SubprocessJudgeModel(command=("/nonexistent/evalglass-judge",), root=tmp_path)
    assert model.judge(_req()).status is JudgeEvidenceStatus.PROVIDER_ERROR


def test_timeout_is_timeout(tmp_path: Path) -> None:
    result = _judge("import time; time.sleep(5)", tmp_path, timeout_s=0.3).judge(_req())
    assert result.status is JudgeEvidenceStatus.TIMEOUT
    assert result.parsed_value is None


def test_malformed_stdout_is_malformed(tmp_path: Path) -> None:
    script = "print('not json at all')"
    result = _judge(script, tmp_path).judge(_req())
    assert result.status is JudgeEvidenceStatus.MALFORMED
    assert result.parsed_value is None


def test_non_finite_value_is_malformed(tmp_path: Path) -> None:
    # json.dumps(NaN) emits the non-standard token `NaN`, which the constant-rejector refuses.
    script = "import sys,json,math; sys.stdin.read(); print(json.dumps({'value':math.nan}))"
    assert _judge(script, tmp_path).judge(_req()).status is JudgeEvidenceStatus.MALFORMED


def test_boolean_value_is_malformed(tmp_path: Path) -> None:
    script = "import sys,json; sys.stdin.read(); print(json.dumps({'value':True}))"
    assert _judge(script, tmp_path).judge(_req()).status is JudgeEvidenceStatus.MALFORMED


def test_missing_value_is_malformed(tmp_path: Path) -> None:
    script = "import sys,json; sys.stdin.read(); print(json.dumps({'rationale':'no score'}))"
    assert _judge(script, tmp_path).judge(_req()).status is JudgeEvidenceStatus.MALFORMED
