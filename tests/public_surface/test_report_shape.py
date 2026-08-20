"""FS-SNAP-5 — freeze the Markdown report headline + shape (EG-AT1 Slice 2, EG-AT1-2).

The report is a *rendering* of the typed Scorecard: its headline verdict word must
equal the product verdict and never an unearned-success word. A synthesized report
whose headline outranks the Scorecard verdict must be detectable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.harness.report import MarkdownScoreSink
from tests.public_surface._normalize import (
    report_overclaim_words,
    report_structure,
    report_verdict_words,
)
from tests.scorecard_factory import informational_scorecard

_SNAP = Path(__file__).parent / "_snapshots"


def _load(name: str) -> dict[str, Any]:
    data = json.loads((_SNAP / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.mark.public_surface
def test_report_headline_and_sections_frozen(tmp_path: Path) -> None:
    md = MarkdownScoreSink().render(informational_scorecard(tmp_path))
    assert md.startswith("# EvalGlass Scorecard")
    assert report_structure(md) == _load("report_shape.json")


@pytest.mark.public_surface
def test_report_no_overclaim(tmp_path: Path) -> None:
    sc = informational_scorecard(tmp_path)
    md = MarkdownScoreSink().render(sc)
    # Exactly one verdict line, equal to the product verdict — no second headline.
    assert report_verdict_words(md) == [sc.verdict.verdict.value] == ["informational"]
    assert report_overclaim_words(md) == set()


@pytest.mark.public_surface
def test_report_replaced_headline_fails(tmp_path: Path) -> None:
    """Sensitivity: a headline claiming 'pass' over an informational run is caught."""
    sc = informational_scorecard(tmp_path)
    tampered = (
        MarkdownScoreSink().render(sc).replace("**Verdict:** informational", "**Verdict:** pass", 1)
    )
    assert report_verdict_words(tampered) != [sc.verdict.verdict.value]


@pytest.mark.public_surface
def test_report_appended_second_headline_fails(tmp_path: Path) -> None:
    """Sensitivity: an honest first line + an appended overclaiming verdict line is caught."""
    sc = informational_scorecard(tmp_path)
    sneaky = MarkdownScoreSink().render(sc) + "\n**Verdict:** pass — looks green\n"
    words = report_verdict_words(sneaky)
    assert words == ["informational", "pass"]
    assert words != [sc.verdict.verdict.value]


@pytest.mark.public_surface
def test_overclaim_detector_fires() -> None:
    """Specificity of the no-overclaim checker: real overclaim words are detected."""
    text = "**Verdict:** informational\nThis run is certified and safe and verified.\n"
    assert report_overclaim_words(text) == {"certified", "safe", "verified"}
