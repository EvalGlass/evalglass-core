"""evidence_provenance family (VG-P1-4).

Validates that baseline/regression, deletion/retention, reproducibility, and
derived-artifact claims trace to current, typed records. Content conventions:

- a baseline carries ``state``: ``comparable`` / ``not_comparable`` /
  ``missing_baseline`` / ``comparison_not_requested``;
- a derived artifact carries ``derived: true`` plus either inline ``provenance``
  or a provenance-kind artifact among the evidence;
- a run_record/baseline may carry a comparable ``timestamp``;
- deletion/retention claims carry ``deleted`` / ``retained`` booleans.

Outcomes:
- FAIL: a regression claim cites a non-comparable baseline; a deletion/retention
  claim is contradicted by present evidence; a derived artifact is primary
  evidence without provenance.
- BLOCKED: no evidence; a regression claim with no/missing baseline; baselines
  in an unknown state; or contradictory timestamps.
- PASS: comparable baseline + current records; derived artifacts have provenance.
"""

from __future__ import annotations

from scripts.contracts import ArtifactKind, ArtifactRef, FamilyFinding, FamilyId, Status
from scripts.families.base import FamilyContext, finding, probe

RISK_REF = "provenance_baseline"

# A regression/baseline-improvement claim needs a comparable baseline.
# Reproducibility is a separate surface backed by run/provenance, not a baseline.
_REGRESSION_SURFACES = {"regression", "baseline"}
_BASELINE_MISSING = {"missing_baseline", "missing"}
_BASELINE_STATES = {"comparable", "comparison_not_requested", "not_comparable"} | _BASELINE_MISSING


def _block(ctx: FamilyContext, reason: str, remediation: str) -> list[FamilyFinding]:
    return [
        finding(
            ctx,
            FamilyId.EVIDENCE_PROVENANCE,
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
            FamilyId.EVIDENCE_PROVENANCE,
            Status.FAIL,
            reason=reason,
            remediation=remediation,
            evidence_refs=evidence_refs,
            risk_ref=RISK_REF,
        )
    ]


def _has_provenance(art: ArtifactRef, required: list[ArtifactRef]) -> bool:
    if probe(art.content, "provenance"):
        return True
    return any(a.kind is ArtifactKind.PROVENANCE for a in required)


def validate(ctx: FamilyContext) -> list[FamilyFinding]:
    required = list({a.id: a for a in ctx.index.required_artifacts(ctx.claim.id)}.values())
    if not required:
        return _block(
            ctx,
            "evidence_provenance claim has no required artifacts to inspect",
            "Declare the run/baseline/provenance records this claim depends on.",
        )
    surfaces = {str(s).strip().lower() for s in ctx.claim.risk_surfaces}

    # Derived artifacts may not be primary evidence without provenance.
    unprovenanced = sorted(
        a.id
        for a in required
        if probe(a.content, "derived") is True and not _has_provenance(a, required)
    )
    if unprovenanced:
        return _fail(
            ctx,
            f"derived artifact(s) {unprovenanced} are used as evidence without a provenance record",
            "Attach a provenance record (or inline provenance) for any derived artifact.",
            unprovenanced,
        )

    # Deletion/retention claims must not be contradicted by present evidence.
    # Check the boolean specific to the claim: a deletion claim is contradicted
    # by deleted=False (still present); a retention claim by retained=False.
    contradicting: set[str] = set()
    if "deletion" in surfaces:
        contradicting |= {a.id for a in required if probe(a.content, "deleted") is False}
    if "retention" in surfaces:
        contradicting |= {a.id for a in required if probe(a.content, "retained") is False}
    if contradicting:
        ids = sorted(contradicting)
        return _fail(
            ctx,
            f"deletion/retention claim is contradicted by present evidence {ids}",
            "Reconcile the claim with the records, or remove the contradicting evidence.",
            ids,
        )

    # Baseline / regression handling.
    baselines = [a for a in required if a.kind is ArtifactKind.BASELINE]
    regression = bool(surfaces & _REGRESSION_SURFACES)
    if regression and not baselines:
        return _block(
            ctx,
            "regression/baseline claim has no baseline record to compare against",
            "Include the comparable baseline record the claim relies on.",
        )
    for base in baselines:
        state = probe(base.content, "state")
        if state not in _BASELINE_STATES:
            return _block(
                ctx,
                f"baseline {base.id!r} has an unrecognized comparability state {state!r}",
                "Record a known baseline state (comparable / not_comparable / missing_baseline).",
            )
        if state in _BASELINE_MISSING:
            return _block(
                ctx,
                f"baseline {base.id!r} is missing; a regression claim cannot be made",
                "Establish a comparable baseline before claiming a regression result.",
            )
        if regression and state == "not_comparable":
            return _fail(
                ctx,
                f"baseline {base.id!r} is non-comparable but is used as regression proof",
                "Only a comparable baseline can support a regression/improvement claim.",
                [base.id],
            )
        if regression and state == "comparison_not_requested":
            return _block(
                ctx,
                f"baseline {base.id!r} records no comparison; it cannot support a regression claim",
                "Run a comparable baseline comparison before claiming a regression result.",
            )

    # Timestamp sanity: a baseline must not be newer than the earliest run it
    # backs. Compare against min(run timestamps) so the result is independent of
    # artifact order even when several run records are present.
    run_tss = [
        probe(a.content, "timestamp")
        for a in required
        if a.kind is ArtifactKind.RUN_RECORD and probe(a.content, "timestamp") is not None
    ]
    for base in baselines:
        base_ts = probe(base.content, "timestamp")
        if base_ts is None:
            continue
        comparable_runs = [ts for ts in run_tss if type(ts) is type(base_ts)]
        if comparable_runs and base_ts > min(comparable_runs):
            return _block(
                ctx,
                f"baseline {base.id!r} timestamp is newer than the run it backs "
                "(contradictory records)",
                "Use a baseline recorded no later than the run under comparison.",
            )

    return [
        finding(
            ctx,
            FamilyId.EVIDENCE_PROVENANCE,
            Status.PASS,
            reason="claims trace to current typed records "
            "(comparable baselines, provenanced artifacts)",
            evidence_refs=sorted(a.id for a in required),
        )
    ]
