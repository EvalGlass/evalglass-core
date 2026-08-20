"""EG-AT4-1 — runner-attach seam: current truth + post-seam contract (alignment plan §C.0, §5.0).

The runner-attach seam does not exist yet (the frozen ``test_lane_attach.py`` canary asserts the
current truth: ``runner.py`` references no lane symbol). This guard adds the *post-seam* contract
that holds whether or not the seam lands: a ``LaneResult`` may fold into the ``RunRecord`` as a
side channel, but it must never be passed into verdict / authority / Scorecard construction — a
lane informs, it never decides. The sensitivity/specificity synthetic runners prove the AST check
fires on a leaky runner and stays quiet on a side-channel-only one.
"""

from __future__ import annotations

import ast
from pathlib import Path

_RUNNER = Path(__file__).resolve().parents[2] / "src" / "evalglass" / "harness" / "runner.py"

#: Constructors/resolvers that turn measurement into a run outcome. A lane result reaching any of
#: these would be a second, hidden verdict path.
_VERDICT_SINKS = frozenset(
    {"verdict", "Verdict", "VerdictPayload", "resolve_authority", "ResolvedAuthority", "Scorecard"}
)

_LANE_RESULT_HINTS = ("lane_result", "lane_results")

#: Seeds: an expression mentioning any of these *originates* a lane value. Lane-ness then
#: propagates through assignments (so ``reg = built_in_lanes(); r = reg.resolve("x").run()`` marks
#: both ``reg`` and ``r``), tracking dataflow rather than a hard-coded variable name.
_LANE_SOURCE_NAMES = frozenset({"built_in_lanes", "LaneResult", "LaneRegistry", "ExtensionLane"})

_LEAKY_RUNNER = """
def run_config(cfg, root):
    result = built_in_lanes().resolve("x").run(cfg)
    payload = VerdictPayload(verdict=result.report, ci_should_fail=False)
    return payload
"""

_SIDE_CHANNEL_RUNNER = """
def run_config(cfg, root):
    record = build_record(cfg)
    lane_result = built_in_lanes().resolve("x").run(cfg)
    record.lane_results.append(lane_result.to_dict())  # side channel only
    return record
"""


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _expr_originates_lane(expr: ast.AST, lane_vars: set[str]) -> bool:
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and _call_name(node) in _LANE_SOURCE_NAMES:
            return True
        if isinstance(node, ast.Name) and (node.id in lane_vars or node.id in _LANE_SOURCE_NAMES):
            return True
        if isinstance(node, ast.Name) and any(h in node.id for h in _LANE_RESULT_HINTS):
            return True
    return False


def _lane_vars(tree: ast.AST) -> set[str]:
    """Variables that hold a lane value — seeded from lane sources, propagated to a fixpoint."""
    lane_vars: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            value = getattr(node, "value", None)
            if not isinstance(node, ast.Assign | ast.AnnAssign) or value is None:
                continue
            if not _expr_originates_lane(value, lane_vars):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in lane_vars:
                    lane_vars.add(target.id)
                    changed = True
    return lane_vars


def _lane_result_reaches_verdict(source: str) -> bool:
    """True if a lane-derived value is passed into a verdict/authority/Scorecard call."""
    tree = ast.parse(source)
    lane_vars = _lane_vars(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in _VERDICT_SINKS:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and (
                    inner.id in lane_vars or any(h in inner.id for h in _LANE_RESULT_HINTS)
                ):
                    return True
    return False


def _references_seam(source: str) -> bool:
    return "built_in_lanes" in source or "LaneResult" in source


def test_runner_never_passes_a_lane_result_into_the_verdict() -> None:
    """Holds pre-seam (no lane symbols) and post-seam (lane results stay a side channel)."""
    source = _RUNNER.read_text(encoding="utf-8")
    assert not _lane_result_reaches_verdict(source)
    # Current truth: the seam is absent, so the obligation is not-exercised, not a pass.
    if not _references_seam(source):
        assert "built_in_lanes" not in source


def test_sensitivity_leaky_runner_folding_lane_result_into_verdict_fires() -> None:
    assert _lane_result_reaches_verdict(_LEAKY_RUNNER)


def test_specificity_side_channel_lane_result_stays_quiet() -> None:
    assert not _lane_result_reaches_verdict(_SIDE_CHANNEL_RUNNER)
