"""scenario_checker family (VG-P1-5).

EGTS proves behavior; it must never compute product verdict meaning. This family
validates EGTS evidence (scenarios, checker outputs) — it never executes EGTS.
Content conventions on EGTS artifacts:

- a scenario carries ``authored_expectation`` (a declared expected value) and
  ``scenario_version`` (linkage);
- ``derived_from_output: true`` marks a post-hoc expectation (the scenario
  accepted whatever the product emitted);
- ``decides_verdict: true`` / ``acts_as: product`` assert the artifact decides
  the run — a boundary violation for EGTS evidence.

Outcomes:
- FAIL: an EGTS scenario/checker is cited as product authority; a scenario
  expectation is post-hoc.
- BLOCKED: no evidence; no scenario/checker present; missing authored
  expectation; missing scenario-version linkage; a required-suite claim with no
  checker evidence.
- PASS: an authored, versioned scenario with EGTS output used only as evidence.
"""

from __future__ import annotations

from typing import Any

from scripts.contracts import ArtifactKind, Authority, FamilyFinding, FamilyId, Status
from scripts.families.base import FamilyContext, finding, probe

RISK_REF = "scenario_expectation"

# Surfaces that specifically concern an authored scenario contract (not just a
# checker run): such a claim must be backed by a scenario artifact.
_SCENARIO_SURFACES = {"scenario", "authored_expectation", "fixture", "egts_expectation"}


def _block(ctx: FamilyContext, reason: str, remediation: str) -> list[FamilyFinding]:
    return [
        finding(
            ctx,
            FamilyId.SCENARIO_CHECKER,
            Status.BLOCKED,
            reason=reason,
            remediation=remediation,
            risk_ref=RISK_REF,
        )
    ]


def _fail(
    ctx: FamilyContext, reason: str, remediation: str, evidence_refs: list[str]
) -> list[FamilyFinding]:
    return [
        finding(
            ctx,
            FamilyId.SCENARIO_CHECKER,
            Status.FAIL,
            reason=reason,
            remediation=remediation,
            evidence_refs=evidence_refs,
            risk_ref=RISK_REF,
        )
    ]


def _decides(content: dict[str, Any] | None) -> bool:
    return probe(content, "decides_verdict") is True or probe(content, "acts_as") in {
        "product",
        "canonical",
    }


def validate(ctx: FamilyContext) -> list[FamilyFinding]:
    required = list({a.id: a for a in ctx.index.required_artifacts(ctx.claim.id)}.values())
    if not required:
        return _block(
            ctx,
            "scenario_checker claim has no required artifacts to inspect",
            "Declare the scenario/checker artifacts this claim depends on.",
        )
    surfaces = {str(s).strip().lower() for s in ctx.claim.risk_surfaces}
    scenarios = [a for a in required if a.kind is ArtifactKind.SCENARIO]
    checkers = [a for a in required if a.kind is ArtifactKind.CHECKER_OUTPUT]

    # Scenario/checker evidence is the EGTS side of the boundary: it must carry
    # EGTS authority, not be mislabeled as product (or any other) authority.
    mislabeled = sorted(a.id for a in scenarios + checkers if a.authority is not Authority.EGTS)
    if mislabeled:
        return _fail(
            ctx,
            f"scenario/checker evidence {mislabeled} carries non-EGTS authority",
            "Scenario and checker artifacts are EGTS evidence; declare them under EGTS authority.",
            mislabeled,
        )

    # EGTS evidence must not be cited as product authority / decide the verdict.
    usurpers = sorted(
        a.id for a in required if a.authority is Authority.EGTS and _decides(a.content)
    )
    if usurpers:
        return _fail(
            ctx,
            f"EGTS scenario/checker output {usurpers} is cited as product authority",
            "EGTS proves behavior; the product Verdict Engine decides the verdict.",
            usurpers,
        )

    if not scenarios and not checkers:
        return _block(
            ctx,
            "no scenario or checker evidence is present to validate the EGTS claim",
            "Include the scenario and/or checker-output artifacts the claim covers.",
        )

    # A claim about an authored scenario contract must carry a scenario artifact.
    if surfaces & _SCENARIO_SURFACES and not scenarios:
        return _block(
            ctx,
            "claim concerns a scenario contract but no scenario artifact is present",
            "Include the scenario artifact (authored expectation + version) the claim covers.",
        )

    # A scenario expectation must be authored, not derived from product output.
    posthoc = sorted(a.id for a in scenarios if probe(a.content, "derived_from_output") is True)
    if posthoc:
        return _fail(
            ctx,
            f"scenario(s) {posthoc} accept a post-hoc expectation derived from product output",
            "Author the expected value independently of what the product emitted.",
            posthoc,
        )

    unauthored = sorted(a.id for a in scenarios if probe(a.content, "authored_expectation") is None)
    if unauthored:
        return _block(
            ctx,
            f"scenario(s) {unauthored} have no authored expectation",
            "Declare the authored expected value for each scenario.",
        )

    unlinked = sorted(a.id for a in scenarios if probe(a.content, "scenario_version") is None)
    if unlinked:
        return _block(
            ctx,
            f"scenario(s) {unlinked} have no scenario-version linkage",
            "Record the scenario version so the expectation is traceable.",
        )

    if "required_suite" in surfaces and not checkers:
        return _block(
            ctx,
            "required-suite claim has no checker-output evidence",
            "Include the required-suite checker outputs proving the suite ran.",
        )

    return [
        finding(
            ctx,
            FamilyId.SCENARIO_CHECKER,
            Status.PASS,
            reason="EGTS scenarios are authored and versioned; "
            "checker output is used only as evidence",
            evidence_refs=sorted(a.id for a in required),
        )
    ]
