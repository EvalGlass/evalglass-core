"""Run orchestration + route convergence (EG-M1-4).

``run_config`` is the harness's composition root for a local run: it reads every configured
dataset/trace through its port, converges them into one ``Example`` list, loads each metric's
evaluator, builds ``MetricPlan``s with the metric's typed authority inputs, assembles the
provenance dimensions, and calls the effect-free core ``run_evaluation``. It **never**
computes scores, authority, or the verdict — those come back from the core.

Two trust rules shape the orchestration:

* **Incomplete input cannot pass a gate.** Malformed records are surfaced as evidence and
  Scorecard diagnostics, *and* — because in M1 every metric scores every example — a
  run-level "route error" measurement is fed in so any active gate blocks on incomplete
  evidence rather than passing over the records that did parse.
* **Authority reflects the worst source.** Since every metric scores every example, a
  metric's authority is the worst-case dataset status + data policy across all configured
  sources, never just one bound dataset. A validated dataset mixed with a trace (no gold) or
  a forbidden source cannot launder a gate to ``pass``.

A configured baseline (``config.baseline_path``) is loaded and passed to the core, which
resolves comparability; a requested comparison with no baseline resolves to missing-baseline.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from evalglass import __version__ as _EVALGLASS_VERSION
from evalglass.adapters.dataset_jsonl import LocalJsonlDatasetStore
from evalglass.adapters.judge_fake import FakeJudgeModel
from evalglass.adapters.judge_subprocess import SubprocessJudgeModel
from evalglass.adapters.task_subprocess import SubprocessTaskRunner
from evalglass.adapters.trace_jsonl import LocalJsonlTraceSource
from evalglass.adapters.trace_open_convention import OpenConventionTraceSource
from evalglass.core import (
    INTEGRITY_METADATA_KEY,
    SOURCE_METADATA_KEY,
    AuthorityInputs,
    ContractError,
    DataPolicy,
    DatasetStatus,
    Diagnostic,
    Evaluator,
    EvaluatorContext,
    EvalUnit,
    EvidenceBundle,
    Example,
    ExampleSelector,
    JudgeCalibration,
    JudgeEvidence,
    JudgeEvidenceStatus,
    MetricPlan,
    RunRecord,
    Score,
    ScoreBatch,
    Scorecard,
    ScoreStatus,
    Severity,
    ThresholdApproval,
    UnitKind,
    Validity,
    run_evaluation,
)
from evalglass.core.authority import JudgeCapability
from evalglass.core.comparison import build_comparison
from evalglass.core.provenance import BaselineState
from evalglass.harness.baseline import load_run_record
from evalglass.harness.calibration import derive_calibration, load_calibration
from evalglass.harness.config import (
    JudgeConfig,
    LaneConfig,
    MetricConfig,
    RuntimeConfig,
    TaskConfig,
    TraceConfig,
    TraceFormat,
)
from evalglass.harness.coverage import SourceCompleteness, SourceImportManifest
from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.evaluator_loader import load_evaluator
from evalglass.harness.judge import collect_judge_evidence
from evalglass.harness.judge_execution import JudgeCache, JudgeExecutor
from evalglass.harness.lanes import (
    LaneError,
    LanePort,
    LaneRegistry,
    LaneResult,
    LaneStatus,
    MissingPrerequisite,
    built_in_lanes,
)
from evalglass.harness.plan import (
    MISSING_PREREQUISITE,
    SELECTOR_MISMATCH,
    DeviationCode,
    EvaluationPlan,
    MetricView,
    PlanDeviation,
    build_plan,
)
from evalglass.harness.ports import (
    JudgeModel,
    JudgeRequest,
    JudgeResult,
    TaskRequest,
    TraceRead,
    TraceSource,
    TraceUnit,
)
from evalglass.harness.prepare import example_from_trace
from evalglass.harness.rubric import RubricRef, load_rubric, load_rubric_spec
from evalglass.harness.rubric_spec import RubricSpec
from evalglass.harness.units import select_units

# The framework version is read from the package's ``__version__`` (single source) rather
# than installed-dist metadata, so a *vendored* runtime — which has no installed dist — still
# reports the pinned version baked into its ``_evalglass/__init__`` (ADR 0011 version injection).
_FRAMEWORK = f"evalglass@{_EVALGLASS_VERSION}"

_ROUTE_ERROR_ID = "__evalglass_route_error__"

#: Higher means more restrictive; used to pick the worst data policy across sources.
_POLICY_SEVERITY: dict[DataPolicy, int] = {
    DataPolicy.PERMITTED: 0,
    DataPolicy.REDACTED: 1,
    DataPolicy.UNKNOWN: 2,
    DataPolicy.MISSING: 3,
    DataPolicy.FORBIDDEN: 4,
}

#: Only explicitly permitted/redacted data may leave the process (be sent to a replay
#: subprocess). Forbidden/missing/unknown all fail closed — egress requires an explicit policy.
_EGRESS_OK: frozenset[DataPolicy] = frozenset({DataPolicy.PERMITTED, DataPolicy.REDACTED})


def _egress_ok(policy: DataPolicy) -> bool:
    """Whether a source's data policy permits sending its data to a host subprocess (egress)."""
    return policy in _EGRESS_OK


def _load_trace_units(
    trace_units: Sequence[TraceUnit], kind: UnitKind
) -> list[tuple[Example, bool]]:
    """Convert normalized trace units to ``(Example, egress_ok)`` pairs for the kind (EG-P1).

    ``CALL`` is the unchanged per-call path — one Example per unit, paired with that unit's own
    egress (a record may override the source policy). A richer kind (``trajectory``/``session``)
    collapses each ``trace_id``'s call-level units into one aggregate Example via
    :func:`select_units`; because that drops the per-unit egress bool the runner relies on, the
    aggregate's egress is resolved here as the **worst of its members** — permitted iff *every*
    member is, so a single ``forbidden``/``unknown`` member blocks the aggregate (fail-closed).
    """
    if kind is UnitKind.CALL:
        return [
            (example_from_trace(unit), _egress_ok(unit.envelope.data_policy))
            for unit in trace_units
        ]
    egress_by_trace: dict[str, bool] = {}
    for unit in trace_units:
        trace_id = unit.unit.trace_id
        member_ok = _egress_ok(unit.envelope.data_policy)
        egress_by_trace[trace_id] = (
            member_ok
            if trace_id not in egress_by_trace
            else egress_by_trace[trace_id] and member_ok
        )
    return [
        (example, egress_by_trace[example.unit.trace_id])
        for example in select_units(trace_units, kind=kind)
    ]


def _judge_capability(judge_cfg: JudgeConfig | None) -> JudgeCapability:
    """The selected adapter's capability, read from the adapter class without constructing it.

    The capability is a static property of the adapter *kind*, so reading the class attribute (not a
    name->capability map) keeps it owned by the adapter while avoiding credential resolution or
    endpoint validation during the side-effect-free preflight.
    """
    adapter = judge_cfg.adapter if judge_cfg is not None else "fake"
    if adapter == "command":
        return SubprocessJudgeModel.capability
    if adapter == "openai_compatible":
        from evalglass.adapters.judge_openai import OpenAICompatibleJudgeModel

        return OpenAICompatibleJudgeModel.capability
    return FakeJudgeModel.capability


class _UnavailableJudgeModel:
    """A ``JudgeModel`` stand-in for when the configured judge cannot be built (e.g. an unset
    credential). Every request yields ``MISSING`` evidence with a diagnostic and no value — a build
    failure is an unavailable state, never a fabricated score — and it performs no effect.
    """

    capability = JudgeCapability.MEASUREMENT

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def judge(self, request: JudgeRequest) -> JudgeResult:
        return JudgeResult(
            example_id=request.example_id,
            metric=request.metric,
            status=JudgeEvidenceStatus.MISSING,
            diagnostics=[
                setup_diagnostic(
                    "judge_unavailable",
                    f"judge model unavailable: {self._reason}",
                    location=request.example_id,
                )
            ],
        )


def _build_judge_model(
    judge_cfg: JudgeConfig | None,
    root: Path,
    rubric_specs: Mapping[str, RubricSpec] | None = None,
) -> JudgeModel:
    """Select and construct the judge adapter from config (an effectful build).

    ``command`` (ADR 0042) and ``openai_compatible`` (ADR 0052) are real measurement instruments;
    the required tier's default stays the hermetic ``fake``. The OpenAI adapter is imported lazily,
    so a fake/command (or no-judge) run never imports it, and its credential is resolved from the
    environment *here*, at effect time — never stored in config, plan, provenance, or any artifact.
    A declared-but-unset credential raises :class:`MissingPrerequisite` (an unavailable state, never
    a score). Data-policy egress is enforced upstream in ``collect_judge_evidence`` for every
    adapter, so none can send forbidden data.
    """
    if judge_cfg is not None and judge_cfg.adapter == "command":
        return SubprocessJudgeModel(
            command=judge_cfg.command, root=root, timeout_s=judge_cfg.timeout_seconds
        )
    if judge_cfg is not None and judge_cfg.adapter == "openai_compatible":
        from evalglass.adapters.judge_openai import OpenAICompatibleJudgeModel

        api_key: str | None = None
        if judge_cfg.credential_env:
            api_key = os.environ.get(judge_cfg.credential_env)
            if not api_key:
                raise MissingPrerequisite(
                    f"judge credential environment variable {judge_cfg.credential_env!r} is not set"
                )
        return OpenAICompatibleJudgeModel(
            endpoint=judge_cfg.endpoint,
            model=judge_cfg.model or "",
            api_key=api_key,
            rubric_specs=dict(rubric_specs or {}),
            timeout_s=judge_cfg.timeout_seconds,
            max_chars=judge_cfg.max_input_chars,
            max_tokens=judge_cfg.max_output_tokens,
            response_format=judge_cfg.response_format,
            allow_loopback=judge_cfg.allow_insecure_loopback,
            headers=dict(judge_cfg.headers),
        )
    return FakeJudgeModel(default_value=judge_cfg.default_value if judge_cfg else None)


def _instrument_fingerprint(judge_cfg: JudgeConfig, rubrics: Mapping[str, RubricRef]) -> str:
    """A stable, secret-free string identifying the judge instrument for the cache key.

    Combines the judge's non-secret provenance (adapter/endpoint/model/decoding) with each rubric's
    provenance (refs + content fingerprint), so a model, endpoint, or rubric change invalidates the
    cache. The credential is never part of it (``provenance()`` excludes it).
    """
    import hashlib
    import json

    body = json.dumps(
        {
            "judge": judge_cfg.provenance(),
            "rubrics": {name: ref.provenance() for name, ref in sorted(rubrics.items())},
        },
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _build_judge_executor(
    judge_cfg: JudgeConfig | None,
    model: JudgeModel,
    rubrics: Mapping[str, RubricRef],
    root: Path,
) -> JudgeExecutor | None:
    """Build the cache/budget/retry executor when the host configured an execution policy (C3)."""
    if judge_cfg is None or judge_cfg.execution is None:
        return None
    import time

    policy = judge_cfg.execution
    cache = JudgeCache(root, policy.cache_dir, policy.cache_mode)
    fingerprint = _instrument_fingerprint(judge_cfg, rubrics)
    return JudgeExecutor(model, policy, cache, fingerprint, sleep=time.sleep, clock=time.monotonic)


def _replay_or_passthrough(
    config: RuntimeConfig,
    root: Path,
    loaded: list[tuple[Example, bool]],
    replay_ids: set[str],
) -> tuple[list[tuple[Example, bool]], list[str], list[Diagnostic]]:
    """Fill missing outputs via the host task for the plan's replay subjects, else pass through.

    Data policy is enforced BEFORE the effect — a non-egress subject is never sent to the
    subprocess. A replayed-task failure becomes a route diagnostic, so the incomplete-evidence path
    blocks an active gate. With no ``config.task`` the loaded subjects pass through unchanged.
    """
    if config.task is None:
        return loaded, [], []
    examples_eg, replay_diagnostics, replay_handled = _replay_missing(
        config.task, root, loaded, replay_ids
    )
    return examples_eg, replay_handled, replay_diagnostics


def _collect_judge(
    config: RuntimeConfig,
    plan: EvaluationPlan,
    example_by_subject: Mapping[str, Example],
    rubrics: Mapping[str, RubricRef],
    root: Path,
) -> tuple[list[JudgeEvidence], list[Diagnostic], list[str]]:
    """Collect judge evidence for the plan's eligible effects (M4), under any execution policy (C3).

    Returns ``([], [], [])`` when the plan has no judge effects. A configured judge that cannot be
    built (e.g. an unset credential) is unavailable — every planned effect gets typed MISSING
    evidence and no provider call — never a fabricated score.
    """
    if not plan.judge_effects():
        return [], [], []
    try:
        model = _build_judge_model(config.judge, root, _rubric_specs(config, root))
    except MissingPrerequisite as exc:
        model = _UnavailableJudgeModel(str(exc))
    executor = _build_judge_executor(config.judge, model, rubrics, root)
    return collect_judge_evidence(model, plan, example_by_subject, rubrics, executor=executor)


def _rubric_specs(config: RuntimeConfig, root: Path) -> dict[str, RubricSpec]:
    """Each judge metric's structured rubric (markdown loads as a scalar spec) keyed by metric.

    The judge scores against this host-owned content; a structured rubric drives the structured
    response contract, a markdown rubric the scalar one.
    """
    return {
        metric.spec.name: load_rubric_spec(metric.rubric, root)
        for metric in config.metrics
        if metric.rubric is not None
    }


@dataclass(frozen=True)
class Preflight:
    """The pre-effect resolution shared by ``run``, ``run --dry-run``, and ``preflight``.

    Everything here is computed without any external effect: sources are read from local files,
    calibration reads host-owned files, and the plan is projected purely. No replay subprocess,
    judge call, or network egress happens — those are driven from ``plan`` by ``run_config``.
    """

    plan: EvaluationPlan
    loaded: list[tuple[Example, bool]]
    source_names: list[str]
    effective_metrics: list[MetricConfig]
    rubrics: dict[str, RubricRef]
    route_diagnostics: list[Diagnostic]
    pre_lane_results: list[LaneResult]
    lane_trace_policies: list[DataPolicy]
    source_manifests: list[dict[str, Any]]


def _load_sources(
    config: RuntimeConfig, root: Path
) -> tuple[list[tuple[Example, bool]], list[str], list[Diagnostic], list[dict[str, Any]]]:
    """Read every configured dataset + local trace into ``(Example, egress_ok)`` pairs (no egress).

    Each loaded example is paired with whether its data policy permits host egress (replay/judge),
    tracked per example *instance* — never by example_id, which is host-supplied and not globally
    unique — and per *record* for traces (a record may override the source policy). It also records,
    parallel to ``loaded``, each subject's configured-source name so a bound metric can scope its
    population to its candidate sources (D1). Every source read also yields one coverage manifest
    (B2), collected here for the RunRecord side channel.
    """
    loaded: list[tuple[Example, bool]] = []
    source_names: list[str] = []
    route_diagnostics: list[Diagnostic] = []
    manifests: list[dict[str, Any]] = []
    for ds_cfg in config.datasets:
        read = LocalJsonlDatasetStore(ds_cfg, root).read()
        route_diagnostics.extend(read.diagnostics)
        if read.manifest is not None:
            manifests.append(read.manifest.to_dict())
        ds_egress_ok = _egress_ok(read.data_policy)
        loaded.extend((example, ds_egress_ok) for example in read.examples)
        source_names.extend(ds_cfg.name for _ in read.examples)
    for tr_cfg in config.traces:
        tread = _trace_source(tr_cfg, root).read()
        route_diagnostics.extend(tread.diagnostics)
        if tread.manifest is not None:
            manifests.append(tread.manifest.to_dict())
        # CALL (default) pairs each unit with its own egress; a richer ``unit:`` kind collapses
        # the trace's units into aggregate Examples paired with worst-of-members egress (EG-P1).
        units = _load_trace_units(tread.units, tr_cfg.kind)
        loaded.extend(units)
        source_names.extend(tr_cfg.name for _ in units)
    return loaded, source_names, route_diagnostics, manifests


def preflight(config: RuntimeConfig, root: Path, *, run_lanes: bool) -> Preflight:
    """Resolve sources, calibration, and the applicability/effect plan without any effect.

    ``run_lanes`` gates the pre-core TRACE_SOURCE lanes: ``run_config`` runs them (a local/enabled
    lane normalizes its spans into the run), while ``preflight``/``--dry-run`` pass ``False`` so a
    preview never triggers a live pull. Calibration reads host-owned files (no egress); the judge
    adapter capability comes from its constructor (no I/O).
    """
    loaded, source_names, route_diagnostics, source_manifests = _load_sources(config, root)
    pre_lane_results: list[LaneResult] = []
    lane_trace_policies: list[DataPolicy] = []
    if run_lanes:
        # Pre-core lane dispatch (ADR 0031, EG-H0-5): a configured TRACE_SOURCE lane normalizes its
        # spans to evidence here; opt-in JUDGE_MODEL/TASK_RUNNER lanes are recorded skipped.
        pre_lane_results, lane_trace_policies = _attach_pre_core_lanes(
            config.lanes, root, loaded, source_names, route_diagnostics, source_manifests
        )
    # EG-NR-1: the capability is read from the selected adapter itself (not a config name) so a
    # judge metric's authority reflects what kind of instrument produced its evidence.
    rubrics = _load_rubrics(config, root)
    judge_capability = (
        _judge_capability(config.judge)
        if any("judge" in m.spec.required_evidence for m in config.metrics)
        else None
    )
    effective_metrics = [
        _apply_calibration(metric, root, judge_capability=judge_capability)
        for metric in config.metrics
    ]
    # D1: when any metric binds sources, stamp each subject's configured-source name into its
    # metadata so a bound metric scores only its candidate sources through the one selector
    # implementation (a bound metric's scored population then equals its planned one). With no bound
    # metric the examples are untouched, so an unbound run stays byte-identical.
    if any(m.sources for m in config.metrics):
        loaded = [
            (replace(example, metadata={**example.metadata, SOURCE_METADATA_KEY: name}), egress)
            for (example, egress), name in zip(loaded, source_names, strict=True)
        ]
    plan = build_plan(
        run_id=config.run_id,
        subjects_in=loaded,
        metrics=[_metric_view(m, rubrics) for m in effective_metrics],
        source_names=source_names,
    )
    return Preflight(
        plan=plan,
        loaded=loaded,
        source_names=source_names,
        effective_metrics=effective_metrics,
        rubrics=rubrics,
        route_diagnostics=route_diagnostics,
        pre_lane_results=pre_lane_results,
        lane_trace_policies=lane_trace_policies,
        source_manifests=source_manifests,
    )


def run_config(config: RuntimeConfig, root: Path) -> RunRecord:
    """Read sources, converge routes, run the core, and return an honest ``RunRecord``."""
    # Resolve the whole pre-effect plan once (sources, calibration, applicability), then drive
    # replay and judge collection from it — the SAME plan `preflight`/`--dry-run` build, so the
    # previewed population is the executed population. The preflight is effect-free.
    pf = preflight(config, root, run_lanes=True)
    plan = pf.plan
    loaded = pf.loaded
    route_diagnostics = list(pf.route_diagnostics)
    rubrics = pf.rubrics
    effective_metrics = pf.effective_metrics
    pre_lane_results = pf.pre_lane_results
    lane_trace_policies = pf.lane_trace_policies
    replay_ids = {effect.subject_id for effect in plan.replay_effects()}

    # M2 replay: fill missing outputs by running the host task (opt-in via config.task), for the
    # plan's replay subjects only.
    examples_eg, replay_handled, replay_diagnostics = _replay_or_passthrough(
        config, root, loaded, replay_ids
    )
    route_diagnostics.extend(replay_diagnostics)

    # Map each plan subject id to its (post-replay) Example (order-preserving: ``s{i}`` is the
    # i-th loaded subject), so the judge collector resolves the concrete evidence for a planned
    # effect without reselecting a population of its own.
    example_by_subject = {f"s{i}": example for i, (example, _eg) in enumerate(examples_eg)}

    # M4 judge evidence: collect for the plan's eligible judge effects ONLY (no metric-by-example
    # Cartesian product). A denied effect yields typed MISSING evidence, never a provider call.
    # Judge diagnostics surface on the Scorecard but never trigger the input-level route-error
    # block — a judge failure blocks only its own gating metric (through the judge evaluator).
    judge_evidence, judge_diagnostics, judge_handled = _collect_judge(
        config, plan, example_by_subject, rubrics, root
    )

    # Reconcile planned vs handled effects. An executed-but-unplanned effect is an integrity
    # failure (an active gate must not pass over it, so it forces the route-error block); a
    # planned-but-unexecuted effect is a typed deviation, never a fabricated numeric zero.
    handled_effect_ids = [*replay_handled, *judge_handled]
    deviations = plan.reconcile(handled_effect_ids)
    executed_unplanned = any(d.code is DeviationCode.EXECUTED_NOT_PLANNED for d in deviations)

    examples = [example for example, _ in examples_eg]
    evidence = EvidenceBundle(runtime_errors=route_diagnostics, judge_evidence=judge_evidence)
    incomplete = bool(route_diagnostics) or executed_unplanned
    if incomplete:
        # One run-level error measurement per metric (every metric scores it) so an active
        # gate blocks on incomplete evidence instead of passing over the records that parsed.
        examples.append(_route_error_example())

    plans = _build_metric_plans(
        config, effective_metrics, root, lane_trace_policies, incomplete=incomplete
    )

    # Load the promoted baseline (if configured) so the core can resolve comparability and D4 can
    # build the paired comparison from its scores. A configured-but-unloadable baseline is a setup
    # error; an absent config means no baseline.
    baseline_record = load_run_record(root / config.baseline_path) if config.baseline_path else None
    baseline = baseline_record.provenance if baseline_record is not None else None

    try:
        record = run_evaluation(
            run_id=config.run_id,
            examples=examples,
            evidence=evidence,
            plans=plans,
            dimensions=_dimensions(config, examples, rubrics, effective_metrics),
            baseline=baseline,
            comparison_requested=config.comparison_requested,
        )
    except ContractError as exc:
        # A host evaluator that returns an undeclared/out-of-range score is a setup/infra
        # problem, not a host quality failure — surface it as a setup error, not a verdict.
        raise SetupError(
            setup_diagnostic(
                "evaluator_contract", f"an evaluator violated the score contract: {exc}"
            )
        ) from exc

    # D3: enrich each metric's terminal population (set by the core from raw scores) with the plan's
    # pre-effect coverage (available/selector-matched/eligible) so the persisted summary reconciles
    # the plan and the scores. Additive: a metric absent from the plan keeps terminal-only counts.
    record = replace(record, scorecard=_enrich_populations(record.scorecard, plan))

    # D4: attach the run's typed paired comparison (the primary carrier of honest change) built from
    # the verified baseline + the comparability the core resolved. Present only when a baseline was
    # configured, so a run without one stays byte-identical. Sets no verdict.
    record = _attach_comparison(record, baseline_record, effective_metrics)

    # Surface route diagnostics on the Scorecard so malformed records are visible to a reader.
    # This adds explanatory diagnostics only — verdict, authority, and scores are unchanged.
    extra_diagnostics = [*route_diagnostics, *judge_diagnostics]
    if extra_diagnostics:
        scorecard = replace(
            record.scorecard,
            diagnostics=[*record.scorecard.diagnostics, *extra_diagnostics],
        )
        record = replace(record, scorecard=scorecard)

    # Runner-attach seam (ADR 0031): fold every configured lane's LaneResult into the RunRecord
    # side channel — the pre-core (trace/judge) results collected above, then the post-core
    # SCORE_SINK results over the finished Scorecard. A lane informs, it never decides: no result
    # reaches verdict/authority/Scorecard construction. Emitting only when non-empty keeps no-lane
    # runs byte-identical to pre-seam runs.
    lane_results = [
        *(result.to_dict() for result in pre_lane_results),
        *_attach_lanes(config.lanes, record.scorecard, root),
    ]
    if lane_results:
        record = replace(record, lane_results=lane_results)
    # Persist per-source coverage manifests (B2): dataset, local-trace, and lane completeness.
    # Additive evidence, never authority — off the Scorecard so an empty/partial import cannot look
    # complete yet never touches verdict/CI/exit.
    if pf.source_manifests:
        record = replace(record, source_manifests=pf.source_manifests)
    # Persist the complete judge evidence (C4), resolvable from Score.evidence_refs so a report
    # explains a score with no host cache. Additive evidence, off the Scorecard.
    record = _with_persisted_evidence(record, config, judge_evidence)
    # Persist the plan/execution reconciliation on the RunRecord (digest + planned/
    # handled/deviated counts + typed deviations). Additive evidence, never authority — deliberately
    # off the Scorecard so verdict/CI/exit stay plan-free.
    return replace(record, plan=_plan_reconciliation_dict(plan, handled_effect_ids, deviations))


# The lane ports the seam dispatches *after* the core, consuming the finished Scorecard. Pre-core
# ports (TRACE_SOURCE / JUDGE_MODEL) attach through their own routes in EG-H0-5.
_POST_CORE_LANE_PORTS: frozenset[LanePort] = frozenset({LanePort.SCORE_SINK})


def _attach_lanes(
    lanes: list[LaneConfig], scorecard: Scorecard, root: Path
) -> list[dict[str, Any]]:
    """Run configured, enabled post-core lanes; return their serialized ``LaneResult``s.

    Only enabled lanes run, and only post-core ports here (a SCORE_SINK consumes the finished
    Scorecard). A missing prerequisite skips; any setup/runtime failure is a blocked result. The
    returned dicts are folded into ``RunRecord.lane_results`` only — never into the verdict.
    """
    enabled = [lane for lane in lanes if lane.enabled]
    if not enabled:
        return []
    registry = built_in_lanes()
    results: list[LaneResult] = []
    for lane_cfg in enabled:
        if registry.get(lane_cfg.name).port in _POST_CORE_LANE_PORTS:
            results.append(_run_score_sink_lane(registry, lane_cfg, scorecard, root))
    return [result.to_dict() for result in results]


def _run_score_sink_lane(
    registry: LaneRegistry, lane_cfg: LaneConfig, scorecard: Scorecard, root: Path
) -> LaneResult:
    """Resolve + run one post-core SCORE_SINK lane, fail-closed (ADR 0031; never raises).

    A missing prerequisite is a clean ``skipped``; any setup *or* export failure is a ``blocked``
    result — optional lane code must never abort the run. The lane is handed a **deep copy** of the
    Scorecard, so even a misbehaving lane that mutates its argument's lists/dicts cannot change the
    returned record's verdict (the byte-identity guarantee holds regardless of the lane).
    """
    if "data_policy" in lane_cfg.options:
        # The egress policy is the TYPED, fail-closed ``LaneConfig.data_policy`` field. Letting an
        # untyped ``options.data_policy`` through would let a conflicting value silently widen
        # egress past the declared policy (a forbidden lane connecting because options said
        # permitted). The ambiguity is a setup error, not a silent override.
        return _blocked_lane(
            lane_cfg.name,
            "lane_setup_failed",
            "lane setup failed: data_policy is the typed lane field and must not be set in options",
        )
    try:
        factory = registry.resolve(lane_cfg.name)
        # Thread the host-declared, typed data_policy into the sink factory so an upload-shaped sink
        # can gate egress before any effect; a sink that writes only locally accepts and ignores it.
        # The typed field is authoritative (options cannot carry data_policy — rejected above).
        options = {"data_policy": lane_cfg.data_policy.value, **lane_cfg.options}
        sink = factory(root=root, **options)
    except MissingPrerequisite as exc:
        # An expected, benign absence (no destination configured) → a clean skip.
        return LaneResult(lane=lane_cfg.name, status=LaneStatus.SKIPPED, report=str(exc))
    except (LaneError, TypeError, ValueError) as exc:
        # A misconfigured lane is a blocked result + diagnostic — never a crashed run.
        return _blocked_lane(lane_cfg.name, "lane_setup_failed", f"lane setup failed: {exc}")
    try:
        # ``sink`` is resolved lazily (Any) so the lane module stays out of the required import
        # closure; its ``export`` returns a LaneResult by the ScorecardExportSink contract. The
        # lane sees an isolated copy, never the live Scorecard.
        return cast("LaneResult", sink.export(deepcopy(scorecard)))
    except MissingPrerequisite as exc:
        return LaneResult(lane=lane_cfg.name, status=LaneStatus.SKIPPED, report=str(exc))
    except Exception as exc:  # a lane must never raise into the run (ADR 0031)
        return _blocked_lane(lane_cfg.name, "lane_export_failed", f"lane export failed: {exc}")


def _blocked_lane(name: str, code: str, message: str) -> LaneResult:
    return LaneResult(
        lane=name,
        status=LaneStatus.BLOCKED,
        report=message,
        diagnostics=[Diagnostic(code=code, severity=Severity.ERROR, message=message)],
    )


# Opt-in ports whose evidence integration is a deferred (live_lane) follow-up: in the required
# tier they are recorded as a skipped side-channel result and never run / egress (EG-H0-5).
_PRE_CORE_DEFERRED_PORTS: frozenset[LanePort] = frozenset(
    {LanePort.JUDGE_MODEL, LanePort.TASK_RUNNER}
)


def _attach_pre_core_lanes(
    lanes: list[LaneConfig],
    root: Path,
    loaded: list[tuple[Example, bool]],
    source_names: list[str],
    route_diagnostics: list[Diagnostic],
    source_manifests: list[dict[str, Any]],
) -> tuple[list[LaneResult], list[DataPolicy]]:
    """Dispatch configured enabled pre-core lanes; contribute TRACE_SOURCE units to the run.

    A TRACE_SOURCE lane normalizes its spans and appends its units to ``loaded`` (and its policy to
    the returned list, for worst-source authority) and its coverage manifest to ``source_manifests``
    (B2 — a skipped lane still records a BLOCKED manifest). A JUDGE_MODEL/TASK_RUNNER lane is a
    skipped result — opt-in, not run in the required tier. SCORE_SINK lanes are handled post-core.
    """
    enabled = [lane for lane in lanes if lane.enabled]
    if not enabled:
        return [], []
    registry = built_in_lanes()
    results: list[LaneResult] = []
    trace_policies: list[DataPolicy] = []
    for lane_cfg in enabled:
        port = registry.get(lane_cfg.name).port
        if port is LanePort.TRACE_SOURCE:
            results.append(
                _run_trace_source_lane(
                    registry,
                    lane_cfg,
                    root,
                    loaded,
                    source_names,
                    route_diagnostics,
                    trace_policies,
                    source_manifests,
                )
            )
        elif port in _PRE_CORE_DEFERRED_PORTS:
            results.append(_deferred_pre_core_lane(lane_cfg.name, port))
    return results, trace_policies


def _lane_blocked_manifest(lane_cfg: LaneConfig, message: str) -> dict[str, Any]:
    """A BLOCKED coverage manifest for a lane that never yielded a TraceRead (setup fault/skip)."""
    return SourceImportManifest(
        source=lane_cfg.name,
        kind="trace_lane",
        adapter=lane_cfg.name,
        data_policy=lane_cfg.data_policy,
        completeness=SourceCompleteness.BLOCKED,
        records_seen=0,
        units_emitted=0,
        rejected=0,
        diagnostics=[Diagnostic(code="lane_not_read", severity=Severity.INFO, message=message)],
    ).to_dict()


def _run_trace_source_lane(
    registry: LaneRegistry,
    lane_cfg: LaneConfig,
    root: Path,
    loaded: list[tuple[Example, bool]],
    source_names: list[str],
    route_diagnostics: list[Diagnostic],
    trace_policies: list[DataPolicy],
    source_manifests: list[dict[str, Any]],
) -> LaneResult:
    """Resolve + read one TRACE_SOURCE lane, fail-closed; append its units + manifest to the run."""
    try:
        factory = registry.resolve(lane_cfg.name)
        # The lane's declared data_policy is the default for its source (so a host need not
        # duplicate it inside options); an explicit options value still wins.
        options = {"data_policy": lane_cfg.data_policy.value, **lane_cfg.options}
        source = factory(root=root, **options)
    except MissingPrerequisite as exc:
        source_manifests.append(_lane_blocked_manifest(lane_cfg, str(exc)))
        return LaneResult(lane=lane_cfg.name, status=LaneStatus.SKIPPED, report=str(exc))
    except (LaneError, TypeError, ValueError) as exc:
        source_manifests.append(_lane_blocked_manifest(lane_cfg, f"lane setup failed: {exc}"))
        return _blocked_lane(lane_cfg.name, "lane_setup_failed", f"lane setup failed: {exc}")
    try:
        tread = cast("TraceRead", source.read())
    except MissingPrerequisite as exc:
        source_manifests.append(_lane_blocked_manifest(lane_cfg, str(exc)))
        return LaneResult(lane=lane_cfg.name, status=LaneStatus.SKIPPED, report=str(exc))
    except Exception as exc:  # a lane must never raise into the run (ADR 0031)
        source_manifests.append(_lane_blocked_manifest(lane_cfg, f"lane read failed: {exc}"))
        return _blocked_lane(lane_cfg.name, "lane_read_failed", f"lane read failed: {exc}")
    route_diagnostics.extend(tread.diagnostics)
    trace_policies.append(tread.data_policy)
    if tread.manifest is not None:
        source_manifests.append(tread.manifest.to_dict())
    # A TRACE_SOURCE lane is CALL-only: ``LaneConfig`` carries no ``unit:`` field, so aggregate
    # (trajectory/session) grading is reachable through the built-in ``traces:`` route only (the
    # EG-P1 scope; ADR 0045). Each lane unit stays a per-call Example paired with its own egress.
    lane_units = _load_trace_units(tread.units, UnitKind.CALL)
    loaded.extend(lane_units)
    source_names.extend(lane_cfg.name for _ in lane_units)
    if tread.diagnostics and not tread.units:
        # A read-level failure (backend unavailable / malformed response) yields no usable units —
        # report blocked + the read diagnostics, never a hollow "ran / normalized 0 unit(s)".
        return LaneResult(
            lane=lane_cfg.name,
            status=LaneStatus.BLOCKED,
            report=f"the {lane_cfg.name} lane read produced no usable units",
            diagnostics=list(tread.diagnostics),
        )
    # Partial success: units DID normalize (they join the run), but per-span mapping diagnostics
    # are carried on the lane_result too — so the side channel is as faithful as the BLOCKED branch
    # above, never a clean "ran / 0 diagnostics" hiding a partial mapping failure. This only
    # enriches the side channel; the diagnostics already reached route_diagnostics/Scorecard above,
    # so the verdict and authority are unchanged.
    partial = f" with {len(tread.diagnostics)} mapping diagnostic(s)" if tread.diagnostics else ""
    units_msg = f"normalized {len(tread.units)} trace unit(s) from the {lane_cfg.name} lane"
    return LaneResult(
        lane=lane_cfg.name,
        status=LaneStatus.RAN,
        report=units_msg + partial,
        diagnostics=list(tread.diagnostics),
    )


def _deferred_pre_core_lane(name: str, port: LanePort) -> LaneResult:
    """An opt-in JUDGE_MODEL/TASK_RUNNER lane: recorded skipped, never run in the required tier."""
    return LaneResult(
        lane=name,
        status=LaneStatus.SKIPPED,
        report=f"the opt-in {port.value} lane {name!r} is not run in the hermetic required tier; "
        "its evidence integration is a deferred live-lane follow-up",
    )


def _replay_missing(
    task_config: TaskConfig, root: Path, loaded: list[tuple[Example, bool]], replay_ids: set[str]
) -> tuple[list[tuple[Example, bool]], list[Diagnostic], list[str]]:
    """Replay the plan's replay subjects (missing output) through the host ``TaskRunner``.

    ``replay_ids`` is the set of plan subject ids (``s{i}``, aligned to ``loaded`` order) the plan
    marked for replay — output-less subjects that at least one metric's selector matches. A subject
    the plan did not mark (matched by no metric) is left output-less and un-replayed, so no
    subprocess is spawned for evidence nothing consumes. A successful replay fills ``output`` from
    the parsed task result; a failed replay yields no output and surfaces typed infrastructure
    diagnostics (which block an active gate downstream). Only the normalized output value reaches an
    evaluator — never the subprocess result. Returns the handled replay effect ids to reconcile.
    """
    runner = SubprocessTaskRunner(task_config, root)
    out: list[tuple[Example, bool]] = []
    diagnostics: list[Diagnostic] = []
    handled: list[str] = []
    for index, (example, egress_ok) in enumerate(loaded):
        subject_id = f"s{index}"
        if example.output is not None or subject_id not in replay_ids:
            out.append((example, egress_ok))
            continue
        handled.append(f"replay:{subject_id}")
        if not egress_ok:
            # Data policy is enforced BEFORE the effect: this subject is not egress-OK, so no
            # subprocess is spawned for it. It stays output-less (non_evaluable); an active gate is
            # already blocked by the policy via authority.
            diagnostics.append(
                setup_diagnostic(
                    "replay_egress_forbidden",
                    f"data policy forbids host egress for example {example.example_id!r}; "
                    "the replay subprocess was not invoked",
                    location=example.example_id,
                )
            )
            out.append((example, egress_ok))
            continue
        result = runner.run(TaskRequest(example_id=example.example_id, input=example.input))
        if result.diagnostics:
            diagnostics.extend(result.diagnostics)
            out.append((example, egress_ok))  # output-less; the route-error path blocks a gate
        else:
            out.append((replace(example, output=result.output), egress_ok))
    return out, diagnostics, handled


def _metric_view(metric: MetricConfig, rubrics: Mapping[str, RubricRef]) -> MetricView:
    """Project a ``MetricConfig`` to the minimal facts the planner needs (one selector source)."""
    ref = rubrics.get(metric.spec.name)
    return MetricView(
        name=metric.spec.name,
        selector=metric.selector,
        is_judge="judge" in metric.spec.required_evidence,
        is_reference=metric.spec.lens.value == "reference",
        prerequisites=list(metric.spec.required_evidence),
        rubric_ref=ref.path if ref is not None else None,
        candidate_sources=metric.candidate_source_names(),
        source_bindings=([b.to_dict() for b in metric.sources] if metric.sources else None),
    )


def _enrich_populations(scorecard: Scorecard, plan: EvaluationPlan) -> Scorecard:
    """Add the plan's pre-effect coverage to each metric's terminal population summary (D3).

    The core set the terminal counts (scored_valid/non_evaluable/blocked/skipped/error) from the raw
    scores; here we join the plan's per-metric ledger (available / selector-matched / selector- and
    prerequisite-excluded / eligible) by metric name, so the persisted summary reconciles the plan
    and the scores. A metric with no matching plan entry keeps its terminal-only counts.
    """
    planned = {pm.metric: pm for pm in plan.metrics}
    enriched = []
    for pop in scorecard.populations:
        pm = planned.get(pop.metric)
        if pm is None:
            enriched.append(pop)
            continue
        enriched.append(
            pop.with_plan_population(
                available=pm.available,
                selector_matched=pm.selector_matched,
                selector_excluded=pm.excluded.get(SELECTOR_MISMATCH, 0),
                eligible=pm.eligible,
                prerequisite_excluded=pm.excluded.get(MISSING_PREREQUISITE, 0),
            )
        )
    return replace(scorecard, populations=enriched)


def _scoring_selector(metric: MetricConfig) -> ExampleSelector | None:
    """The selector the core scores a metric with — its ``applies_to`` plus its source binding (D1).

    An unbound metric keeps exactly its user selector (byte-identical). A bound metric ANDs a
    reserved source-name constraint onto its user selector, so it scores only subjects from its
    candidate sources (an integrity subject still bypasses). This reuses the one applicability
    implementation rather than teaching the core about sources.
    """
    candidates = metric.candidate_source_names()
    if candidates is None:
        return metric.selector
    # ANDs a reserved source constraint onto the user selector (integrity subjects still bypass).
    constraints: dict[str, tuple[Any, ...]] = {}
    if metric.selector is not None:
        constraints.update(metric.selector.constraints)
    constraints[SOURCE_METADATA_KEY] = tuple(sorted(candidates))
    return ExampleSelector(constraints=constraints)


def _build_metric_plans(
    config: RuntimeConfig,
    effective_metrics: Sequence[MetricConfig],
    root: Path,
    lane_trace_policies: list[DataPolicy],
    *,
    incomplete: bool,
) -> list[MetricPlan]:
    """One ``MetricPlan`` per metric: isolated evaluator, scoped authority, scoping selector."""
    plans: list[MetricPlan] = []
    for metric in effective_metrics:
        _check_dataset_ref(config, metric)
        evaluator = _isolate_evaluator(
            load_evaluator(metric.spec.evaluator_ref, root), metric.spec.evaluator_ref
        )
        if incomplete:
            evaluator = _guard_evaluator(evaluator)
        plans.append(
            MetricPlan(
                spec=metric.spec,
                evaluator=evaluator,
                # D2: a bound metric resolves authority over only the sources it consumes; an
                # unbound metric keeps the conservative run-global worst.
                authority=_metric_authority_inputs(metric, config, lane_trace_policies),
                threshold=metric.threshold,
                params=metric.params,
                decision_policy=metric.decision_policy,
                # K2 + D1: score only this metric's declared call site (applies_to) within its bound
                # candidate sources; absent selector + no bindings -> every example (unchanged).
                selector=_scoring_selector(metric),
            )
        )
    return plans


def _with_persisted_evidence(
    record: RunRecord, config: RuntimeConfig, judge_evidence: list[JudgeEvidence]
) -> RunRecord:
    """Attach the parsed judge evidence to the record (C4); raw response dropped unless opted in."""
    if not judge_evidence:
        return record
    retain = config.judge is not None and config.judge.retain_raw_response
    persisted = (
        list(judge_evidence) if retain else [e.without_raw_response() for e in judge_evidence]
    )
    return replace(record, evidence=persisted)


def _attach_comparison(
    record: RunRecord, baseline_record: RunRecord | None, metrics: Sequence[MetricConfig]
) -> RunRecord:
    """Build + attach the typed paired comparison (D4) when a baseline was loaded; else unchanged.

    A numeric delta exists only when the run is comparable; every other state explains why not. The
    builder is the same one the drift watcher uses, so ``run`` and ``watch`` cannot diverge.
    """
    if baseline_record is None or record.comparable is None:
        return record
    state = record.comparable.state
    changed = record.comparable.changed_dimensions if state is BaselineState.NOT_COMPARABLE else ()
    comparison = build_comparison(
        current_scores=record.scores,
        baseline_scores=baseline_record.scores,
        baseline_run_id=baseline_record.run_id,
        state=state,
        changed_dimensions=changed,
        directions={m.spec.name: m.spec.direction for m in metrics},
    )
    return replace(record, scorecard=replace(record.scorecard, comparison=comparison))


def _plan_reconciliation_dict(
    plan: EvaluationPlan, handled: list[str], deviations: list[PlanDeviation]
) -> dict[str, Any]:
    """The Harness-owned plan/execution reconciliation persisted on ``RunRecord.plan``."""
    return {
        "schema": plan.schema,
        "fingerprint": plan.fingerprint(),
        "planned": len(plan.effects),
        "handled": len(handled),
        "deviated": len(deviations),
        "deviations": [d.to_dict() for d in deviations],
    }


def _route_error_example() -> Example:
    unit = EvalUnit(unit_id=_ROUTE_ERROR_ID, kind=UnitKind.CALL, trace_id=_ROUTE_ERROR_ID)
    # Flag it as a run-integrity example so it bypasses any per-metric selector (K2): an
    # incomplete-input run must still block an active gate, even a selector-scoped one.
    return Example(
        example_id=_ROUTE_ERROR_ID,
        input=None,
        output=None,
        unit=unit,
        metadata={INTEGRITY_METADATA_KEY: True},
    )


_MAX_CAUSE_CHARS = 200


def _isolate_evaluator(evaluator: Evaluator, ref: str) -> Evaluator:
    """Isolate a host evaluator so an arbitrary crash in its body is a typed setup error (EG-NR-5).

    An evaluator that raises an ordinary exception (``KeyError``, ``ValueError``, …) is an
    infrastructure/setup failure, not a host-quality result: it becomes an ``evaluator_crashed``
    setup error (exit ``2``), never a fabricated low score and never an uncaught traceback reading
    like a quality fail. A score-*contract* violation (``ContractError``, raised by the core when a
    returned Score is undeclared/out-of-range) is re-raised untouched so it keeps its distinct
    ``evaluator_contract`` code. ``KeyboardInterrupt``/``SystemExit`` are not ``Exception``
    subclasses and propagate untouched. The original exception is chained so the CLI's
    ``--debug`` can surface the real traceback.
    """

    def isolated(
        example: Example, context: EvaluatorContext, evidence: EvidenceBundle
    ) -> Score | ScoreBatch:
        try:
            result = evaluator(example, context, evidence)
        except ContractError:
            raise
        except Exception as exc:
            cause = f"{type(exc).__name__}: {exc}"
            raise SetupError(
                setup_diagnostic(
                    "evaluator_crashed",
                    f"host evaluator {ref!r} raised {cause[:_MAX_CAUSE_CHARS]}",
                    location=ref,
                    cause=type(exc).__name__,
                )
            ) from exc
        # An invalid return type (None, a bare mapping, …) would otherwise raise a TypeError deep
        # in the core (``replace`` on a non-dataclass) — outside this boundary and uncaught — so
        # validate it here as a distinct typed setup error rather than a raw exit-1 traceback.
        if not isinstance(result, (Score, ScoreBatch)):
            raise SetupError(
                setup_diagnostic(
                    "evaluator_bad_return",
                    f"host evaluator {ref!r} returned {type(result).__name__}, "
                    "expected a Score or ScoreBatch",
                    location=ref,
                )
            )
        return result

    return cast("Evaluator", isolated)


def _guard_evaluator(evaluator: Evaluator) -> Evaluator:
    """Wrap an evaluator so the run-level route-error example scores as ``error`` for it."""

    def guarded(
        example: Example, context: EvaluatorContext, evidence: EvidenceBundle
    ) -> Score | ScoreBatch:
        if example.example_id == _ROUTE_ERROR_ID:
            return Score(
                metric=context.spec.name,
                value=None,
                status=ScoreStatus.ERROR,
                validity=Validity.NOT_MEASURED,
                evaluator_version="route-guard@1",
                diagnostics=[
                    Diagnostic(
                        code="route_incomplete",
                        severity=Severity.ERROR,
                        message="run had unreadable input records; an active gate cannot pass "
                        "over incomplete evidence",
                    )
                ],
            )
        return evaluator(example, context, evidence)

    return cast("Evaluator", guarded)


def _trace_source(config: TraceConfig, root: Path) -> TraceSource:
    if config.fmt is TraceFormat.LOCAL:
        return LocalJsonlTraceSource(config, root)
    return OpenConventionTraceSource(config, root)


def _check_dataset_ref(config: RuntimeConfig, metric: MetricConfig) -> None:
    if metric.dataset is not None and not any(d.name == metric.dataset for d in config.datasets):
        raise SetupError(
            setup_diagnostic(
                "dataset_ref_unknown",
                f"metric {metric.spec.name!r} references unknown dataset {metric.dataset!r}",
            )
        )


def _worst_status(
    dataset_statuses: list[DatasetStatus], *, has_proposed_trace: bool
) -> DatasetStatus:
    """The least trustworthy dataset status over a source set (traces carry no validated gold)."""
    statuses = list(dataset_statuses)
    if has_proposed_trace:
        statuses.append(DatasetStatus.PROPOSED)
    if any(s is DatasetStatus.RETIRED for s in statuses):
        return DatasetStatus.RETIRED
    if not statuses or any(s is DatasetStatus.PROPOSED for s in statuses):
        return DatasetStatus.PROPOSED
    return DatasetStatus.VALIDATED


def _worst_policy(policies: list[DataPolicy]) -> DataPolicy:
    """The most restrictive data policy over a source set (fail-closed to ``unknown`` if empty)."""
    return max(policies, key=lambda p: _POLICY_SEVERITY[p], default=DataPolicy.UNKNOWN)


def _run_authority(
    config: RuntimeConfig, lane_trace_policies: list[DataPolicy]
) -> tuple[DatasetStatus, DataPolicy]:
    """The worst-case dataset status + data policy across every configured source (legacy default).

    This run-global worst is the conservative fallback for an **unbound** metric (one with no
    explicit source bindings, D1): its authority must reflect the least trustworthy source in the
    run — not one bound dataset (build contract §2 #9). A configured TRACE_SOURCE lane is a source
    too: it carries no validated gold, so it dilutes the status to ``proposed`` and its data policy
    joins the worst-policy comparison (EG-H0-5), exactly like a built-in ``traces:`` entry — a lane
    cannot launder a gate to ``pass``. A **bound** metric instead resolves authority over only the
    sources it consumes (D2, :func:`_metric_authority_inputs`).
    """
    status = _worst_status(
        [d.status for d in config.datasets],
        has_proposed_trace=bool(config.traces or lane_trace_policies),
    )
    policy = _worst_policy(
        [d.data_policy for d in config.datasets]
        + [t.data_policy for t in config.traces]
        + lane_trace_policies
    )
    return status, policy


def _metric_authority_inputs(
    metric: MetricConfig, config: RuntimeConfig, lane_trace_policies: list[DataPolicy]
) -> AuthorityInputs:
    """Resolve a metric's authority inputs over the evidence it actually consumes (D2).

    A **bound** metric (D1 ``sources``) resolves dataset status + data policy over *only* its bound
    sources across every role, so an unrelated proposed/forbidden source in the same run cannot
    dilute it, and a proposed/forbidden source it does consume constrains it. Because bindings are
    declared (not selector-dependent), a selector that excludes ordinary examples cannot hide a
    consumed source from authority. An **unbound** metric keeps the conservative run-global worst
    (:func:`_run_authority`). Judge capability/calibration, threshold approval, and baseline needs
    stay on the metric itself, so they are carried unchanged into the per-source inputs.
    """
    names = {b.name for b in metric.sources}
    if not names:
        status, policy = _run_authority(config, lane_trace_policies)
        return metric.authority_inputs(dataset_status=status, data_policy=policy)
    bound_datasets = [d for d in config.datasets if d.name in names]
    bound_traces = [t for t in config.traces if t.name in names]
    status = _worst_status(
        [d.status for d in bound_datasets], has_proposed_trace=bool(bound_traces)
    )
    policy = _worst_policy(
        [d.data_policy for d in bound_datasets] + [t.data_policy for t in bound_traces]
    )
    return metric.authority_inputs(dataset_status=status, data_policy=policy)


def _apply_calibration(
    metric: MetricConfig, root: Path, *, judge_capability: JudgeCapability | None = None
) -> MetricConfig:
    """Resolve a judge metric's authority from its host-owned calibration file (EG-M4-3).

    A complete, host-owned ``CalibrationRecord`` + ``ApprovedThreshold`` is the *only* way a
    judge metric becomes gating. Without a calibration file a judge metric is forced to
    ``UNCALIBRATED`` + ``PROPOSED`` — the yaml cannot self-declare ``calibrated``/``approved``
    to bypass the host-owned approval. An incomplete record is a setup error, never a silent
    gate; the harness derives the authority inputs and never fabricates an approver.

    EG-NR-1: for a judge metric the selected adapter's ``judge_capability`` is stamped on the
    returned config so authority resolution can refuse a synthetic test double *before* calibration
    — no calibration file or approved threshold can turn a fake judge into a gating one.
    """
    is_judge = "judge" in metric.spec.required_evidence
    capability = judge_capability if is_judge else None
    if metric.calibration is None:
        if is_judge:
            return replace(
                metric,
                judge_calibration=JudgeCalibration.UNCALIBRATED,
                threshold_approval=ThresholdApproval.PROPOSED,
                judge_capability=capability,
            )
        return metric
    calibration_file = load_calibration(metric.calibration, root)
    try:
        outcome = derive_calibration(
            calibration_file, metric.spec.score_range, metric.spec.direction
        )
    except ContractError as exc:
        raise SetupError(
            setup_diagnostic("calibration_invalid", f"calibration for {metric.spec.name!r}: {exc}")
        ) from exc
    return replace(
        metric,
        judge_calibration=outcome.judge_calibration,
        threshold_approval=outcome.threshold_approval,
        threshold=outcome.threshold,
        judge_capability=capability,
    )


def _load_rubrics(config: RuntimeConfig, root: Path) -> dict[str, RubricRef]:
    """Load each judge metric's host-owned rubric (fail-closed) for refs + provenance."""
    return {
        metric.spec.name: load_rubric(metric.rubric, root)
        for metric in config.metrics
        if metric.rubric is not None
    }


def _dimensions(
    config: RuntimeConfig,
    examples: list[Example],
    rubrics: Mapping[str, RubricRef],
    metrics: Sequence[MetricConfig],
) -> dict[str, Any]:
    policies = (
        {d.data_policy.value for d in config.datasets}
        | {t.data_policy.value for t in config.traces}
        # An enabled lane is a configured source: its policy joins the gating policy set so a
        # comparison breaks when a lane changes the run's evidence/egress surface.
        | {lc.data_policy.value for lc in config.lanes if lc.enabled}
    )
    return {
        "framework": _FRAMEWORK,
        "metric_spec": [m.spec.to_dict() for m in metrics],
        "evaluator": [m.spec.evaluator_ref for m in metrics],
        "dataset": [
            {"name": d.name, "version": d.version, "status": d.status.value}
            for d in config.datasets
        ],
        "example": [e.example_id for e in examples],
        "evidence": {"example_count": len(examples)},
        "config": _config_dimension(config, rubrics),
        "policy": sorted(policies),
        # Include the gating-relevant MetricConfig fields (not on MetricSpec) so a run whose
        # threshold/approval/params/baseline-need changed gets a distinct fingerprint.
        "authority": {m.spec.name: _authority_dimension(m) for m in metrics},
        "baseline": config.baseline_path,
    }


def _authority_dimension(metric: MetricConfig) -> dict[str, Any]:
    """The per-metric gating provenance. ``applies_to`` is added **only when a selector is set**,
    so a config with no selectors keeps the exact pre-K2 fingerprint (existing baselines stay
    comparable across the upgrade); once a selector is configured, changing it breaks comparability
    — the metric scores a different population (ADR 0049)."""
    dim: dict[str, Any] = {
        "metric_status": metric.metric_status.value,
        "threshold": metric.threshold,
        "threshold_approval": metric.threshold_approval.value,
        "judge_calibration": (
            metric.judge_calibration.value if metric.judge_calibration is not None else None
        ),
        "requires_baseline": metric.requires_baseline,
        "params": metric.params,
    }
    if metric.selector is not None:
        dim["applies_to"] = metric.selector.to_dict()
    # EG-NR-1: record the judge capability only when set, so runs with no judge metric keep their
    # exact pre-existing fingerprint (existing baselines stay comparable). Swapping the judge
    # adapter (fake <-> a real measurement judge) changes the evidence source and breaks
    # comparability — which is correct.
    if metric.judge_capability is not None:
        dim["judge_capability"] = metric.judge_capability.value
    # D1: explicit source bindings are score-determining — a metric bound to a different candidate
    # or reference source consumes different evidence. Added only when bindings are declared, so an
    # unbound metric keeps its exact pre-D1 fingerprint (existing baselines stay comparable).
    if metric.sources:
        dim["sources"] = [b.to_dict() for b in metric.sources]
    return dim


def _config_dimension(config: RuntimeConfig, rubrics: Mapping[str, RubricRef]) -> dict[str, Any]:
    """The gating ``config`` provenance dimension.

    ``lanes`` is added **only when lanes are configured**, so a run with no ``lanes:`` block keeps
    the exact pre-seam fingerprint (existing baselines stay comparable across the upgrade); once a
    lane is configured, adding/toggling/retargeting it breaks comparability — the evidence changed.
    """
    dimension: dict[str, Any] = {
        "run_id": config.run_id,
        "output_dir": config.output_dir,
        # A judge-adapter setting changes the collected evidence and thus the scores, so it must
        # enter the gating provenance — a judge-config change breaks comparability. The typed
        # projection carries the judge's score-determining identity but never its credential.
        "judge": (config.judge.provenance() if config.judge is not None else None),
        # Rubric refs + content fingerprint are score-determining host truth, so they enter the
        # gating provenance — a rubric change (version OR content) breaks comparability.
        "rubrics": {name: ref.provenance() for name, ref in rubrics.items()},
    }
    if config.lanes:
        dimension["lanes"] = [
            {
                "name": lc.name,
                "enabled": lc.enabled,
                "data_policy": lc.data_policy.value,
                "options": lc.options,
            }
            for lc in config.lanes
        ]
    return dimension
