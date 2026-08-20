"""The typed EvaluationPlan — one applicability/effect plan resolved before any effect.

Today the harness collects judge evidence for the *product* of every judge metric and every
example, and the per-metric ``ExampleSelector`` is applied later, inside the pure core scorer. A
developer therefore cannot see — before running — which subjects each metric can evaluate, which
effects (judge calls, task replay) that implies, or how many external requests will occur; and a
host judge has to re-implement the selector to short-circuit irrelevant pairs.

``build_plan`` resolves that once, up front, into a typed, JSON-serialisable ``EvaluationPlan``:

* one :class:`PlannedSubject` per loaded ``Example`` instance, with a **stable plan-local id**
  (``s0``, ``s1``, …) that is unique even when host ``example_id`` values collide;
* one :class:`PlannedMetric` per configured metric — its selector, unit kind, source binding, and a
  reconciled population ledger (available / selector-matched / eligible / per-reason excluded);
* one :class:`PlannedEffect` per eligible judge or replay effect, each carrying its policy decision,
  instrument reference, and a request fingerprint, keyed by a **stable effect id** so the executor
  can bind an outcome to exactly one planned effect and fail closed on any effect it did
  not plan.

Two honesty rules from the engine are preserved exactly:

* **One selector implementation.** Applicability is decided only by
  :meth:`ExampleSelector.matches` — this module never re-implements the grammar.
* **Integrity bypass.** A run-integrity subject (the route-error example) matches every metric
  regardless of any selector, so an incomplete-input run still reaches every active gate.

The planner is **effect-free**: it performs no network, subprocess, clock-dependent id generation,
scoring, authority resolution, or verdict decision (``CLAUDE.md §8`` spirit). It
only projects the eligible population and the effects it implies; the Verdict Engine and authority
resolution stay the single owners of meaning.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Self

from evalglass.core import Diagnostic, Example
from evalglass.core._validation import ContractError, _as_mapping, _coerce_enum, _require
from evalglass.core.selector import INTEGRITY_METADATA_KEY, ExampleSelector

#: Versioned schema tag for the persisted ``run-plan.json`` and the ``RunRecord.plan`` digest.
PLAN_SCHEMA = "evalglass.evaluation-plan/1"

_JUDGE_EVIDENCE = "judge"


class EffectKind(Enum):
    """The kind of external effect a metric's evaluation requires."""

    JUDGE = "judge"
    REPLAY = "replay"


class PolicyDecision(Enum):
    """The fail-closed egress decision for a subject's effect.

    ``PERMITTED`` iff the subject's data policy allows host egress (permitted/redacted); every
    other policy state (forbidden/missing/unknown) collapses to ``DENIED`` — a single fail-closed
    decision, exactly the ``_EGRESS_OK`` rule the replay/judge seams already enforce.
    """

    PERMITTED = "permitted"
    DENIED = "denied"


class ExclusionReason(Enum):
    """Why a metric excluded an available subject from its eligible population."""

    SELECTOR_MISMATCH = "selector_mismatch"
    MISSING_PREREQUISITE = "missing_prerequisite"


#: Public exclusion-reason keys, so a population consumer need not import the Enum values.
SELECTOR_MISMATCH = ExclusionReason.SELECTOR_MISMATCH.value
MISSING_PREREQUISITE = ExclusionReason.MISSING_PREREQUISITE.value


class DeviationCode(Enum):
    """A reconciled difference between the plan and the executed run."""

    PLANNED_NOT_EXECUTED = "planned_not_executed"
    EXECUTED_NOT_PLANNED = "executed_not_planned"


def _sha(value: Any) -> str:
    """Order-insensitive sha256 over a JSON-serialisable value (the provenance idiom)."""
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    )


@dataclass(frozen=True)
class PlannedSubject:
    """One loaded ``Example`` instance in the plan, with a stable plan-local identity.

    ``subject_id`` is assigned by load order (``s0``, ``s1``, …) so it is unique across the run even
    when two sources supply the same host ``example_id``. ``egress_ok`` is the
    already-resolved, fail-closed data-policy decision for this instance.
    """

    subject_id: str
    example_id: str
    unit_id: str
    unit_kind: str
    source: str
    egress_ok: bool
    integrity: bool = False

    @property
    def policy_decision(self) -> PolicyDecision:
        return PolicyDecision.PERMITTED if self.egress_ok else PolicyDecision.DENIED

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "subject_id": self.subject_id,
            "example_id": self.example_id,
            "unit_id": self.unit_id,
            "unit_kind": self.unit_kind,
            "source": self.source,
            "egress_ok": self.egress_ok,
            "policy_decision": self.policy_decision.value,
        }
        if self.integrity:
            out["integrity"] = True
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "PlannedSubject")
        return cls(
            subject_id=str(_require(m, "subject_id", "PlannedSubject")),
            example_id=str(_require(m, "example_id", "PlannedSubject")),
            unit_id=str(_require(m, "unit_id", "PlannedSubject")),
            unit_kind=str(_require(m, "unit_kind", "PlannedSubject")),
            source=str(_require(m, "source", "PlannedSubject")),
            egress_ok=bool(_require(m, "egress_ok", "PlannedSubject")),
            integrity=bool(m.get("integrity", False)),
        )


@dataclass(frozen=True)
class PlannedEffect:
    """One external effect the plan requires — a judge call or a task replay.

    ``effect_id`` is stable and unique: ``judge:<metric>:<subject_id>`` for a judge effect,
    ``replay:<subject_id>`` for a (metric-agnostic) replay. The executor keys its outcome to this id
    and rejects any effect id it did not plan. ``request_fingerprint`` is the sha256 of the
    score-determining request content, so a changed prompt/rubric/input changes the plan.
    """

    effect_id: str
    kind: EffectKind
    subject_id: str
    policy_decision: PolicyDecision
    metric: str | None = None
    instrument_ref: str | None = None
    request_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "effect_id": self.effect_id,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "policy_decision": self.policy_decision.value,
        }
        if self.metric is not None:
            out["metric"] = self.metric
        if self.instrument_ref is not None:
            out["instrument_ref"] = self.instrument_ref
        if self.request_fingerprint is not None:
            out["request_fingerprint"] = self.request_fingerprint
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "PlannedEffect")
        return cls(
            effect_id=str(_require(m, "effect_id", "PlannedEffect")),
            kind=_coerce_enum(
                EffectKind, _require(m, "kind", "PlannedEffect"), "kind", "PlannedEffect"
            ),
            subject_id=str(_require(m, "subject_id", "PlannedEffect")),
            policy_decision=_coerce_enum(
                PolicyDecision,
                _require(m, "policy_decision", "PlannedEffect"),
                "policy_decision",
                "PlannedEffect",
            ),
            metric=(str(m["metric"]) if m.get("metric") is not None else None),
            instrument_ref=(
                str(m["instrument_ref"]) if m.get("instrument_ref") is not None else None
            ),
            request_fingerprint=(
                str(m["request_fingerprint"]) if m.get("request_fingerprint") is not None else None
            ),
        )


@dataclass(frozen=True)
class PlannedMetric:
    """One metric's reconciled population ledger + the effects its evaluation requires.

    The counts reconcile exactly:
    ``available == selector_matched + excluded[selector_mismatch]`` and
    ``selector_matched == eligible + excluded[missing_prerequisite]`` (integrity subjects always
    count as matched and eligible). ``effect_ids`` lists the plan effects this metric owns.
    """

    metric: str
    unit_kind: str
    available: int
    selector_matched: int
    eligible: int
    excluded: dict[str, int]
    prerequisites: list[str] = field(default_factory=list)
    selector: dict[str, Any] | None = None
    effect_ids: list[str] = field(default_factory=list)
    #: Additive (Epic D / D1): the metric's resolved source bindings (name + role), present only for
    #: a bound metric. ``available`` is then the count over just the bound candidate sources, so a
    #: bound metric's population is exactly its declared inputs. Absent -> an unbound legacy metric.
    source_bindings: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "metric": self.metric,
            "unit_kind": self.unit_kind,
            "available": self.available,
            "selector_matched": self.selector_matched,
            "eligible": self.eligible,
            "excluded": dict(self.excluded),
        }
        if self.prerequisites:
            out["prerequisites"] = list(self.prerequisites)
        if self.selector is not None:
            out["selector"] = self.selector
        if self.effect_ids:
            out["effect_ids"] = list(self.effect_ids)
        if self.source_bindings is not None:
            out["source_bindings"] = [dict(b) for b in self.source_bindings]
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "PlannedMetric")
        excluded_raw = m.get("excluded", {})
        if not isinstance(excluded_raw, Mapping):
            raise ContractError("PlannedMetric: 'excluded' must be a mapping")
        return cls(
            metric=str(_require(m, "metric", "PlannedMetric")),
            unit_kind=str(_require(m, "unit_kind", "PlannedMetric")),
            available=int(_require(m, "available", "PlannedMetric")),
            selector_matched=int(_require(m, "selector_matched", "PlannedMetric")),
            eligible=int(_require(m, "eligible", "PlannedMetric")),
            excluded={str(k): int(v) for k, v in excluded_raw.items()},
            prerequisites=[str(p) for p in m.get("prerequisites", [])],
            selector=(dict(m["selector"]) if m.get("selector") is not None else None),
            effect_ids=[str(e) for e in m.get("effect_ids", [])],
            source_bindings=(
                [
                    dict(_as_mapping(b, "PlannedMetric.source_bindings"))
                    for b in m["source_bindings"]
                ]
                if m.get("source_bindings") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class PlanDeviation:
    """A reconciled difference between what was planned and what actually executed."""

    code: DeviationCode
    effect_id: str | None = None
    metric: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code.value}
        if self.effect_id is not None:
            out["effect_id"] = self.effect_id
        if self.metric is not None:
            out["metric"] = self.metric
        if self.message:
            out["message"] = self.message
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "PlanDeviation")
        return cls(
            code=_coerce_enum(
                DeviationCode, _require(m, "code", "PlanDeviation"), "code", "PlanDeviation"
            ),
            effect_id=(str(m["effect_id"]) if m.get("effect_id") is not None else None),
            metric=(str(m["metric"]) if m.get("metric") is not None else None),
            message=str(m.get("message", "")),
        )


@dataclass(frozen=True)
class EvaluationPlan:
    """The whole run's applicability/effect plan, resolved before any effect."""

    run_id: str
    subjects: list[PlannedSubject]
    metrics: list[PlannedMetric]
    effects: list[PlannedEffect]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    schema: str = PLAN_SCHEMA

    def fingerprint(self) -> str:
        """A stable digest over the plan's *score-determining* content only.

        Includes each metric's selector/unit-kind/prerequisites/effect refs, each subject's
        source + egress decision, and every effect's kind/instrument/request fingerprint. Excludes
        cosmetic-only fields (plan-local subject-id spelling is derived from load order, which is
        already reflected by the source list) so a display-only change leaves the digest stable.
        """
        payload = {
            "schema": self.schema,
            "subjects": [
                {"source": s.source, "egress_ok": s.egress_ok, "integrity": s.integrity}
                for s in self.subjects
            ],
            "metrics": [self._metric_fingerprint(pm) for pm in self.metrics],
            "effects": [
                {
                    "kind": e.kind.value,
                    "metric": e.metric,
                    "policy_decision": e.policy_decision.value,
                    "instrument_ref": e.instrument_ref,
                    "request_fingerprint": e.request_fingerprint,
                }
                for e in self.effects
            ],
        }
        return _sha(payload)

    @staticmethod
    def _metric_fingerprint(pm: PlannedMetric) -> dict[str, Any]:
        """The score-determining slice of one metric for the plan digest.

        ``source_bindings`` is added only for a bound metric: a metric bound to a different
        candidate or reference source scores different evidence, so the digest (and comparability)
        must move, while an unbound metric keeps its pre-D1 digest (baselines stay comparable).
        """
        out: dict[str, Any] = {
            "metric": pm.metric,
            "unit_kind": pm.unit_kind,
            "selector": pm.selector,
            "prerequisites": pm.prerequisites,
        }
        if pm.source_bindings is not None:
            out["source_bindings"] = pm.source_bindings
        return out

    def judge_effects(self) -> list[PlannedEffect]:
        return [e for e in self.effects if e.kind is EffectKind.JUDGE]

    def replay_effects(self) -> list[PlannedEffect]:
        return [e for e in self.effects if e.kind is EffectKind.REPLAY]

    def reconcile(self, executed_effect_ids: Iterable[str]) -> list[PlanDeviation]:
        """Diff planned vs executed effect ids into typed deviations.

        An executed id absent from the plan is an ``EXECUTED_NOT_PLANNED`` integrity failure; a
        planned id never executed is a ``PLANNED_NOT_EXECUTED`` deviation (typed evidence, never a
        fabricated numeric zero).
        """
        planned = {e.effect_id for e in self.effects}
        executed = set(executed_effect_ids)
        deviations: list[PlanDeviation] = []
        for effect_id in sorted(executed - planned):
            deviations.append(
                PlanDeviation(
                    code=DeviationCode.EXECUTED_NOT_PLANNED,
                    effect_id=effect_id,
                    message="an effect was executed that the plan did not authorise",
                )
            )
        for effect_id in sorted(planned - executed):
            deviations.append(
                PlanDeviation(
                    code=DeviationCode.PLANNED_NOT_EXECUTED,
                    effect_id=effect_id,
                    message="a planned effect was not executed",
                )
            )
        return deviations

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema": self.schema,
            "run_id": self.run_id,
            "fingerprint": self.fingerprint(),
            "subjects": [s.to_dict() for s in self.subjects],
            "metrics": [pm.to_dict() for pm in self.metrics],
            "effects": [e.to_dict() for e in self.effects],
        }
        if self.diagnostics:
            out["diagnostics"] = [d.to_dict() for d in self.diagnostics]
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "EvaluationPlan")
        return cls(
            run_id=str(_require(m, "run_id", "EvaluationPlan")),
            subjects=[
                PlannedSubject.from_dict(_as_mapping(s, "EvaluationPlan.subjects"))
                for s in m.get("subjects", [])
            ],
            metrics=[
                PlannedMetric.from_dict(_as_mapping(x, "EvaluationPlan.metrics"))
                for x in m.get("metrics", [])
            ],
            effects=[
                PlannedEffect.from_dict(_as_mapping(e, "EvaluationPlan.effects"))
                for e in m.get("effects", [])
            ],
            diagnostics=[
                Diagnostic.from_dict(_as_mapping(d, "EvaluationPlan.diagnostics"))
                for d in m.get("diagnostics", [])
            ],
            schema=str(m.get("schema", PLAN_SCHEMA)),
        )


# --- the pure planner ---------------------------------------------------------------------------


def _subject_id(index: int) -> str:
    """A stable, collision-free plan-local subject id derived from load order (no clock)."""
    return f"s{index}"


def _request_fingerprint(metric: str, example: Example, instrument_ref: str | None) -> str:
    """A score-determining fingerprint of a judge request (metric + evidence + instrument)."""
    return _sha(
        {
            "metric": metric,
            "input": example.input,
            "output": example.output,
            "reference": example.reference,
            "context": example.context,
            "instrument_ref": instrument_ref,
        }
    )


@dataclass(frozen=True)
class MetricView:
    """The minimal metric facts the planner needs, decoupled from ``MetricConfig`` (testable)."""

    name: str
    selector: ExampleSelector | None
    is_judge: bool
    is_reference: bool
    prerequisites: list[str]
    rubric_ref: str | None = None
    #: Additive (Epic D / D1): the metric's ``candidate``-role source names. ``None`` -> an unbound
    #: metric that sees every loaded subject (legacy). A frozenset -> the metric's population is
    #: restricted to subjects from those sources (an integrity subject always stays in scope).
    candidate_sources: frozenset[str] | None = None
    #: Additive (D1): the metric's full resolved bindings (name + role), carried onto the plan for
    #: doctor/provenance. ``None`` for an unbound metric.
    source_bindings: list[dict[str, Any]] | None = None


def _plan_subjects(subjects_in: Sequence[tuple[Example, bool]]) -> list[PlannedSubject]:
    """One stable-id PlannedSubject per loaded example instance (load order → ``s0``, ``s1``, …)."""
    return [
        PlannedSubject(
            subject_id=_subject_id(index),
            example_id=example.example_id,
            unit_id=example.unit.unit_id,
            unit_kind=example.unit.kind.value,
            source=example.unit.trace_id,
            egress_ok=egress_ok,
            integrity=bool(example.metadata.get(INTEGRITY_METADATA_KEY)),
        )
        for index, (example, egress_ok) in enumerate(subjects_in)
    ]


def _in_scope_pairs(
    mv: MetricView,
    subjects: Sequence[PlannedSubject],
    examples: Sequence[Example],
    source_names: Sequence[str] | None,
) -> list[tuple[PlannedSubject, Example]]:
    """The (subject, example) pairs a metric's bindings put in scope (D1).

    An unbound metric (``candidate_sources is None``) sees every subject — byte-identical to the
    pre-binding planner. A bound metric sees only subjects from its ``candidate`` sources, plus any
    run-integrity subject (which must never be filtered out of a gate's population, D1 AC5). When a
    metric is bound but the run supplied no per-subject source names, only integrity subjects are in
    scope — the metric fails closed to non-evaluable rather than silently scoring an unknown source.
    """
    if mv.candidate_sources is None:
        return list(zip(subjects, examples, strict=True))
    pairs: list[tuple[PlannedSubject, Example]] = []
    for index, (subject, example) in enumerate(zip(subjects, examples, strict=True)):
        in_source = source_names is not None and source_names[index] in mv.candidate_sources
        if subject.integrity or in_source:
            pairs.append((subject, example))
    return pairs


def _match_pairs(
    mv: MetricView, in_scope: Sequence[tuple[PlannedSubject, Example]]
) -> tuple[list[tuple[PlannedSubject, Example]], int]:
    """Selector-matched pairs + the count excluded by selector mismatch, over an in-scope set.

    An integrity subject or a metric with no selector matches everything; otherwise applicability is
    :meth:`ExampleSelector.matches` (the one implementation).
    """
    matched: list[tuple[PlannedSubject, Example]] = []
    mismatch = 0
    for subject, example in in_scope:
        if subject.integrity or mv.selector is None or mv.selector.matches(example):
            matched.append((subject, example))
        else:
            mismatch += 1
    return matched, mismatch


def _eligible_subjects(
    mv: MetricView, matched: Sequence[tuple[PlannedSubject, Example]]
) -> tuple[list[tuple[PlannedSubject, Example]], int]:
    """Eligible pairs (prerequisites met) + the count excluded by a missing prerequisite."""
    eligible: list[tuple[PlannedSubject, Example]] = []
    missing = 0
    for subject, example in matched:
        if not subject.integrity and mv.is_reference and example.reference is None:
            missing += 1
        else:
            eligible.append((subject, example))
    return eligible, missing


def _judge_effects_for(
    mv: MetricView, eligible: Sequence[tuple[PlannedSubject, Example]]
) -> list[PlannedEffect]:
    """One judge effect per eligible non-integrity subject (integrity subjects cause no egress)."""
    return [
        PlannedEffect(
            effect_id=f"judge:{mv.name}:{subject.subject_id}",
            kind=EffectKind.JUDGE,
            subject_id=subject.subject_id,
            policy_decision=subject.policy_decision,
            metric=mv.name,
            instrument_ref=mv.rubric_ref,
            request_fingerprint=_request_fingerprint(mv.name, example, mv.rubric_ref),
        )
        for subject, example in eligible
        if not subject.integrity
    ]


def _plan_metric(
    mv: MetricView,
    subjects: Sequence[PlannedSubject],
    examples: Sequence[Example],
    source_names: Sequence[str] | None,
) -> tuple[PlannedMetric, list[PlannedEffect], set[str]]:
    """Plan one metric: its reconciled ledger, its judge effects, and its matched subject ids.

    A bound metric's ``available`` population is only its candidate sources (D1); an unbound metric
    keeps the whole-run population (byte-identical to before bindings existed).
    """
    in_scope = _in_scope_pairs(mv, subjects, examples, source_names)
    matched, mismatch = _match_pairs(mv, in_scope)
    eligible, missing = _eligible_subjects(mv, matched)
    judge_effects = _judge_effects_for(mv, eligible) if mv.is_judge else []
    excluded: dict[str, int] = {}
    if mismatch:
        excluded[ExclusionReason.SELECTOR_MISMATCH.value] = mismatch
    if missing:
        excluded[ExclusionReason.MISSING_PREREQUISITE.value] = missing
    planned = PlannedMetric(
        metric=mv.name,
        unit_kind=_dominant_unit_kind(s for s, _ in matched),
        available=sum(1 for s, _ in in_scope if not s.integrity),
        selector_matched=len(matched),
        eligible=len(eligible),
        excluded=excluded,
        prerequisites=list(mv.prerequisites),
        selector=mv.selector.to_dict() if mv.selector is not None else None,
        effect_ids=[e.effect_id for e in judge_effects],
        source_bindings=mv.source_bindings,
    )
    return planned, judge_effects, {s.subject_id for s, _ in matched}


def _replay_effects(
    subjects: Sequence[PlannedSubject],
    examples: Sequence[Example],
    matched_subject_ids: set[str],
) -> list[PlannedEffect]:
    """A replay effect per output-less, selector-matched, non-integrity subject.

    Replay fills a *missing output*, a prerequisite the replay itself satisfies, so a subject is
    replay-worthy as soon as some metric's selector matches it (independent of e.g. a missing
    reference). With no selectors every subject matches, so this is byte-compatible with the
    pre-plan "replay every output-less example" behaviour.
    """
    return [
        PlannedEffect(
            effect_id=f"replay:{subject.subject_id}",
            kind=EffectKind.REPLAY,
            subject_id=subject.subject_id,
            policy_decision=subject.policy_decision,
        )
        for subject, example in zip(subjects, examples, strict=True)
        if example.output is None
        and not subject.integrity
        and subject.subject_id in matched_subject_ids
    ]


def build_plan(
    *,
    run_id: str,
    subjects_in: Sequence[tuple[Example, bool]],
    metrics: Sequence[MetricView],
    source_names: Sequence[str] | None = None,
) -> EvaluationPlan:
    """Resolve one applicability/effect plan over the loaded subjects and metrics (effect-free).

    ``subjects_in`` is the same ``(Example, egress_ok)`` sequence the runner already assembles
    (datasets + trace units + any run-integrity example), so the plan's population is exactly the
    scored population. ``source_names`` is the parallel per-subject configured-source name (dataset
    or trace name) the runner records; it is used only to scope a bound metric's population to its
    ``candidate`` sources (D1). Absent -> every metric is unbound (byte-identical to before
    bindings). Selector decisions call :meth:`ExampleSelector.matches` — the one applicability
    implementation.
    """
    subjects = _plan_subjects(subjects_in)
    examples = [example for example, _egress in subjects_in]
    if source_names is not None and len(source_names) != len(subjects):
        raise ContractError("build_plan: source_names must be parallel to subjects_in")
    planned_metrics: list[PlannedMetric] = []
    effects: list[PlannedEffect] = []
    # A subject is replay-worthy once some metric's selector matches it (see _replay_effects).
    matched_subject_ids: set[str] = set()
    for mv in metrics:
        planned, judge_effects, matched_ids = _plan_metric(mv, subjects, examples, source_names)
        planned_metrics.append(planned)
        effects.extend(judge_effects)
        matched_subject_ids |= matched_ids
    effects.extend(_replay_effects(subjects, examples, matched_subject_ids))
    return EvaluationPlan(
        run_id=run_id, subjects=subjects, metrics=planned_metrics, effects=effects
    )


def _dominant_unit_kind(subjects: Iterable[PlannedSubject]) -> str:
    kinds = {s.unit_kind for s in subjects if not s.integrity}
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixed" if kinds else "call"
