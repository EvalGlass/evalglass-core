"""Track B — ontology invariants map to real tests; status taxonomy is capability-only (EG-AT5-7).

Alignment plan §D 6F + 6G. Each modeled ``Invariant`` entity must map to a real, collectible
enforcing test (or be pinned as expected drift); the core trust laws must all be present; and the
``no-self-approval`` law must resolve into ``tests/harness/test_governance.py``. Separately, every
entity ``status`` is a capability-status value (``now``/``next``/``planned``/``experimental``),
provably disjoint from the run ``Verdict``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalglass.core.verdict import Verdict
from tests.ontology.ontology_loader import Ontology

pytestmark = pytest.mark.ontology

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Each modeled Invariant -> the test file that enforces it (all collectible, all present today).
_INVARIANT_TESTS: dict[str, str] = {
    "inv.byte-identical-verdicts": "tests/plugin/test_first_run_e2e.py",
    "inv.ci-should-fail": "tests/harness/test_exits.py",
    "inv.core-isolation": "tests/core_isolation/test_core_imports.py",
    "inv.deletion-invariant-tested": "tests/plugin/test_first_run_e2e.py",
    "inv.egress-before-effects": "tests/harness/test_data_policy.py",
    "inv.fail-closed-comparability": "tests/core/test_provenance.py",
    "inv.fresh-install-gates-nothing": "tests/installer/test_scaffold.py",
    "inv.incomplete-cannot-gate": "tests/core/test_authority.py",
    "inv.lanes-no-authority": "tests/harness/test_lane_governance.py",
    "inv.no-gate-verb": "tests/plugin/test_honesty_audit.py",
    "inv.no-self-approval": "tests/harness/test_governance.py",
    "inv.no-zero-enforced": "tests/core/test_scores.py",
    "inv.verdict-tamper-rejection": "tests/core/test_verdict.py",
}

#: The core trust laws that must all be modeled (plan §D 6F), by invariant id.
_REQUIRED_TRUST_LAWS = frozenset(
    {
        "inv.no-zero-enforced",  # no-0.0
        "inv.incomplete-cannot-gate",
        "inv.egress-before-effects",
        "inv.deletion-invariant-tested",  # deletion-invariance
        "inv.fail-closed-comparability",  # provenance-comparability
        "inv.no-self-approval",
        "inv.lanes-no-authority",  # capability-not-authority
    }
)

_CAPABILITY_STATUSES = frozenset({"now", "next", "planned", "experimental"})

#: The governance test family that concretely enforces no-self-approval (synthetic / benchmark /
#: annotation), beyond the canonical pinned file.
_GOVERNANCE_FAMILY = (
    "tests/harness/test_governance.py",
    "tests/harness/test_governance_synthetic.py",
    "tests/harness/test_governance_annotation.py",
    "tests/harness/test_governance_benchmark.py",
)

#: Ontology concepts for the capability-status axis, and the verdict-side entities they must not
#: link to (keeping capability status separate from a run outcome — §D 6G).
_STATUS_CONCEPTS = ("con.status-taxonomy", "con.capability-not-authority")


def _collectible(path_str: str) -> bool:
    path = _REPO_ROOT / path_str
    return path.is_file() and "def test_" in path.read_text(encoding="utf-8")


def test_every_invariant_maps_to_a_collectible_test(real_ontology: Ontology) -> None:
    modeled = {e.id for e in real_ontology.by_class("Invariant")}
    unmapped = modeled - set(_INVARIANT_TESTS)
    assert unmapped == set(), f"invariants with no enforcing-test mapping: {sorted(unmapped)}"
    for inv_id in sorted(modeled):
        assert _collectible(_INVARIANT_TESTS[inv_id]), (
            f"{inv_id} -> {_INVARIANT_TESTS[inv_id]} is not a collectible test"
        )


def test_core_trust_laws_are_all_present(real_ontology: Ontology) -> None:
    modeled = {e.id for e in real_ontology.by_class("Invariant")}
    missing = _REQUIRED_TRUST_LAWS - modeled
    assert missing == set(), f"core trust laws not modeled as invariants: {sorted(missing)}"


def test_no_self_approval_resolves_into_governance() -> None:
    assert _INVARIANT_TESTS["inv.no-self-approval"] == "tests/harness/test_governance.py"
    assert _collectible("tests/harness/test_governance.py")


def test_no_self_approval_is_enforced_by_the_governance_family() -> None:
    """The pinned file is the entry point; the law is concretely enforced across the family."""
    for path in _GOVERNANCE_FAMILY:
        assert _collectible(path), f"{path} is not a collectible governance test"
    # The canonical file actually asserts the three self-approval guards, not just any test.
    body = (_REPO_ROOT / "tests/harness/test_governance.py").read_text(encoding="utf-8")
    for guard in ("synthetic", "benchmark", "annotation"):
        assert guard in body, (
            f"the governance file does not enforce the {guard} self-approval guard"
        )


def test_thirteen_invariants_are_modeled(real_ontology: Ontology) -> None:
    assert len(real_ontology.by_class("Invariant")) == 13


# --- 6G status taxonomy -----------------------------------------------------
def test_entity_status_values_are_capability_status_only(real_ontology: Ontology) -> None:
    statuses = {e.status for e in real_ontology.entities}
    assert statuses <= _CAPABILITY_STATUSES, f"non-capability status value(s): {statuses}"


def test_capability_status_is_disjoint_from_verdict(real_ontology: Ontology) -> None:
    statuses = {e.status for e in real_ontology.entities}
    verdicts = {v.value for v in Verdict}
    assert statuses.isdisjoint(verdicts), (
        f"a status value collides with a Verdict: {statuses & verdicts}"
    )


def _verdict_entity_ids(ontology: Ontology) -> set[str]:
    """Every verdict-side entity (the run-outcome surface a capability status must not touch)."""
    return {e.id for e in ontology.entities if "verdict" in e.id}


def _status_to_verdict_edges(
    relations: object, verdict_ids: set[str]
) -> list[tuple[str, str, str]]:
    return [
        (r.predicate, r.src, r.dst)
        for r in relations  # type: ignore[attr-defined]
        if (r.src in _STATUS_CONCEPTS and r.dst in verdict_ids)
        or (r.dst in _STATUS_CONCEPTS and r.src in verdict_ids)
    ]


def test_no_relation_links_status_taxonomy_to_a_verdict(real_ontology: Ontology) -> None:
    """§6G: capability status is never wired to a run verdict / verdict payload."""
    verdict_ids = _verdict_entity_ids(real_ontology)
    assert verdict_ids, "expected verdict-side entities in the ontology"
    offending = _status_to_verdict_edges(real_ontology.relations, verdict_ids)
    assert offending == [], f"capability status is linked to a verdict: {offending}"


# --- negative controls ------------------------------------------------------
def test_an_unmapped_invariant_would_be_detected() -> None:
    """Sensitivity: a newly modeled invariant with no mapping fails the completeness check."""
    modeled = {"inv.no-self-approval", "inv.brand-new-unmapped-law"}
    assert not modeled <= set(_INVARIANT_TESTS)


def test_a_status_to_verdict_link_would_be_detected() -> None:
    """Sensitivity: a (doctored) edge from the status taxonomy to a verdict is caught."""
    from tests.ontology.ontology_loader import Relation

    doctored = [Relation(predicate="governs", src="con.status-taxonomy", dst="enum.verdict")]
    assert _status_to_verdict_edges(doctored, {"enum.verdict"}) != []
