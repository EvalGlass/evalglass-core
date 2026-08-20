"""EG-AT3-5 — quality-control positioning + canonical vocabulary (alignment plan §7.3, §7.4).

ST-POSN: the "AI quality-control" framing is present in the identity surfaces and never
carries a platform / keys / telemetry / guarantee connotation without an evidence-not-proof
prohibition. ST-VOCAB: banned architecture terms (kernel/…) are absent outside a prohibition,
canonical terms remain present, and the coding-agent command surface exposes no authority verb.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.plugin.lexicons import (
    BANNED_AUTHORITY_VERBS,
    CANONICAL_TERMS,
    has_execution_verb,
    has_future_marker,
)
from tests.plugin.prose_scan import (
    has_banned_architecture_term,
    logical_blocks,
    violates_platform_connotation,
    violates_unearned_success,
)
from tests.plugin.rendered_surfaces import audited_prose_files

pytestmark = pytest.mark.public_surface

_REPO = Path(__file__).resolve().parents[2]
_QUALITY_CONTROL = re.compile(r"quality[ -]control", re.IGNORECASE)

#: Identity surfaces that must carry the quality-control framing (CLAUDE.md is a hard exclusion).
_IDENTITY_SURFACES = [
    _REPO / "README.md",
    _REPO / "plugin-docs" / "vocabulary.md",
    _REPO / ".claude-plugin" / "plugin.json",
    _REPO / ".claude-plugin" / "marketplace.json",
    _REPO / ".codex-plugin" / "plugin.json",
    _REPO / "skills" / "evalglass" / "SKILL.md",
    _REPO / "docs" / "evalglass-product-architecture-current.html",
]


def _blocks(paths: list[Path]) -> Iterator[tuple[str, int, str]]:
    for path in paths:
        for start, block in logical_blocks(path.read_text(encoding="utf-8")):
            yield path.name, start, block


def _sentences(paths: list[Path]) -> Iterator[tuple[str, int, str]]:
    for name, start, block in _blocks(paths):
        for sentence in re.split(r"[.;!]\s", block):
            yield name, start, sentence


# --------------------------------------------------------------------------- ST-POSN-1


def test_quality_control_framing_in_identity_surfaces() -> None:
    missing = [p.name for p in _IDENTITY_SURFACES if not _QUALITY_CONTROL.search(p.read_text())]
    assert missing == [], f"identity surfaces missing the quality-control framing: {missing}"


# --------------------------------------------------------------------------- ST-POSN-2


def test_quality_control_framing_has_no_platform_or_guarantee_connotation() -> None:
    offenders = [
        f"{name}:{lineno}"
        for name, lineno, sentence in _sentences(audited_prose_files())
        if violates_platform_connotation(sentence)
    ]
    assert offenders == []


# --------------------------------------------------------------------------- ST-VOCAB-2


def test_banned_architecture_terms_absent_outside_a_prohibition() -> None:
    """Scanned per logical block, so a prohibition that wraps across lines still exempts."""
    offenders = [
        f"{name}:{lineno}"
        for name, lineno, block in _blocks(audited_prose_files())
        if has_banned_architecture_term(block)
    ]
    assert offenders == []


# --------------------------------------------------------------------------- ST-VOCAB-3


def test_unearned_success_words_carry_a_prohibition() -> None:
    offenders = [
        f"{name}:{lineno}:{sentence.strip()[:60]}"
        for name, lineno, sentence in _sentences(audited_prose_files())
        if violates_unearned_success(sentence)
    ]
    assert offenders == []


# --------------------------------------------------------------------------- ST-VOCAB-4


def test_canonical_terms_remain_present() -> None:
    corpus = " ".join(p.read_text(encoding="utf-8").lower() for p in audited_prose_files())
    missing = [term for term in CANONICAL_TERMS if term not in corpus]
    assert missing == [], f"canonical terms missing from the prose surfaces: {missing}"


def _command_names(surface: object) -> set[str]:
    """Recursively collect every (sub)command name from the parsed CLI help surface."""
    names: set[str] = set()
    if isinstance(surface, dict):
        commands = surface.get("commands")
        if isinstance(commands, dict):
            for name, sub in commands.items():
                names.add(str(name).lower())
                names |= _command_names(sub)
    return names


def test_command_surface_exposes_no_authority_verb() -> None:
    """The live CLI verbs never include an authority verb (gate/approve/certify)."""
    surface = json.loads(
        (_REPO / "tests" / "public_surface" / "_snapshots" / "cli_help_surface.json").read_text(
            encoding="utf-8"
        )
    )
    names = _command_names(surface)
    assert names, "expected at least one CLI command in the surface"
    banned = {verb.strip() for verb in BANNED_AUTHORITY_VERBS}
    offenders = sorted(names & banned)
    assert offenders == [], f"command surface exposes authority verb(s): {offenders}"


# ----------------------------------------------------------- W2: detector sensitivity controls
# Each ST-POSN/ST-VOCAB guard above proves the *production* surfaces are clean (specificity). These
# negative controls prove the SAME detector FIRES on a doctored violation — the sensitivity half the
# doctrine requires (alignment plan §7: every detector ships sensitivity + specificity).


def test_sensitivity_posn1_missing_framing_is_detected() -> None:
    """ST-POSN-1: a surface with no quality-control framing is detected by the framing check."""
    assert _QUALITY_CONTROL.search("evalglass is an evaluation tool") is None


def test_sensitivity_posn2_platform_connotation_is_flagged() -> None:
    """ST-POSN-2: a QC + platform sentence is flagged without a prohibition, cleared with one."""
    assert violates_platform_connotation(
        "evalglass is a quality-control hosted platform with telemetry"
    )
    assert not violates_platform_connotation(
        "evalglass is a quality-control tool, not a hosted platform — evidence, not proof"
    )


def test_sensitivity_vocab2_banned_term_is_flagged() -> None:
    """ST-VOCAB-2: a bare banned term is flagged; a prohibition that forbids it exempts."""
    assert has_banned_architecture_term("the pure kernel runs the evaluation")
    assert not has_banned_architecture_term("never use 'kernel'; say 'Evaluation Core' instead")


def test_sensitivity_vocab3_unearned_success_is_flagged() -> None:
    """ST-VOCAB-3: an unearned-success word is flagged; an evidence-not-proof prohibition clears."""
    assert violates_unearned_success("a green scorecard is certified proof of correctness")
    assert not violates_unearned_success(
        "a green scorecard is evidence, not proof — never certified"
    )


def test_sensitivity_vocab4_missing_canonical_term_is_detected() -> None:
    """ST-VOCAB-4: a corpus missing a canonical term is detected."""
    missing = [term for term in CANONICAL_TERMS if term not in "prose without the vocabulary"]
    assert missing  # the detector fires when canonical terms are absent


# ----------------------------------------------------------- EG-H5-5: deferred-connector honesty


#: The deferred live trace connectors that must read as not-built wherever they are named.
_LIVE_CONNECTORS = ("langfuse", "phoenix", "langsmith")
#: Words that, in a connector sentence, assert it is already implemented/available now.
_IMPLEMENTED_NOW = ("implemented", "available now", "ships today", "shipped", "runs today")


def test_governance_doc_defers_live_connectors() -> None:
    """Scoped per connector *sentence*: every sentence naming Langfuse/Phoenix/LangSmith that
    describes it executing or being implemented must carry a deferral / future marker — so the doc
    can never claim a real provider pull is implemented this tranche (EG-H5-5)."""
    text = (_REPO / "docs" / "EXTENSION_GOVERNANCE.md").read_text(encoding="utf-8")
    mentioned: set[str] = set()
    offenders: list[str] = []
    for _start, block in logical_blocks(text):
        for sentence in re.split(r"[.;!]\s", block):
            lowered = sentence.lower()
            vendors = [v for v in _LIVE_CONNECTORS if v in lowered]
            if not vendors:
                continue
            mentioned.update(vendors)
            now_claim = has_execution_verb(sentence) or any(w in lowered for w in _IMPLEMENTED_NOW)
            if now_claim and not has_future_marker(sentence):
                offenders.append(sentence.strip()[:80])
    assert mentioned == set(_LIVE_CONNECTORS), f"a live connector is not even named: {mentioned}"
    assert offenders == [], f"a connector sentence overclaims implementation/execution: {offenders}"


def test_sensitivity_connector_overclaim_is_detected() -> None:
    """Negative control: a connector sentence claiming implementation/execution with no deferral
    marker is detectably wrong — and a deferral marker clears it (the guard has teeth)."""
    overclaim = "Langfuse provider pulls are implemented now"
    lowered = overclaim.lower()
    now_claim = has_execution_verb(overclaim) or any(w in lowered for w in _IMPLEMENTED_NOW)
    assert now_claim
    assert not has_future_marker(overclaim)  # the production guard flags exactly this shape
    assert has_future_marker("Langfuse pulls are not built — deferred to a later workbook")
