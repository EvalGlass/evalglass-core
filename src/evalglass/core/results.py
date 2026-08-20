"""RunRecord and Scorecard — the primary machine artifacts (EG-M0-6a).

``Scorecard`` is the authority-aware summary of a run (verdict, per-metric
aggregates, per-metric resolved authority, baseline state, diagnostics).
``RunRecord`` is the complete persisted record (scorecard + every individual score
+ provenance + comparability). Both are JSON-primary (``CLAUDE.md §4`` #6) and
compose the already-built contracts rather than redefining their meaning.
Effect-free, stdlib-only.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import (
    ContractError,
    _as_mapping,
    _coerce_enum,
    _opt_list,
    _require,
    _require_mapping,
)
from evalglass.core.aggregation import AggregatedMetric, aggregate
from evalglass.core.authority import ResolvedAuthority
from evalglass.core.claim_spec import ClaimSpec
from evalglass.core.clusters import DiagnosticCluster, cluster
from evalglass.core.comparison import ComparisonResult
from evalglass.core.contracts import Diagnostic, JudgeEvidence, JudgeEvidenceStatus
from evalglass.core.estimate import Estimate
from evalglass.core.population import PopulationSummary
from evalglass.core.provenance import BaselineState, ComparableRunFingerprint, RunFingerprint
from evalglass.core.scores import Score, aggregatable
from evalglass.core.verdict import VerdictPayload


@dataclass(frozen=True)
class Scorecard:
    """Authority-aware run summary; report wording must be backed by these fields."""

    verdict: VerdictPayload
    metrics: list[AggregatedMetric]
    authority: dict[str, ResolvedAuthority]
    baseline_state: BaselineState | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    # Additive (M7 T1/T2): per-metric point + honest interval + n_effective. Emitted only
    # when non-empty, so a pre-M7 scorecard (no estimates) stays byte-identical and an
    # absent field parses to []. The point never disagrees with the matching metric value
    # (both derive from aggregate()); the interval is the new decision-grade uncertainty.
    estimates: list[Estimate] = field(default_factory=list)
    # Additive (M7 G10): optional per-metric construct/validity arguments (host-owned truth,
    # attached by the harness — the engine never sets it, so a computed scorecard stays
    # byte-identical). Carries no gating power; it makes the claim narrower when absent.
    claim_specs: dict[str, ClaimSpec] = field(default_factory=dict)
    # Additive (P3; ADR 0047): per-(metric, diagnostic.code) failure clusters, grouping the run's
    # failing/non-scored items by shared cause. A pure projection of the raw scores (recomputed by
    # _verify_consistency), so it is anti-tamper-safe and a pre-P3 scorecard (no clusters) stays
    # byte-identical. Explanatory structure only — it carries no value and no authority.
    clusters: list[DiagnosticCluster] = field(default_factory=list)
    # Additive (Epic D / D3): per-metric population accounting -- the pre-effect coverage
    # (available/selector-matched/eligible from the plan) plus terminal measurement states (scored/
    # non_evaluable/blocked/skipped/error from the raw scores). The terminal layer is a verified
    # projection recomputed by _verify_consistency; the pre-effect layer is Harness-supplied and
    # stays unknown (never zero) on a record without it. Emitted only when non-empty, so a scorecard
    # without population accounting stays byte-identical. Coverage, never a quality composite.
    populations: list[PopulationSummary] = field(default_factory=list)
    # Additive (Epic D / D4): the run's typed, comparability-qualified comparison against its
    # baseline -- purpose/state, changed fingerprint dimensions, and (only when comparable) the
    # per-metric paired deltas. The single primary carrier of honest change: a renderer reads this,
    # never a raw previous-value subtraction. Evidence, never a verdict -- it sets no exit. Present
    # only when a baseline comparison was computed, so a run without one stays byte-identical.
    comparison: ComparisonResult | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "verdict": self.verdict.to_dict(),
            "metrics": [m.to_dict() for m in self.metrics],
            "authority": {k: v.to_dict() for k, v in self.authority.items()},
        }
        if self.baseline_state is not None:
            out["baseline_state"] = self.baseline_state.value
        if self.diagnostics:
            out["diagnostics"] = [d.to_dict() for d in self.diagnostics]
        if self.estimates:
            out["estimates"] = [e.to_dict() for e in self.estimates]
        if self.claim_specs:
            out["claim_specs"] = {k: v.to_dict() for k, v in self.claim_specs.items()}
        if self.clusters:
            out["clusters"] = [c.to_dict() for c in self.clusters]
        if self.populations:
            out["populations"] = [p.to_dict() for p in self.populations]
        if self.comparison is not None:
            out["comparison"] = self.comparison.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "Scorecard")
        authority_raw = _require(m, "authority", "Scorecard")
        if not isinstance(authority_raw, Mapping):
            raise ContractError("Scorecard: 'authority' must be a mapping")
        baseline_raw = m.get("baseline_state")
        return cls(
            verdict=VerdictPayload.from_dict(
                _as_mapping(_require(m, "verdict", "Scorecard"), "Scorecard.verdict")
            ),
            metrics=[
                AggregatedMetric.from_dict(_as_mapping(x, "Scorecard.metrics"))
                for x in _coerce_required_list(m, "metrics", "Scorecard")
            ],
            authority={
                str(k): ResolvedAuthority.from_dict(_as_mapping(v, "Scorecard.authority"))
                for k, v in authority_raw.items()
            },
            baseline_state=(
                _coerce_enum(BaselineState, baseline_raw, "baseline_state", "Scorecard")
                if baseline_raw is not None
                else None
            ),
            diagnostics=[
                Diagnostic.from_dict(_as_mapping(d, "Scorecard.diagnostics"))
                for d in _opt_list(m, "diagnostics", "Scorecard")
            ],
            estimates=[
                Estimate.from_dict(_as_mapping(e, "Scorecard.estimates"))
                for e in _opt_list(m, "estimates", "Scorecard")
            ],
            claim_specs=_parse_claim_specs(m),
            clusters=[
                DiagnosticCluster.from_dict(_as_mapping(c, "Scorecard.clusters"))
                for c in _opt_list(m, "clusters", "Scorecard")
            ],
            populations=[
                PopulationSummary.from_dict(_as_mapping(p, "Scorecard.populations"))
                for p in _opt_list(m, "populations", "Scorecard")
            ],
            comparison=(
                ComparisonResult.from_dict(_as_mapping(m["comparison"], "Scorecard.comparison"))
                if m.get("comparison") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class RunRecord:
    """Complete persisted record of a run.

    ``lane_results`` is an additive, optional side channel (ADR 0031): the serialized
    outcomes of any configured optional extension lanes (``ran``/``skipped``/``blocked``
    + diagnostics). It records *evidence*, never authority — it is deliberately **not**
    on :class:`Scorecard`, so the verdict-bearing summary, reports, CI, and exit code
    stay lane-free. It is emitted only when non-empty, so a run with no configured lanes
    is byte-identical to a pre-seam run, and a missing value parses to ``[]``.
    """

    run_id: str
    scorecard: Scorecard
    scores: list[Score]
    provenance: RunFingerprint
    comparable: ComparableRunFingerprint | None = None
    lane_results: list[dict[str, Any]] = field(default_factory=list)
    # Additive: the plan/execution reconciliation — the EvaluationPlan digest plus
    # planned/executed/failed/deviated counts and typed deviations, attached by the Harness after
    # the effect-free core returns (the core never sees it). Records *evidence of execution*, never
    # authority; deliberately not on Scorecard so verdict/CI/exit stay plan-free. Emitted only when
    # present, so a pre-A2 record (no plan) is byte-identical and an absent value parses to None.
    plan: dict[str, Any] | None = None
    # Additive: per-source import coverage manifests (Epic B / B2) — one per source read (dataset,
    # local trace, or connector lane), recording what each source returned vs what was accepted,
    # rejected, or fell back on, plus a typed completeness. Evidence only, never authority: like
    # lane_results it is deliberately off Scorecard so verdict/CI/exit are unaffected, and emitted
    # only when non-empty so a run with no imported sources stays byte-identical.
    source_manifests: list[dict[str, Any]] = field(default_factory=list)
    # Additive (C4; ADR 0054): the complete, append-only judge-evidence records for this run — the
    # parsed score/rationale/facets/violations/citations plus instrument identity, usage, and
    # diagnostics that produced each judge Score. A judge ``Score.evidence_refs`` resolves into this
    # list (``resolve_evidence``), so a report explains a score with no host cache. Evidence, never
    # authority: deliberately off Scorecard (which stays compact), integrity-covered as part of the
    # RunRecord, and emitted only when non-empty so a no-judge run stays byte-identical.
    evidence: list[JudgeEvidence] = field(default_factory=list)

    def resolve_evidence(self, ref: str) -> JudgeEvidence | None:
        """The evidence record a ``Score.evidence_refs`` entry points to, or ``None``."""
        for record in self.evidence:
            if record.evidence_id == ref:
                return record
        return None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "run_id": self.run_id,
            "scorecard": self.scorecard.to_dict(),
            "scores": [s.to_dict() for s in self.scores],
            "provenance": self.provenance.to_dict(),
        }
        if self.comparable is not None:
            out["comparable"] = self.comparable.to_dict()
        # Emit only when non-empty (no-lane runs stay byte-identical to pre-seam runs);
        # copy each entry so mutating the returned JSON never reaches the frozen record.
        if self.lane_results:
            out["lane_results"] = [dict(r) for r in self.lane_results]
        if self.plan is not None:
            out["plan"] = dict(self.plan)
        if self.source_manifests:
            out["source_manifests"] = [dict(m) for m in self.source_manifests]
        if self.evidence:
            out["evidence"] = [e.to_dict() for e in self.evidence]
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "RunRecord")
        run_id = _require(m, "run_id", "RunRecord")
        if not isinstance(run_id, str) or not run_id:
            raise ContractError("RunRecord: 'run_id' must be a non-empty string")
        # A present-but-malformed 'comparable' must fail closed, not be read as absent.
        comparable = (
            ComparableRunFingerprint.from_dict(
                _require_mapping(m, "comparable", "RunRecord.comparable")
            )
            if m.get("comparable") is not None
            else None
        )
        record = cls(
            run_id=run_id,
            scorecard=Scorecard.from_dict(
                _as_mapping(_require(m, "scorecard", "RunRecord"), "RunRecord.scorecard")
            ),
            scores=[
                Score.from_dict(_as_mapping(s, "RunRecord.scores"))
                for s in _coerce_required_list(m, "scores", "RunRecord")
            ],
            provenance=RunFingerprint.from_dict(
                _as_mapping(_require(m, "provenance", "RunRecord"), "RunRecord.provenance")
            ),
            comparable=comparable,
            lane_results=_lane_results(m),
            plan=_plan_reconciliation(m),
            source_manifests=_source_manifests(m),
            evidence=_evidence_records(m),
        )
        # M7 T5 (G5): the persisted aggregates/estimates are projections of the raw scores.
        # Recompute them on load and reject a record whose summary contradicts its own
        # scores — a hand-edited aggregate (e.g. 1.0 -> 0.0 while the raw scores stay 1.0)
        # must fail closed, not parse as a quiet pass.
        _verify_consistency(record.scorecard, record.scores)
        # C4 (ADR 0054): when evidence is persisted, a judge Score's evidence_refs must resolve to a
        # record and a numeric judge value must come from an OK record — a dangling ref or a
        # value-without-OK-evidence fails closed. A legacy record with NO evidence key is exempt
        # (its refs are unavailable, never fabricated).
        _verify_evidence(record.scores, record.evidence, enforced="evidence" in m)
        return record


def _evidence_records(m: Mapping[str, Any]) -> list[JudgeEvidence]:
    """Parse the optional append-only judge-evidence records (absent -> []; else fail closed)."""
    raw = m.get("evidence")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ContractError("RunRecord: 'evidence' must be a list")
    return [JudgeEvidence.from_dict(_as_mapping(e, "RunRecord.evidence")) for e in raw]


def _verify_evidence(scores: list[Score], evidence: list[JudgeEvidence], *, enforced: bool) -> None:
    """When evidence is persisted, judge score refs must resolve and a value must come from OK.

    A dangling ``judge:`` ref (an evidence record removed by tampering) or a numeric judge value
    whose resolved evidence is not ``ok`` fails closed. A legacy record with no ``evidence`` key is
    exempt — its refs are labelled unavailable on read, never fabricated (ADR 0054).
    """
    if not enforced:
        return
    index = {e.evidence_id: e for e in evidence}
    for score in scores:
        for ref in score.evidence_refs:
            if not ref.startswith("judge:"):
                continue
            record = index.get(ref)
            if record is None:
                raise ContractError(
                    f"RunRecord: score for {score.metric!r} references judge evidence {ref!r} "
                    "that is not in the run's evidence records (dangling)"
                )
            if score.value is not None and record.status is not JudgeEvidenceStatus.OK:
                raise ContractError(
                    f"RunRecord: score for {score.metric!r} carries a numeric value but its "
                    f"evidence {ref!r} has status {record.status.value!r}, not 'ok'"
                )


def _parse_claim_specs(m: Mapping[str, Any]) -> dict[str, ClaimSpec]:
    """Parse the optional per-metric claim specs (absent -> {}; fail closed otherwise)."""
    raw = m.get("claim_specs")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ContractError("Scorecard: 'claim_specs' must be a mapping")
    return {
        str(k): ClaimSpec.from_dict(_as_mapping(v, "Scorecard.claim_specs")) for k, v in raw.items()
    }


def _values_close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def _verify_consistency(scorecard: Scorecard, scores: list[Score]) -> None:
    """Reject a RunRecord whose stored aggregates/estimates contradict its raw scores.

    Recomputes each ``AggregatedMetric`` (value + coverage counts) and each
    ``Estimate`` point + effective n from the raw ``scores`` — projections must match
    their source (``docs/TETA_REDESIGN.md`` G5 / N5). It does not re-derive interval
    *methods* (that needs the MetricSpec, not persisted here); the point + counts are
    what a tamper would move.
    """
    _verify_aggregates(scorecard, scores)
    _verify_estimates(scorecard, scores)
    # P3 (ADR 0047): the diagnostic clusters are a pure projection of the raw scores. When a record
    # carries clusters, recompute and reject any mismatch (count/severity/members/order) — a
    # fabricated or hand-edited cluster fails closed exactly like a tampered aggregate. A record
    # with NO clusters is not checked (the estimates convention): a pre-P3 record whose scores
    # carry diagnostics still loads, and dropping the clusters loses explanatory structure only —
    # it manufactures no value, verdict, or authority.
    if scorecard.clusters and scorecard.clusters != cluster(scores):
        raise ContractError(
            "RunRecord: stored diagnostic clusters contradict the raw scores "
            "(recomputed clusters differ) — the record is internally inconsistent"
        )
    _verify_populations(scorecard, scores)
    _verify_comparison_state(scorecard)


def _verify_aggregates(scorecard: Scorecard, scores: list[Score]) -> None:
    """Reject a record whose stored ``AggregatedMetric`` value/coverage contradicts the scores."""
    for agg in scorecard.metrics:
        recomputed = aggregate(agg.metric, scores, agg.aggregation)
        if (
            not _values_close(recomputed.value, agg.value)
            or recomputed.included_count != agg.included_count
            or recomputed.status_counts != agg.status_counts
        ):
            raise ContractError(
                f"RunRecord: stored aggregate for {agg.metric!r} contradicts the raw scores "
                "(recomputed value/coverage differs) — the record is internally inconsistent"
            )


def _verify_estimates(scorecard: Scorecard, scores: list[Score]) -> None:
    """Reject a record whose stored ``Estimate`` point / effective n contradicts its raw scores."""
    by_metric = {agg.metric: agg for agg in scorecard.metrics}
    for est in scorecard.estimates:
        own = [s for s in scores if s.metric == est.metric]
        n_eff = len([s for s in aggregatable(own) if s.value is not None])
        if est.n_effective != n_eff:
            raise ContractError(
                f"RunRecord: estimate n_effective for {est.metric!r} ({est.n_effective}) "
                f"contradicts the raw scores ({n_eff})"
            )
        expected_point = by_metric[est.metric].value if est.metric in by_metric else None
        if not _values_close(est.point, expected_point):
            raise ContractError(
                f"RunRecord: estimate point for {est.metric!r} contradicts the aggregate value"
            )


def _verify_populations(scorecard: Scorecard, scores: list[Score]) -> None:
    """Reject a record whose stored population TERMINAL counts contradict its raw scores (D3).

    The terminal layer (scored_valid/non_evaluable/blocked/skipped/error) is a pure projection of
    the raw scores. The pre-effect layer is plan-derived (not recoverable from scores) and is
    validated for internal identity in ``PopulationSummary.__post_init__``; a record with no
    populations is not checked (byte-compat).
    """
    for pop in scorecard.populations:
        recomputed = PopulationSummary.from_scores(pop.metric, scores)
        if (
            pop.scored_valid != recomputed.scored_valid
            or pop.non_evaluable != recomputed.non_evaluable
            or pop.blocked != recomputed.blocked
            or pop.skipped != recomputed.skipped
            or pop.error != recomputed.error
        ):
            raise ContractError(
                f"RunRecord: stored population for {pop.metric!r} contradicts the raw scores "
                "(recomputed terminal counts differ) — the record is internally inconsistent"
            )


def _verify_comparison_state(scorecard: Scorecard) -> None:
    """Reject an injected comparison whose state contradicts the Scorecard's baseline_state (D4).

    The per-metric deltas need the baseline's scores to fully recompute, which are not in this
    record; state-vs-delta consistency is enforced in ``ComparisonResult``, and any edit to the
    persisted values is caught by the run manifest/completion-marker integrity.
    """
    if (
        scorecard.comparison is not None
        and scorecard.baseline_state is not None
        and scorecard.comparison.state is not scorecard.baseline_state
    ):
        raise ContractError(
            "RunRecord: stored comparison state contradicts the scorecard baseline_state "
            "— the record is internally inconsistent"
        )


def _coerce_required_list(data: Mapping[str, Any], key: str, ctx: str) -> list[Any]:
    value = _require(data, key, ctx)
    if not isinstance(value, list):
        raise ContractError(f"{ctx}: field '{key}' must be a list")
    return value


def _lane_results(m: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse the optional lane side channel (ADR 0031): absent → ``[]``; fail closed otherwise."""
    raw = m.get("lane_results")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ContractError("RunRecord: 'lane_results' must be a list")
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ContractError("RunRecord: each 'lane_results' entry must be a mapping")
        out.append(dict(entry))
    return out


def _plan_reconciliation(m: Mapping[str, Any]) -> dict[str, Any] | None:
    """Parse the optional plan/execution reconciliation: absent → ``None``; fail closed.

    Opaque to the core (a Harness-owned projection); validated only as a mapping so a malformed
    value fails closed rather than parsing as absent.
    """
    raw = m.get("plan")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ContractError("RunRecord: 'plan' must be a mapping")
    return dict(raw)


def _source_manifests(m: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse the optional source-import coverage manifests (B2): absent → ``[]``; fail closed.

    Opaque to the core (a Harness-owned projection); validated only as a list of mappings so a
    malformed value fails closed rather than parsing as absent.
    """
    raw = m.get("source_manifests")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ContractError("RunRecord: 'source_manifests' must be a list")
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ContractError("RunRecord: each 'source_manifests' entry must be a mapping")
        out.append(dict(entry))
    return out
