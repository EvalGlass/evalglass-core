"""Track B — bidirectional master guard + path-state reporting (EG-AT5-8; alignment plan §D 6H).

The master guard closes the loop so the drift guard cannot stay green over an unmapped live enum:

* **code → ontology:** every live ``Enum`` reachable under ``core/`` + ``harness/exits`` +
  ``harness/lanes`` is either *mapped* to an ontology enum or listed in an explicit, committed
  exception set — a newly added live enum that is neither fails;
* **ontology → code:** every ontology ``Enum`` entity maps to a real live enum;
* **path state is always reported:** the real artifact is exercised when present, and reported as a
  visible NOT EXERCISED skip when absent — never a silent pass over zero entities.

After the site artifact is remediated (modeling the currently-unmodeled enums), the exception set
shrinks; an entry that becomes modeled or disappears from code is caught here.
"""

from __future__ import annotations

import pytest

from tests.ontology.enum_drift import ONTOLOGY_TO_LIVE, discover_live_enums
from tests.ontology.ontology_loader import Ontology, artifact_path, load_real_ontology

pytestmark = pytest.mark.ontology

#: Live enums the ontology *does* model (the 9 Enum entities), by live class name.
_MAPPED_LIVE = frozenset(ONTOLOGY_TO_LIVE.values())

#: Live enums deliberately NOT modeled as ontology entities yet — the explicit drift exception.
#: Shrinks as the site artifact adds entities; a new live enum must be mapped or added here.
_UNMODELED_LIVE_ENUMS = frozenset(
    {
        # EG-H1 modeled ThresholdApproval / JudgeCalibration / LanePort / LaneStatus / Maturity;
        # the rest remain honestly unmodeled (out of scope for this reconciliation tranche).
        "Aggregation",
        "ComparisonPurpose",  # D4: baseline comparison purpose; not modeled in the site artifact
        "DecisionStatistic",  # M7 T2: decision-statistic selector; not in the site artifact yet
        "DeltaOutcome",  # M7 T5: paired-comparison outcome; not modeled in the site artifact yet
        "Direction",
        "GrantStatus",  # M7 T3: digest-bound grant verification status; not modeled yet
        "IntervalMethod",  # M7 T1: interval estimator method; not modeled in the site artifact yet
        "JudgeCapability",  # M7 T3: judge capability (fake vs measurement); not modeled yet
        "JudgeEvidenceStatus",
        "Lens",
        "ScoreType",
        "Severity",
        "UnitKind",
    }
)


def test_mapped_and_unmodeled_exception_sets_are_disjoint() -> None:
    assert _MAPPED_LIVE.isdisjoint(_UNMODELED_LIVE_ENUMS)


def test_every_live_enum_is_mapped_or_an_explicit_exception() -> None:
    """code → ontology completeness: no live enum is silently untracked."""
    discovered = set(discover_live_enums())
    accounted = _MAPPED_LIVE | _UNMODELED_LIVE_ENUMS
    unaccounted = discovered - accounted
    assert unaccounted == set(), f"live enum(s) neither mapped nor excepted: {sorted(unaccounted)}"
    stale_exceptions = accounted - discovered
    assert stale_exceptions == set(), (
        f"mapped/excepted enum no longer in code: {sorted(stale_exceptions)}"
    )


def test_every_ontology_enum_entity_is_mapped(real_ontology: Ontology) -> None:
    """ontology → code: every ``Enum`` entity in the artifact has a mapping (no unmapped entity).

    Iterates the real artifact's ``Enum`` entities — so a newly added or renamed ontology enum that
    nobody added to ``ONTOLOGY_TO_LIVE`` is caught, not silently ignored.
    """
    entity_ids = {e.id for e in real_ontology.by_class("Enum")}
    unmapped = entity_ids - set(ONTOLOGY_TO_LIVE)
    assert unmapped == set(), f"ontology Enum entities with no live mapping: {sorted(unmapped)}"
    stale = set(ONTOLOGY_TO_LIVE) - entity_ids
    assert stale == set(), f"mapping references absent Enum entities: {sorted(stale)}"


def test_every_mapped_ontology_enum_points_at_a_live_enum() -> None:
    """Each mapping target is a real, discovered live enum."""
    discovered = set(discover_live_enums())
    for ontology_enum, live_name in ONTOLOGY_TO_LIVE.items():
        assert live_name in discovered, f"{ontology_enum} maps to absent live enum {live_name!r}"


def test_ontology_path_state_is_reported() -> None:
    """The artifact path state is always visible: exercised when present, skipped when absent."""
    path = artifact_path()
    if path is None:
        pytest.skip(
            "NOT EXERCISED — no ontology artifact at EVALGLASS_ONTOLOGY or the in-repo copy"
        )
    assert path.is_file()
    ontology = load_real_ontology()
    assert isinstance(ontology, Ontology)


# --- negative controls ------------------------------------------------------
def test_a_new_unaccounted_live_enum_would_be_detected() -> None:
    """Sensitivity: a live enum absent from both the mapped and exception sets is flagged."""
    discovered = set(discover_live_enums()) | {"BrandNewUnmappedEnum"}
    accounted = _MAPPED_LIVE | _UNMODELED_LIVE_ENUMS
    assert discovered - accounted == {"BrandNewUnmappedEnum"}


def test_a_stale_exception_would_be_detected() -> None:
    """Sensitivity: an exception for an enum no longer in code is flagged as stale."""
    discovered = set(discover_live_enums())
    accounted = _MAPPED_LIVE | _UNMODELED_LIVE_ENUMS | {"RemovedEnum"}
    assert accounted - discovered == {"RemovedEnum"}
