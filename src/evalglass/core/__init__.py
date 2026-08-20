"""Evaluation Core — effect-free center of EvalGlass.

This package MUST NOT:
    * read or write files;
    * call the network;
    * call LLMs or import vendor SDKs;
    * read environment variables;
    * use wall-clock time, randomness, or process state directly;
    * execute host code.

The structural enforcement lives in ``tools/check_core_isolation.py`` and
``tests/core_isolation/``. See CLAUDE.md §4.
"""

from __future__ import annotations

from evalglass.core._validation import ContractError
from evalglass.core.aggregation import AggregatedMetric, aggregate
from evalglass.core.authority import (
    AuthorityInputs,
    AuthorityLevel,
    DatasetStatus,
    JudgeCalibration,
    MetricStatus,
    ResolvedAuthority,
    ThresholdApproval,
    resolve_authority,
)
from evalglass.core.clusters import DiagnosticCluster, cluster
from evalglass.core.contracts import (
    DataPolicy,
    Diagnostic,
    EvalUnit,
    EvidenceBundle,
    Example,
    JudgeEvidence,
    JudgeEvidenceStatus,
    Severity,
    TraceEnvelope,
    UnitKind,
)
from evalglass.core.engine import MetricPlan, run_evaluation
from evalglass.core.evaluators import Evaluator, EvaluatorContext
from evalglass.core.population import PopulationSummary
from evalglass.core.provenance import (
    BaselineState,
    ComparableRunFingerprint,
    RunFingerprint,
    fingerprint_dimension,
)
from evalglass.core.registry import (
    Aggregation,
    Direction,
    Lens,
    MetricRegistry,
    MetricSpec,
    ScoreType,
)
from evalglass.core.results import RunRecord, Scorecard
from evalglass.core.scores import Score, ScoreBatch, ScoreStatus, Validity, aggregatable
from evalglass.core.selector import (
    INTEGRITY_METADATA_KEY,
    SOURCE_METADATA_KEY,
    ExampleSelector,
)
from evalglass.core.verdict import GateInput, Verdict, VerdictPayload, decide_verdict

__all__ = [
    "INTEGRITY_METADATA_KEY",
    "SOURCE_METADATA_KEY",
    "AggregatedMetric",
    "Aggregation",
    "AuthorityInputs",
    "AuthorityLevel",
    "BaselineState",
    "ComparableRunFingerprint",
    "ContractError",
    "DataPolicy",
    "DatasetStatus",
    "Diagnostic",
    "DiagnosticCluster",
    "Direction",
    "EvalUnit",
    "Evaluator",
    "EvaluatorContext",
    "EvidenceBundle",
    "Example",
    "ExampleSelector",
    "GateInput",
    "JudgeCalibration",
    "JudgeEvidence",
    "JudgeEvidenceStatus",
    "Lens",
    "MetricPlan",
    "MetricRegistry",
    "MetricSpec",
    "MetricStatus",
    "PopulationSummary",
    "ResolvedAuthority",
    "RunFingerprint",
    "RunRecord",
    "Score",
    "ScoreBatch",
    "ScoreStatus",
    "ScoreType",
    "Scorecard",
    "Severity",
    "ThresholdApproval",
    "TraceEnvelope",
    "UnitKind",
    "Validity",
    "Verdict",
    "VerdictPayload",
    "aggregatable",
    "aggregate",
    "cluster",
    "decide_verdict",
    "fingerprint_dimension",
    "resolve_authority",
    "run_evaluation",
]
