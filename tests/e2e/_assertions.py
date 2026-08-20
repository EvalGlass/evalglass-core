"""The cross-journey no-false-green helper (EG-AT6-11; alignment plan §8.19).

``assert_no_false_green`` is the single guard every reporting e2e calls at its tail. It refuses a
result that claims more than the run earned:

1. the rendered run verdict equals the Scorecard verdict (no stronger token);
2. unearned-success vocabulary is absent from stdout / report.md;
3. every non-scored score carries a null value, never a fabricated ``0.0``;
4. the exit code is the one derived from ``ci_should_fail`` (0 / 1);
5. the Scorecard carries exactly one verdict.
"""

from __future__ import annotations

import re

from tests.egts.host_repo import CliResult
from tests.plugin.lexicons import UNEARNED_SUCCESS_WORDS

#: Unearned-success vocabulary a product surface must never apply to a run/result. Sourced from the
#: shared honesty lexicon (single source of truth) — includes ``certify`` *and* ``certified``.
_FORBIDDEN_SURFACE_WORDS = tuple(sorted(UNEARNED_SUCCESS_WORDS))
#: Negation tokens that, *immediately preceding* a forbidden word, make it a prohibition.
_NEGATIONS = ("not ", "no ", "never ", "without ", "cannot ", "isn't ", "aren't ")
_VERDICT_RE = re.compile(r"verdict[:=]\s*([a-z_]+)")


def assert_no_false_green(result: CliResult) -> None:
    scorecard = result.scorecard
    assert scorecard is not None, "a reporting run produced no Scorecard"
    verdict = scorecard["verdict"]["verdict"]
    surfaces = (result.stdout, result.report or "")

    # (1) EVERY rendered run verdict — across stdout and the report — echoes the Scorecard verdict.
    for surface in surfaces:
        for match in _VERDICT_RE.finditer(surface.lower()):
            assert match.group(1) == verdict, (
                f"a surface renders verdict {match.group(1)!r}, Scorecard says {verdict!r}"
            )

    # (2) no unearned-success vocabulary, unless that occurrence is directly negated.
    for surface in surfaces:
        lowered = surface.lower()
        for word in _FORBIDDEN_SURFACE_WORDS:
            for occurrence in re.finditer(re.escape(word), lowered):
                preceding = lowered[max(0, occurrence.start() - 12) : occurrence.start()]
                if any(neg in preceding for neg in _NEGATIONS):
                    continue  # e.g. "not production-ready"
                raise AssertionError(f"surface overclaims with {word!r}")

    # (3) a non-scored score never fabricates a value.
    if result.runrecord is not None:
        for score in result.runrecord["scores"]:
            if score["status"] != "scored":
                assert score["value"] is None, (
                    f"{score.get('metric')} non-scored example fabricated value {score['value']!r}"
                )

    # (4) the exit code is exactly the one ci_should_fail derives.
    ci_should_fail = scorecard["verdict"]["ci_should_fail"]
    expected_exit = 1 if ci_should_fail else 0
    assert result.exit_code == expected_exit, (
        f"exit {result.exit_code} disagrees with ci_should_fail={ci_should_fail}"
    )

    # (5) the Scorecard carries exactly one verdict value.
    assert isinstance(verdict, str)
    assert verdict, "the Scorecard does not carry a single verdict"
