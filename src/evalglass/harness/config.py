"""Typed runtime configuration parsed at the harness boundary (EG-M1-1).

``evalglass.yaml`` is host-owned truth. This module turns its loaded mapping into
typed config dataclasses, failing closed on anything malformed (M0 lesson: parsing
is the #1 bug class) and — critically — applying **authority-safe defaults**: a
metric with no authority fields declared stays ``informational`` with a ``proposed``
threshold, so it cannot gate (CLAUDE.md §11; build contract §2 #9). Granting gating
authority is always an explicit, host-supplied act.

This module performs no I/O; :mod:`evalglass.harness.loader` owns the file read and
``yaml.safe_load``. It reuses the Evaluation Core's fail-closed parse helpers and
its ``MetricSpec`` validation rather than re-implementing them.
"""

from __future__ import annotations

import enum
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core import (
    AuthorityInputs,
    ContractError,
    DataPolicy,
    DatasetStatus,
    ExampleSelector,
    JudgeCalibration,
    MetricSpec,
    MetricStatus,
    ThresholdApproval,
    UnitKind,
)
from evalglass.core._validation import (
    _as_mapping,
    _coerce_enum,
    _opt_int,
    _opt_list,
    _opt_mapping,
    _opt_str,
    _require_str,
)
from evalglass.core.authority import JudgeCapability
from evalglass.core.decision import DecisionPolicy, DecisionStatistic
from evalglass.core.registry import Direction
from evalglass.harness.judge_execution import JudgeExecutionPolicy
from evalglass.harness.lanes import built_in_lanes

_DECISION_POLICY_KEYS = frozenset(
    {"decision_statistic", "min_n_effective", "max_missing_fraction", "interval_level"}
)


def _parse_rubric(raw: Any, ctx: str) -> RubricConfig | None:
    """Parse a metric's ``rubric``. K5 ergonomics: a bare path string means ``{path: <str>}``."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = {"path": raw}
    return RubricConfig.from_mapping(raw, f"{ctx}.rubric")


def _parse_selector(raw: Any, ctx: str) -> ExampleSelector | None:
    """Build a host-owned ExampleSelector from an optional ``applies_to`` block (EG-V02-4 / K2).

    ``applies_to`` is a mapping of ``metadata_key -> value | [values]``; the metric then scores
    only examples whose metadata holds every key with an allowed value. The keys/values are the
    host's own (e.g. a per-workflow tag their traces carry) — EvalGlass assumes none. Fail-closed:
    a non-mapping, an empty mapping, or a non-scalar value is a setup error, not a silent no-op.
    """
    if raw is None:
        return None
    m = _as_mapping(raw, f"{ctx}.applies_to")
    if not m:
        raise ContractError(f"{ctx}.applies_to: must declare at least one metadata constraint")
    constraints: dict[str, tuple[Any, ...]] = {}
    for key, value in m.items():
        if not isinstance(key, str) or not key:
            raise ContractError(f"{ctx}.applies_to: each key must be a non-empty string")
        values = value if isinstance(value, list) else [value]
        if not values or any(isinstance(v, (list, dict)) for v in values):
            raise ContractError(
                f"{ctx}.applies_to[{key!r}]: value must be a scalar or a non-empty list of scalars"
            )
        constraints[key] = tuple(values)
    return ExampleSelector(constraints=constraints)


def _parse_source_bindings(raw: Any, ctx: str) -> list[SourceBinding]:
    """Parse a metric's optional ``sources`` list into typed bindings (fail-closed) (D1).

    Absent -> an unbound legacy metric (empty list). Cross-source resolution (name known/ambiguous,
    at-least-one-candidate, ``dataset`` conflict) happens once in ``RuntimeConfig`` where every
    source name is visible; here we only validate each binding's own shape.
    """
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise ContractError(f"{ctx}.sources: must be a non-empty list of source bindings")
    return [SourceBinding.from_mapping(b, f"{ctx}.sources[{i}]") for i, b in enumerate(raw)]


def _parse_decision_policy(
    raw: Any, threshold: float | None, direction: Direction, ctx: str
) -> DecisionPolicy | None:
    """Build a host-owned DecisionPolicy from an optional ``decision_policy`` block (M7 T2).

    The policy reuses the metric's approved ``threshold`` and declared ``direction`` — it
    only carries the *decision rule* (which statistic, min effective n, max missing, level).
    A block without a threshold is a setup error: a decision needs something to clear.
    """
    if raw is None:
        return None
    m = _as_mapping(raw, f"{ctx}.decision_policy")
    unknown = sorted(set(m) - _DECISION_POLICY_KEYS)
    if unknown:
        raise ContractError(f"{ctx}.decision_policy: unknown key(s): {', '.join(unknown)}")
    if threshold is None:
        raise ContractError(f"{ctx}.decision_policy: a decision policy requires a threshold")
    stat_raw = m.get("decision_statistic")
    statistic = (
        _coerce_enum(DecisionStatistic, stat_raw, "decision_statistic", f"{ctx}.decision_policy")
        if stat_raw is not None
        else None
    )
    kwargs: dict[str, Any] = {}
    if "min_n_effective" in m:
        value = m["min_n_effective"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContractError(f"{ctx}.decision_policy: 'min_n_effective' must be an int")
        kwargs["min_n_effective"] = value
    if "max_missing_fraction" in m:
        kwargs["max_missing_fraction"] = _opt_finite_float(
            m, "max_missing_fraction", f"{ctx}.decision_policy"
        )
    if "interval_level" in m:
        kwargs["interval_level"] = _opt_finite_float(m, "interval_level", f"{ctx}.decision_policy")
    return DecisionPolicy(
        threshold=threshold, direction=direction, decision_statistic=statistic, **kwargs
    )


class TraceFormat(enum.StrEnum):
    """How a trace JSONL file is shaped. Adapters for each land in later M1 slices."""

    LOCAL = "local"
    OPENTELEMETRY = "opentelemetry"
    OPENINFERENCE = "openinference"


def _opt_finite_float(m: Mapping[str, Any], key: str, ctx: str) -> float | None:
    value = m.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ContractError(f"{ctx}: '{key}' must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ContractError(f"{ctx}: '{key}' must be finite, got {value!r}")
    return float(value)


def _opt_bool(m: Mapping[str, Any], key: str, ctx: str, *, default: bool) -> bool:
    value = m.get(key, default)
    if not isinstance(value, bool):
        raise ContractError(f"{ctx}: '{key}' must be a boolean, got {value!r}")
    return value


@dataclass(frozen=True)
class DatasetConfig:
    """A host-owned dataset declaration. Status defaults to the conservative ``proposed``."""

    path: str
    name: str
    status: DatasetStatus = DatasetStatus.PROPOSED
    version: str = "0"
    data_policy: DataPolicy = DataPolicy.UNKNOWN

    @classmethod
    def from_mapping(cls, data: Any, idx: int) -> Self:
        ctx = f"datasets[{idx}]"
        m = _as_mapping(data, ctx)
        path = _require_str(m, "path", ctx)
        return cls(
            path=path,
            name=_opt_str(m, "name", ctx) or path,
            status=_coerce_enum(DatasetStatus, m.get("status", "proposed"), "status", ctx),
            version=_opt_str(m, "version", ctx) or "0",
            data_policy=_coerce_enum(
                DataPolicy, m.get("data_policy", "unknown"), "data_policy", ctx
            ),
        )


@dataclass(frozen=True)
class TraceConfig:
    """A host-owned trace declaration. ``fmt`` selects the M1 TraceSource adapter.

    ``kind`` (YAML key ``unit``) selects the behavior slice the route grades (EG-P1, ADR 0045):
    the default ``CALL`` scores one LLM call per unit (every pre-P1 config is unchanged), while
    ``trajectory``/``session`` group a trace's call-level units into one aggregate before scoring.
    """

    path: str
    name: str
    fmt: TraceFormat = TraceFormat.LOCAL
    data_policy: DataPolicy = DataPolicy.UNKNOWN
    kind: UnitKind = UnitKind.CALL

    @classmethod
    def from_mapping(cls, data: Any, idx: int) -> Self:
        ctx = f"traces[{idx}]"
        m = _as_mapping(data, ctx)
        path = _require_str(m, "path", ctx)
        return cls(
            path=path,
            name=_opt_str(m, "name", ctx) or path,
            fmt=_coerce_enum(TraceFormat, m.get("format", "local"), "format", ctx),
            data_policy=_coerce_enum(
                DataPolicy, m.get("data_policy", "unknown"), "data_policy", ctx
            ),
            # Absent ``unit:`` ⇒ CALL (byte-identical to pre-P1); a present-but-bogus value
            # fails closed via _coerce_enum, exactly like ``format``/``data_policy``.
            kind=_coerce_enum(UnitKind, m.get("unit", "call"), "unit", ctx),
        )


@dataclass(frozen=True)
class TaskConfig:
    """Host replay command (EG-M2-1a): a host-declared ``argv`` (no shell) plus a timeout.

    Opt-in — when absent, no replay runs. Parsing fails closed: a missing/empty/non-list
    ``argv`` or a non-positive/non-finite ``timeout_s`` is a setup error, never a silently
    ignored or shell-interpreted command.
    """

    argv: list[str]
    timeout_s: float = 30.0

    @classmethod
    def from_mapping(cls, data: Any, ctx: str = "task") -> Self:
        m = _as_mapping(data, ctx)
        argv_raw = m.get("argv")
        if not isinstance(argv_raw, list) or not argv_raw:
            raise ContractError(f"{ctx}: 'argv' must be a non-empty list of strings")
        if not all(isinstance(a, str) and a for a in argv_raw):
            raise ContractError(f"{ctx}: every 'argv' item must be a non-empty string")
        timeout = m.get("timeout_s", 30.0)
        if isinstance(timeout, bool) or not isinstance(timeout, int | float):
            raise ContractError(f"{ctx}: 'timeout_s' must be a number, got {timeout!r}")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ContractError(f"{ctx}: 'timeout_s' must be finite and positive, got {timeout!r}")
        return cls(argv=[str(a) for a in argv_raw], timeout_s=float(timeout))


# An environment-variable *name* (not a secret value). The credential reference in config must
# match this so a pasted key is refused at the config boundary and never persisted.
_ENV_VAR_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
# Header names that conventionally carry a secret — these must flow through ``credential_env``,
# never a raw value in host config.
_SECRET_HEADER_NAMES = frozenset(
    {"authorization", "x-api-key", "api-key", "cookie", "proxy-authorization", "x-goog-api-key"}
)
_RESPONSE_FORMATS = frozenset({"json_object", "text"})
_OPENAI_JUDGE_KEYS = frozenset(
    {
        "adapter",
        "endpoint",
        "model",
        "credential_env",
        "timeout_seconds",
        "max_input_chars",
        "max_output_tokens",
        "response_format",
        "allow_insecure_loopback",
        "headers",
        "retain_raw_response",
        "execution",
    }
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback_endpoint(endpoint: str) -> bool:
    """True when ``endpoint``'s host is a loopback address (127.0.0.1 / localhost / ::1).

    A pure-string parse (no ``urllib``) so this required-tier module imports no network client.
    """
    authority = endpoint.split("://", 1)[-1].split("/", 1)[0].rsplit("@", 1)[-1]
    if authority.startswith("["):  # IPv6 literal, e.g. [::1]:8000
        host = authority[1:].split("]", 1)[0]
    else:
        host = authority.split(":", 1)[0]
    return host in _LOOPBACK_HOSTS


def _opt_positive_int(m: Mapping[str, Any], key: str, ctx: str, *, default: int) -> int:
    value = _opt_int(m, key, ctx)
    if value is None:
        return default
    if value <= 0:
        raise ContractError(f"{ctx}: '{key}' must be a positive integer, got {value!r}")
    return value


def _parse_judge_headers(m: Mapping[str, Any], ctx: str) -> tuple[tuple[str, str], ...]:
    """Parse the optional non-secret ``headers`` allowlist; refuse any secret-bearing header."""
    raw = _opt_mapping(m, "headers", ctx)
    pairs: list[tuple[str, str]] = []
    for name, value in raw.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ContractError(f"{ctx}: 'headers' must map string names to string values")
        if name.lower() in _SECRET_HEADER_NAMES:
            raise ContractError(
                f"{ctx}: header {name!r} can carry a secret; supply credentials via "
                "'credential_env' (an environment-variable name), not a header value"
            )
        pairs.append((name, value))
    return tuple(pairs)


@dataclass(frozen=True)
class JudgeConfig:
    """Host-owned judge adapter declaration (EG-M4-1b; ADR 0042, ADR 0052).

    Three adapters: ``fake`` (the required tier's deterministic, no-network default —
    ``default_value`` is its fallback when a fixture gives no directive); ``command`` — a host
    **command judge** subprocess (``command`` argv, ``timeout_seconds``) that scores over JSON
    in/out; and ``openai_compatible`` — a real OpenAI-compatible ``/chat/completions`` judge
    configured directly (``endpoint``/``model``/``credential_env`` + bounded decoding), so a host
    needs no provider subprocess wrapper. Every adapter is opt-in and stays uncalibrated →
    informational until a host computes an agreement study; the credential is an env-var *name*,
    never a secret in config.
    """

    adapter: str = "fake"
    default_value: float | None = None
    command: tuple[str, ...] = ()
    timeout_seconds: float = 120.0
    # OpenAI-compatible measurement route (C1). ``credential_env`` is an env-var NAME; the secret is
    # resolved only at effect time and never enters config, provenance, plan, or any artifact.
    endpoint: str | None = None
    model: str | None = None
    credential_env: str | None = None
    max_input_chars: int = 6000
    max_output_tokens: int = 400
    response_format: str = "json_object"
    allow_insecure_loopback: bool = False
    headers: tuple[tuple[str, str], ...] = ()
    #: Persist the raw provider response text in the run's evidence records (C4; ADR 0054). The
    #: conservative default is False — parsed evidence and its fingerprint are portable, but the raw
    #: text (possible sensitive provider content) is retained only when the host opts in.
    retain_raw_response: bool = False
    #: Judge execution controls (C3; ADR 0055): deterministic cache, budgets, and bounded retry.
    #: Absent -> the default policy (no cache/budget/retry), byte-identical to a pre-C3 run.
    execution: JudgeExecutionPolicy | None = None

    @classmethod
    def from_mapping(cls, data: Any, ctx: str = "judge") -> Self:
        m = _as_mapping(data, ctx)
        adapter = _opt_str(m, "adapter", ctx) or "fake"
        retain_raw = _opt_bool(m, "retain_raw_response", ctx, default=False)
        execution = (
            JudgeExecutionPolicy.from_mapping(m["execution"], f"{ctx}.execution")
            if m.get("execution") is not None
            else None
        )
        if adapter == "fake":
            return cls(
                adapter="fake",
                default_value=_opt_finite_float(m, "default_value", ctx),
                retain_raw_response=retain_raw,
                execution=execution,
            )
        if adapter == "command":
            command = m.get("command")
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(c, str) and c.strip() for c in command)
            ):
                raise ContractError(
                    f"{ctx}: judge adapter 'command' requires a non-empty list of string argv"
                )
            timeout = _opt_finite_float(m, "timeout_seconds", ctx)
            return cls(
                adapter="command",
                command=tuple(command),
                timeout_seconds=timeout if timeout is not None else 120.0,
                retain_raw_response=retain_raw,
                execution=execution,
            )
        if adapter == "openai_compatible":
            return cls._openai_from_mapping(m, ctx, retain_raw=retain_raw, execution=execution)
        raise ContractError(
            f"{ctx}: unknown judge adapter {adapter!r}; use 'fake', 'command', or "
            "'openai_compatible'"
        )

    @classmethod
    def _openai_from_mapping(
        cls, m: Mapping[str, Any], ctx: str, *, retain_raw: bool, execution: Any
    ) -> Self:
        unknown = sorted(set(m) - _OPENAI_JUDGE_KEYS)
        if unknown:
            raise ContractError(f"{ctx}: unknown key(s) for adapter 'openai_compatible': {unknown}")
        allow_loopback = _opt_bool(m, "allow_insecure_loopback", ctx, default=False)
        endpoint = _require_str(m, "endpoint", ctx)
        scheme = endpoint.split("://", 1)[0].lower() if "://" in endpoint else ""
        plaintext_loopback_ok = (
            allow_loopback and scheme == "http" and _is_loopback_endpoint(endpoint)
        )
        if scheme != "https" and not plaintext_loopback_ok:
            raise ContractError(
                f"{ctx}: judge endpoint must be TLS (got {endpoint!r}); plaintext is permitted "
                "only for a loopback host under 'allow_insecure_loopback'"
            )
        model = _require_str(m, "model", ctx)
        credential_env = _opt_str(m, "credential_env", ctx)
        if credential_env is not None and not _ENV_VAR_NAME_RE.match(credential_env):
            raise ContractError(
                f"{ctx}: 'credential_env' must be an environment-variable NAME (e.g. "
                "'OPENAI_API_KEY'), not a secret value"
            )
        response_format = _opt_str(m, "response_format", ctx) or "json_object"
        if response_format not in _RESPONSE_FORMATS:
            raise ContractError(
                f"{ctx}: 'response_format' must be one of {sorted(_RESPONSE_FORMATS)}, "
                f"got {response_format!r}"
            )
        timeout = _opt_finite_float(m, "timeout_seconds", ctx)
        return cls(
            adapter="openai_compatible",
            endpoint=endpoint,
            model=model,
            credential_env=credential_env,
            timeout_seconds=timeout if timeout is not None else 120.0,
            max_input_chars=_opt_positive_int(m, "max_input_chars", ctx, default=6000),
            max_output_tokens=_opt_positive_int(m, "max_output_tokens", ctx, default=400),
            response_format=response_format,
            allow_insecure_loopback=allow_loopback,
            headers=_parse_judge_headers(m, ctx),
            retain_raw_response=retain_raw,
            execution=execution,
        )

    def provenance(self) -> dict[str, Any]:
        """The score-determining judge identity for gating provenance — never the secret.

        ``fake``/``command`` keep their exact pre-C1 shape (existing baselines stay comparable);
        ``openai_compatible`` records endpoint/model/decoding identity so a model or endpoint swap
        breaks comparability, but the credential reference and any header never enter provenance.
        """
        if self.adapter == "openai_compatible":
            return {
                "adapter": "openai_compatible",
                "endpoint": self.endpoint,
                "model": self.model,
                "response_format": self.response_format,
                "max_output_tokens": self.max_output_tokens,
            }
        return {"adapter": self.adapter, "default_value": self.default_value}


@dataclass(frozen=True)
class RubricConfig:
    """A judge metric's host-owned rubric reference (EG-M4-2).

    ``path`` points at a markdown rubric under ``evals/rubrics/`` (loaded + fingerprinted by
    :mod:`evalglass.harness.rubric`). The version + prompt/model/parser refs enter the run's
    gating provenance, so any change breaks baseline comparability.
    """

    path: str
    version: str = "1"
    prompt_ref: str | None = None
    model_ref: str | None = None
    parser_version: str | None = None

    @classmethod
    def from_mapping(cls, data: Any, ctx: str = "rubric") -> Self:
        m = _as_mapping(data, ctx)
        return cls(
            path=_require_str(m, "path", ctx),
            version=_opt_str(m, "version", ctx) or "1",
            prompt_ref=_opt_str(m, "prompt_ref", ctx),
            model_ref=_opt_str(m, "model_ref", ctx),
            parser_version=_opt_str(m, "parser_version", ctx),
        )


class SourceRole(enum.StrEnum):
    """The role a bound source plays for a metric's construct (Epic D / D1).

    Domain-neutral and authority-free: a role only says *how* a metric consumes a source, never
    that the source is validated or that the metric may gate. ``candidate`` supplies the subjects a
    metric scores; ``reference`` supplies gold/silver for a reference-lens comparison; ``context``
    and ``observation`` supply supporting/assembled evidence a construct reads.
    """

    CANDIDATE = "candidate"
    REFERENCE = "reference"
    CONTEXT = "context"
    OBSERVATION = "observation"


@dataclass(frozen=True)
class SourceBinding:
    """One metric-to-source binding: which named source plays which role (Epic D / D1)."""

    name: str
    role: SourceRole

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role.value}

    @classmethod
    def from_mapping(cls, data: Any, ctx: str) -> Self:
        m = _as_mapping(data, ctx)
        return cls(
            name=_require_str(m, "name", ctx),
            role=_coerce_enum(SourceRole, _require_present(m, "role", ctx), "role", ctx),
        )


@dataclass(frozen=True)
class MetricAttentionRule:
    """A host-declared presentation attention rule, distinct from an approved gate (Epic E / E1).

    Purely a display hint: it flags a metric for the dashboard's attention queue when its value
    crosses a host-chosen band, and it can **never** change scoring, authority, the verdict, or CI
    exit. A gate is an approved decision rule resolved by the Verdict Engine; this is only "surface
    this to a reader." Both bounds are optional; ``note`` is an optional human reason.
    """

    below: float | None = None
    above: float | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.below is not None:
            out["below"] = self.below
        if self.above is not None:
            out["above"] = self.above
        if self.note is not None:
            out["note"] = self.note
        return out

    @classmethod
    def from_mapping(cls, data: Any, ctx: str) -> Self:
        m = _as_mapping(data, ctx)
        return cls(
            below=_opt_finite_float(m, "below", ctx),
            above=_opt_finite_float(m, "above", ctx),
            note=_opt_str(m, "note", ctx),
        )


@dataclass(frozen=True)
class MetricDisplay:
    """Host-owned, score-neutral presentation metadata for one metric (Epic E / E1).

    Every field here is display only: a label, the workflow/group it belongs to, its tier, a
    construct description, ordering, host links, and an optional attention rule. None of it grants
    authority, changes a score, or feeds a gating fingerprint — the renderer copies these facts so
    it never has to infer workflow/tier/label from a metric name or an authority reason. Every field
    is optional; the projection supplies deterministic neutral fallbacks when absent.
    """

    label: str | None = None
    workflow: str | None = None
    tier: str | None = None
    description: str | None = None
    order: int | None = None
    docs_url: str | None = None
    owner: str | None = None
    source_url: str | None = None
    attention: MetricAttentionRule | None = None

    @classmethod
    def from_mapping(cls, data: Any, ctx: str) -> Self:
        m = _as_mapping(data, ctx)
        order_raw = m.get("order")
        if order_raw is not None and (
            isinstance(order_raw, bool) or not isinstance(order_raw, int)
        ):
            raise ContractError(f"{ctx}.order: must be an integer")
        attention = m.get("attention")
        return cls(
            label=_opt_str(m, "label", ctx),
            workflow=_opt_str(m, "workflow", ctx),
            tier=_opt_str(m, "tier", ctx),
            description=_opt_str(m, "description", ctx),
            order=order_raw,
            docs_url=_opt_str(m, "docs_url", ctx),
            owner=_opt_str(m, "owner", ctx),
            source_url=_opt_str(m, "source_url", ctx),
            attention=(
                MetricAttentionRule.from_mapping(attention, f"{ctx}.attention")
                if attention is not None
                else None
            ),
        )


@dataclass(frozen=True)
class MetricConfig:
    """A declared metric: its validated ``MetricSpec`` plus authority + threshold inputs.

    Authority defaults are deliberately conservative — ``informational`` status and a
    ``proposed`` threshold — so an under-specified metric is informational, never a gate.
    """

    spec: MetricSpec
    threshold: float | None = None
    metric_status: MetricStatus = MetricStatus.INFORMATIONAL
    threshold_approval: ThresholdApproval = ThresholdApproval.PROPOSED
    judge_calibration: JudgeCalibration | None = None
    # Additive (EG-NR-1): the capability of the selected judge adapter, set by the harness for a
    # judge metric (never from yaml). None = not a judge metric / not asserted (back-compat).
    # A SYNTHETIC_TEST_DOUBLE resolves to informational regardless of calibration/threshold.
    judge_capability: JudgeCapability | None = None
    requires_baseline: bool = False
    dataset: str | None = None
    rubric: RubricConfig | None = None
    calibration: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    # Additive (M7 T2): optional host-owned decision rule. When present, an active gate
    # decides on the confidence bound + adequacy over the Estimate instead of the point.
    decision_policy: DecisionPolicy | None = None
    # Additive (EG-V02-4 / K2): an optional host-owned example selector (``applies_to``). When
    # present the metric scores only examples whose metadata matches; absent -> every example.
    selector: ExampleSelector | None = None
    # Additive (Epic D / D1): explicit source/evidence bindings. When present, a metric's candidate
    # population derives only from its ``candidate``-role sources (plus its selector), and D2
    # resolves authority over the sources it actually consumes. Absent -> unbound legacy metric
    # (all-source population, conservative run-global authority). Roles grant no authority.
    sources: list[SourceBinding] = field(default_factory=list)
    # Additive (Epic E / E1): host-owned, score-neutral presentation metadata for the dashboard.
    # Display only — it never changes a score, authority, fingerprint, or the verdict. Absent -> the
    # projection uses deterministic neutral fallbacks (label = name, a single neutral workflow, tier
    # derived from the typed lens/evaluator).
    display: MetricDisplay | None = None

    def candidate_source_names(self) -> frozenset[str] | None:
        """The candidate-role source names, or ``None`` when the metric is unbound (all sources)."""
        if not self.sources:
            return None
        return frozenset(b.name for b in self.sources if b.role is SourceRole.CANDIDATE)

    def authority_inputs(
        self, *, dataset_status: DatasetStatus, data_policy: DataPolicy
    ) -> AuthorityInputs:
        """The typed authority inputs for this metric, given its bound dataset state."""
        return AuthorityInputs(
            metric_status=self.metric_status,
            dataset_status=dataset_status,
            threshold_approval=self.threshold_approval,
            data_policy=data_policy,
            judge_calibration=self.judge_calibration,
            judge_capability=self.judge_capability,
            requires_baseline=self.requires_baseline,
        )

    @classmethod
    def from_mapping(cls, data: Any, idx: int) -> Self:
        ctx = f"metrics[{idx}]"
        m = _as_mapping(data, ctx)
        # Reuse the Evaluation Core's MetricSpec parser + validation (continuous needs a
        # range, low<high, finite bounds) instead of duplicating it; fill harness defaults.
        # Ergonomics (EG-V02-5 / K5): a metric's *tier* being "judge" is expressed by
        # ``required_evidence: [judge]``, not by ``lens`` (which is reference/non_reference). Accept
        # ``lens: judge`` as sugar for ``non_reference`` so a first author's natural guess loads.
        lens_value = _require_present(m, "lens", ctx)
        if lens_value == "judge":
            lens_value = "non_reference"
        spec_data: dict[str, Any] = {
            "name": _require_str(m, "name", ctx),
            "version": _opt_str(m, "version", ctx) or "1",
            "lens": lens_value,
            "granularity": m.get("granularity", "call"),
            "score_type": _require_present(m, "score_type", ctx),
            "direction": m.get("direction", "higher_is_better"),
            "evaluator_ref": _require_str(m, "evaluator_ref", ctx),
            "aggregation": m.get("aggregation", "mean"),
        }
        # Preserve every declared MetricSpec field — silently dropping required_evidence /
        # prerequisites / profile would let a config's trust constraints vanish. MetricSpec
        # validates each one (and rejects unknowns it does not declare).
        for opt in ("score_range", "emits", "profile", "required_evidence", "prerequisites"):
            if opt in m:
                spec_data[opt] = m[opt]
        spec = MetricSpec.from_dict(spec_data)
        threshold = _opt_finite_float(m, "threshold", ctx)
        # A threshold outside the declared range is a malformed config, not an impossible
        # gate the Verdict Engine should ever evaluate — reject it as a setup error.
        if threshold is not None and spec.score_range is not None:
            low, high = spec.score_range
            if not low <= threshold <= high:
                raise ContractError(
                    f"{ctx}: threshold {threshold} is outside the metric's "
                    f"score_range [{low}, {high}]"
                )
        judge_raw = m.get("judge_calibration")
        judge_calibration = (
            _coerce_enum(JudgeCalibration, judge_raw, "judge_calibration", ctx)
            if judge_raw is not None
            else None
        )
        # A metric that needs judge evidence but declares no calibration is UNCALIBRATED,
        # never None — so it stays informational and cannot gate just because the yaml left
        # calibration unset. A calibrated record that *can* gate arrives in EG-M4-3.
        if judge_calibration is None and "judge" in spec.required_evidence:
            judge_calibration = JudgeCalibration.UNCALIBRATED
        return cls(
            spec=spec,
            threshold=threshold,
            metric_status=_coerce_enum(
                MetricStatus, m.get("metric_status", "informational"), "metric_status", ctx
            ),
            threshold_approval=_coerce_enum(
                ThresholdApproval,
                m.get("threshold_approval", "proposed"),
                "threshold_approval",
                ctx,
            ),
            judge_calibration=judge_calibration,
            requires_baseline=_opt_bool(m, "requires_baseline", ctx, default=False),
            dataset=_opt_str(m, "dataset", ctx),
            rubric=_parse_rubric(m.get("rubric"), ctx),
            calibration=_opt_str(m, "calibration", ctx),
            params=_opt_mapping(m, "params", ctx),
            decision_policy=_parse_decision_policy(
                m.get("decision_policy"), threshold, spec.direction, ctx
            ),
            selector=_parse_selector(m.get("applies_to"), ctx),
            sources=_parse_source_bindings(m.get("sources"), ctx),
            display=(
                MetricDisplay.from_mapping(m["display"], f"{ctx}.display")
                if m.get("display") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class LaneConfig:
    """An opt-in extension-lane selection for a run (EG-H0-2; ADR 0031).

    Conservative by default: a listed lane is **disabled** until the host explicitly
    enables it (so listing one never runs it), and ``name`` must be a real entry in
    ``built_in_lanes()`` — an unknown name or key is a setup error, never a silent
    drop. ``options`` are the lane-specific factory kwargs; the lane validates their
    contents when it runs. A lane carries no authority and cannot change the verdict.
    """

    name: str
    enabled: bool = False
    data_policy: DataPolicy = DataPolicy.UNKNOWN
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Any, idx: int) -> Self:
        ctx = f"lanes[{idx}]"
        m = _as_mapping(data, ctx)
        unknown = sorted(set(m) - {"name", "enabled", "data_policy", "options"})
        if unknown:
            raise ContractError(f"{ctx}: unknown lane config key(s): {', '.join(unknown)}")
        name = _require_str(m, "name", ctx)
        known = built_in_lanes().names()
        if name not in known:
            raise ContractError(f"{ctx}: unknown lane {name!r}; known lanes: {', '.join(known)}")
        return cls(
            name=name,
            enabled=_opt_bool(m, "enabled", ctx, default=False),
            data_policy=_coerce_enum(
                DataPolicy, m.get("data_policy", "unknown"), "data_policy", ctx
            ),
            options=_opt_mapping(m, "options", ctx),
        )


@dataclass(frozen=True)
class DashboardConfig:
    """Run-level, score-neutral dashboard presentation metadata (Epic E / E1).

    Optional labels for the report hero (``application`` / ``source_label``), a stable ``series``
    identity for honest progression, and an optional host-declared ``composite`` — a named,
    weighted, versioned overall score. A composite is the **only** licensed way to show a mean;
    absent, the dashboard shows coverage and never averages unrelated metrics. Presentation only:
    none of this grants authority or changes a verdict.
    """

    application: str | None = None
    source_label: str | None = None
    series: str | None = None
    composite: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, data: Any) -> Self:
        ctx = "config.dashboard"
        m = _as_mapping(data, ctx)
        composite = m.get("composite")
        if composite is not None:
            composite = dict(_as_mapping(composite, f"{ctx}.composite"))
        return cls(
            application=_opt_str(m, "application", ctx),
            source_label=_opt_str(m, "source_label", ctx),
            series=_opt_str(m, "series", ctx),
            composite=composite,
        )


@dataclass(frozen=True)
class RuntimeConfig:
    """The whole validated run configuration the harness builds its run from."""

    run_id: str
    metrics: list[MetricConfig]
    datasets: list[DatasetConfig] = field(default_factory=list)
    traces: list[TraceConfig] = field(default_factory=list)
    task: TaskConfig | None = None
    judge: JudgeConfig | None = None
    baseline_path: str | None = None
    comparison_requested: bool = False
    output_dir: str = "reports"
    lanes: list[LaneConfig] = field(default_factory=list)
    dashboard: DashboardConfig | None = None

    @classmethod
    def from_mapping(cls, data: Any) -> Self:
        m = _as_mapping(data, "config")
        run = _opt_mapping(m, "run", "config")
        metrics_raw = m.get("metrics")
        if not isinstance(metrics_raw, list) or not metrics_raw:
            raise ContractError("config: 'metrics' must be a non-empty list")
        metrics = [MetricConfig.from_mapping(x, i) for i, x in enumerate(metrics_raw)]
        names = [mc.spec.name for mc in metrics]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ContractError(f"config: duplicate metric name(s): {', '.join(dupes)}")
        datasets = [
            DatasetConfig.from_mapping(x, i)
            for i, x in enumerate(_opt_list(m, "datasets", "config"))
        ]
        traces = [
            TraceConfig.from_mapping(x, i) for i, x in enumerate(_opt_list(m, "traces", "config"))
        ]
        _validate_source_bindings(metrics, datasets, traces)
        # A present ``task:`` key (even ``null``/non-mapping) must fail closed as a setup error;
        # only an absent key means "no replay" (TaskConfig.from_mapping rejects non-mappings).
        task = TaskConfig.from_mapping(m["task"]) if "task" in m else None
        judge = JudgeConfig.from_mapping(m["judge"]) if "judge" in m else None
        lanes = [
            LaneConfig.from_mapping(x, i) for i, x in enumerate(_opt_list(m, "lanes", "config"))
        ]
        baseline = _opt_mapping(m, "baseline", "config")
        output = _opt_mapping(m, "output", "config")
        return cls(
            run_id=_opt_str(run, "id", "config.run") or "run",
            metrics=metrics,
            datasets=datasets,
            traces=traces,
            task=task,
            judge=judge,
            baseline_path=_opt_str(baseline, "path", "config.baseline") if baseline else None,
            comparison_requested=(
                _opt_bool(baseline, "comparison_requested", "config.baseline", default=False)
                if baseline
                else False
            ),
            output_dir=_opt_str(output, "dir", "config.output") or "reports",
            lanes=lanes,
            dashboard=(
                DashboardConfig.from_mapping(m["dashboard"])
                if m.get("dashboard") is not None
                else None
            ),
        )


def _validate_source_bindings(
    metrics: list[MetricConfig],
    datasets: list[DatasetConfig],
    traces: list[TraceConfig],
) -> None:
    """Resolve every metric's source bindings against the run's known sources (fail-closed) (D1).

    Each binding name must resolve to exactly one known source; a name that is both a dataset and a
    trace is ambiguous; a duplicate ``(name, role)`` and a metric that binds sources but no
    ``candidate`` role are setup errors; and declaring both ``dataset`` and ``sources`` is ambiguous
    (migrate the dataset into a candidate binding). Roles carry no authority — this only proves the
    declared inputs exist and are executable, per D1 AC1/AC2.
    """
    dataset_names = [d.name for d in datasets]
    trace_names = [t.name for t in traces]
    known = set(dataset_names) | set(trace_names)
    ambiguous = {n for n in dataset_names if n in trace_names}
    for metric in metrics:
        if metric.sources:
            _validate_metric_bindings(metric, known, ambiguous)


def _validate_metric_bindings(metric: MetricConfig, known: set[str], ambiguous: set[str]) -> None:
    """Resolve one bound metric's source bindings (fail-closed) — the per-metric half of D1."""
    name = metric.spec.name
    if metric.dataset is not None:
        raise ContractError(
            f"metric {name!r}: declare either 'dataset' or 'sources', not both "
            "(migrate the dataset into a candidate source binding)"
        )
    seen: set[tuple[str, SourceRole]] = set()
    for binding in metric.sources:
        if binding.name in ambiguous:
            raise ContractError(
                f"metric {name!r}: ambiguous source {binding.name!r} is both a dataset "
                "and a trace; rename one so the binding resolves to exactly one source"
            )
        if binding.name not in known:
            raise ContractError(
                f"metric {name!r}: binds unknown source {binding.name!r}; "
                f"known sources: {', '.join(sorted(known)) or '(none)'}"
            )
        key = (binding.name, binding.role)
        if key in seen:
            raise ContractError(
                f"metric {name!r}: duplicate source binding "
                f"{binding.name!r} as {binding.role.value!r}"
            )
        seen.add(key)
    if not any(b.role is SourceRole.CANDIDATE for b in metric.sources):
        raise ContractError(
            f"metric {name!r}: source bindings must include at least one 'candidate' source "
            "(the population the metric scores)"
        )


def _require_present(m: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in m:
        raise ContractError(f"{ctx}: missing required field '{key}'")
    return m[key]
