"""Structured, versioned rubric contract + a structured judge-response parser (ADR 0053).

A judge is only as meaningful as its construct and evidence boundary. The scalar markdown rubric
(``rubric.py``) states a construct in prose; a :class:`RubricSpec` makes the same thing *typed and
inspectable*: an explicit construct, ordered anchored criteria, a declared evidence boundary (which
behavior layers the judge may see — the dossier), refusal conditions, and a structured response
schema (score, rationale, per-criterion facet values, violations, cited evidence refs, refusal).

Everything here is **host-owned truth** loaded at the harness boundary — it grants no authority. A
new rubric is ``proposed`` until a host reviews it; calibration stays a separate, later act. The
spec's content digest enters judge provenance, so a rubric/prompt/parser/schema change breaks
baseline comparability. The parser validates a judge's JSON against the declared schema: it rejects
undeclared facets, resolves cited evidence refs against the bounded dossier, and distinguishes a
valid score from a refusal, missing evidence, or a parser error — never a fabricated low score.

The framework ships no construct or domain content; both come from the host.
"""

from __future__ import annotations

import enum
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core._validation import (
    ContractError,
    _as_mapping,
    _coerce_enum,
    _opt_list,
    _opt_str,
    _require_str,
)

#: Versioned schema tag for a structured rubric artifact.
RUBRIC_SCHEMA = "evalglass.rubric/1"


def _opt_bool(m: Any, key: str, ctx: str, *, default: bool) -> bool:
    value = m.get(key, default)
    if not isinstance(value, bool):
        raise ContractError(f"{ctx}: '{key}' must be a boolean, got {value!r}")
    return value


class RubricStatus(enum.StrEnum):
    """A rubric's review lifecycle. It never grants authority; calibration is separate."""

    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    RETIRED = "retired"


class CriterionType(enum.StrEnum):
    """The output shape a criterion facet takes in the judge response."""

    SCORE = "score"  # a float in [0, 1]
    BOOLEAN = "boolean"  # true/false
    LABEL = "label"  # one of a declared set of labels


@dataclass(frozen=True)
class RubricCriterion:
    """One scoring criterion (facet): a name plus an anchor or an explicit output type.

    Every criterion must be *anchored* (score bands describing what each level means) or declare an
    explicit non-score output type — a bare, unanchored criterion is not measurable (AC2).
    """

    name: str
    output_type: CriterionType = CriterionType.SCORE
    anchors: tuple[tuple[str, str], ...] = ()  # ordered (level, description) pairs
    labels: tuple[str, ...] = ()  # allowed values when output_type is LABEL
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ContractError("RubricCriterion: 'name' must be a non-empty string")
        if self.output_type is CriterionType.SCORE and not self.anchors:
            raise ContractError(
                f"RubricCriterion {self.name!r}: a 'score' criterion needs anchored bands "
                "(an unanchored criterion is not measurable)"
            )
        if self.output_type is CriterionType.LABEL and not self.labels:
            raise ContractError(
                f"RubricCriterion {self.name!r}: a 'label' criterion must declare allowed labels"
            )

    @classmethod
    def from_mapping(cls, data: Any, ctx: str) -> Self:
        m = _as_mapping(data, ctx)
        name = _require_str(m, "name", ctx)
        output_type = _coerce_enum(CriterionType, m.get("output_type", "score"), "output_type", ctx)
        anchors_raw = _opt_mapping_or_list(m.get("anchors"), f"{ctx}.anchors")
        labels = tuple(_str_list(m.get("labels"), f"{ctx}.labels"))
        return cls(
            name=name,
            output_type=output_type,
            anchors=anchors_raw,
            labels=labels,
            description=_opt_str(m, "description", ctx),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "output_type": self.output_type.value}
        if self.anchors:
            out["anchors"] = dict(self.anchors)
        if self.labels:
            out["labels"] = list(self.labels)
        if self.description is not None:
            out["description"] = self.description
        return out


@dataclass(frozen=True)
class RubricResponseSchema:
    """What the judge must return, beyond the overall score + rationale.

    ``facets`` are the criterion names the parser will accept — an undeclared facet in a response is
    rejected (AC2). ``allow_violations`` / ``allow_citations`` gate those optional arrays;
    ``require_citations`` demands at least one resolvable citation for a scored response.
    """

    facets: tuple[str, ...] = ()
    allow_violations: bool = True
    allow_citations: bool = True
    require_citations: bool = False

    @classmethod
    def from_mapping(cls, data: Any, ctx: str) -> Self:
        m = _as_mapping(data, ctx)
        return cls(
            facets=tuple(_str_list(m.get("facets"), f"{ctx}.facets")),
            allow_violations=_opt_bool(m, "allow_violations", ctx, default=True),
            allow_citations=_opt_bool(m, "allow_citations", ctx, default=True),
            require_citations=_opt_bool(m, "require_citations", ctx, default=False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "facets": list(self.facets),
            "allow_violations": self.allow_violations,
            "allow_citations": self.allow_citations,
            "require_citations": self.require_citations,
        }


@dataclass(frozen=True)
class RubricSpec:
    """A structured, versioned, host-owned rubric. Grants no authority.

    A scalar markdown rubric loads into this shape too (one implicit unanchored construct, no
    facets) through :func:`from_markdown`, so the command judge's score+rationale contract holds.
    """

    construct: str
    criteria: tuple[RubricCriterion, ...]
    response: RubricResponseSchema
    evidence_layers: tuple[str, ...] = ("input", "output")
    refusal_conditions: tuple[str, ...] = ()
    scope: str | None = None
    version: str = "1"
    prompt_version: str | None = None
    parser_version: str = "1"
    status: RubricStatus = RubricStatus.PROPOSED

    def __post_init__(self) -> None:
        if not self.construct or not self.construct.strip():
            raise ContractError("RubricSpec: 'construct' must be a non-empty string")
        names = [c.name for c in self.criteria]
        if len(names) != len(set(names)):
            raise ContractError("RubricSpec: criterion names must be unique")
        declared = set(names)
        undeclared = [f for f in self.response.facets if f not in declared]
        if undeclared:
            raise ContractError(
                f"RubricSpec: response facets {undeclared} are not declared criteria {names}"
            )
        if not self.evidence_layers:
            raise ContractError("RubricSpec: 'evidence_layers' must declare at least one layer")

    @property
    def is_structured(self) -> bool:
        """True when the rubric declares facets — the judge must return the structured schema."""
        return bool(self.response.facets)

    def content_digest(self) -> str:
        """A stable digest of the score-determining rubric content (enters judge provenance)."""
        payload = json.dumps(self._digest_body(), sort_keys=True, ensure_ascii=True)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _digest_body(self) -> dict[str, Any]:
        # The review status is deliberately excluded: reviewing a rubric does not change what it
        # measures, so it must not break comparability. Version/prompt/parser DO.
        return {
            "construct": self.construct,
            "criteria": [c.to_dict() for c in self.criteria],
            "response": self.response.to_dict(),
            "evidence_layers": list(self.evidence_layers),
            "refusal_conditions": list(self.refusal_conditions),
            "scope": self.scope,
            "version": self.version,
            "prompt_version": self.prompt_version,
            "parser_version": self.parser_version,
        }

    @classmethod
    def from_markdown(cls, text: str, *, version: str = "1", parser_version: str = "1") -> Self:
        """Load a scalar markdown rubric as an unanchored construct with no facets (compat path)."""
        construct = text.strip() or "Score how well the output satisfies its stated construct."
        return cls(
            construct=construct,
            criteria=(),
            response=RubricResponseSchema(),
            version=version,
            parser_version=parser_version,
        )

    @classmethod
    def from_mapping(cls, data: Any, ctx: str = "rubric") -> Self:
        m = _as_mapping(data, ctx)
        schema = _opt_str(m, "schema", ctx)
        if schema is not None and schema != RUBRIC_SCHEMA:
            raise ContractError(
                f"{ctx}: unknown rubric schema {schema!r}; expected {RUBRIC_SCHEMA}"
            )
        criteria = tuple(
            RubricCriterion.from_mapping(c, f"{ctx}.criteria[{i}]")
            for i, c in enumerate(_opt_list(m, "criteria", ctx))
        )
        response = (
            RubricResponseSchema.from_mapping(m["response"], f"{ctx}.response")
            if m.get("response") is not None
            else RubricResponseSchema(facets=tuple(c.name for c in criteria))
        )
        return cls(
            construct=_require_str(m, "construct", ctx),
            criteria=criteria,
            response=response,
            evidence_layers=tuple(_str_list(m.get("evidence_layers"), f"{ctx}.evidence_layers"))
            or ("input", "output"),
            refusal_conditions=tuple(
                _str_list(m.get("refusal_conditions"), f"{ctx}.refusal_conditions")
            ),
            scope=_opt_str(m, "scope", ctx),
            version=_opt_str(m, "version", ctx) or "1",
            prompt_version=_opt_str(m, "prompt_version", ctx),
            parser_version=_opt_str(m, "parser_version", ctx) or "1",
            status=_coerce_enum(RubricStatus, m.get("status", "proposed"), "status", ctx),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schema": RUBRIC_SCHEMA, **self._digest_body()}
        out["status"] = self.status.value
        return out


def _str_list(raw: Any, ctx: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
        raise ContractError(f"{ctx}: must be a list of non-empty strings")
    return list(raw)


def _opt_mapping_or_list(raw: Any, ctx: str) -> tuple[tuple[str, str], ...]:
    """Anchors as an ordered mapping ``{level: description}`` (dicts preserve insertion order)."""
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise ContractError(f"{ctx}: 'anchors' must be a mapping of level -> description")
    pairs: list[tuple[str, str]] = []
    for level, desc in raw.items():
        if not isinstance(level, str) or not isinstance(desc, str):
            raise ContractError(f"{ctx}: anchor levels and descriptions must be strings")
        pairs.append((level, desc))
    return tuple(pairs)


# --------------------------------------------------------------------------- #
# Structured response parsing
# --------------------------------------------------------------------------- #


class ParsedResponseStatus(enum.StrEnum):
    """The outcome of parsing a judge response against a rubric's declared schema."""

    OK = "ok"
    REFUSED = "refused"
    MISSING_EVIDENCE = "missing_evidence"
    PARSER_ERROR = "parser_error"


@dataclass(frozen=True)
class ParsedJudgeResponse:
    """The typed result of parsing a judge's JSON against a :class:`RubricSpec`.

    A non-``OK`` status carries no ``score`` — a refusal, missing evidence, or a parser error is
    never a fabricated low score. ``facets``/``violations``/``citations`` are the validated
    structured content the evidence record will carry.
    """

    status: ParsedResponseStatus
    score: float | None = None
    rationale: str | None = None
    facets: tuple[tuple[str, float | bool | str], ...] = ()
    violations: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    refusal_reason: str | None = None
    message: str | None = None

    def facets_dict(self) -> dict[str, float | bool | str]:
        return dict(self.facets)


def _err(message: str) -> ParsedJudgeResponse:
    return ParsedJudgeResponse(status=ParsedResponseStatus.PARSER_ERROR, message=message)


def _finite_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def parse_judge_response(
    payload: Any, spec: RubricSpec, *, dossier_refs: frozenset[str] = frozenset()
) -> ParsedJudgeResponse:
    """Validate a judge's parsed JSON object against ``spec``'s declared response schema.

    Distinguishes a valid score, a refusal, missing evidence, and a parser error (AC3). Rejects any
    facet not declared as a criterion (AC2). Cited evidence refs must resolve within
    ``dossier_refs`` — an invented citation is a parser error (AC4). A non-OK outcome carries no
    score.
    """
    if not isinstance(payload, dict):
        return _err("judge response was not a JSON object")

    declined = _declined_outcome(payload)
    if declined is not None:
        return declined

    score = _finite_score(payload.get("score", payload.get("value")))
    if score is None:
        return _err("judge response had no finite numeric 'score'")

    facets_result, facet_err = _parse_facets(payload.get("facets"), spec)
    if facet_err is not None:
        return _err(facet_err)

    violations, viol_err = _parse_violations(payload.get("violations"), spec)
    if viol_err is not None:
        return _err(viol_err)

    citations, cite_err = _parse_citations(payload.get("citations"), spec, dossier_refs)
    if cite_err is not None:
        return _err(cite_err)

    rationale = payload.get("rationale")
    return ParsedJudgeResponse(
        status=ParsedResponseStatus.OK,
        score=_clamp01(score),
        rationale=rationale if isinstance(rationale, str) else None,
        facets=tuple(facets_result),
        violations=tuple(violations),
        citations=tuple(citations),
    )


def _declined_outcome(payload: dict[str, Any]) -> ParsedJudgeResponse | None:
    """A refusal or missing-evidence outcome (no score), or ``None`` if the judge did score."""
    if payload.get("refused") is True or payload.get("refusal") not in (None, False):
        reason = payload.get("refusal") if isinstance(payload.get("refusal"), str) else None
        return ParsedJudgeResponse(status=ParsedResponseStatus.REFUSED, refusal_reason=reason)
    if payload.get("missing_evidence") is True:
        return ParsedJudgeResponse(status=ParsedResponseStatus.MISSING_EVIDENCE)
    return None


def _parse_violations(raw: Any, spec: RubricSpec) -> tuple[list[str], str | None]:
    violations = raw if raw is not None else []
    if not isinstance(violations, list) or not all(isinstance(v, str) for v in violations):
        return [], "'violations' must be a list of strings"
    if violations and not spec.response.allow_violations:
        return [], "judge response carried violations, but the rubric does not allow them"
    return violations, None


def _parse_facets(
    raw: Any, spec: RubricSpec
) -> tuple[list[tuple[str, float | bool | str]], str | None]:
    if raw is None:
        return [], None
    if not isinstance(raw, dict):
        return [], "'facets' must be a mapping of criterion -> value"
    declared = {c.name: c for c in spec.criteria}
    result: list[tuple[str, float | bool | str]] = []
    for name, value in raw.items():
        crit = declared.get(name)
        if crit is None:
            return [], f"undeclared facet {name!r} (declared: {sorted(declared)})"
        parsed, ok = _coerce_facet_value(crit, value)
        if not ok:
            return [], f"facet {name!r} value {value!r} is invalid for a {crit.output_type.value}"
        result.append((name, parsed))
    return result, None


def _coerce_facet_value(crit: RubricCriterion, value: Any) -> tuple[float | bool | str, bool]:
    if crit.output_type is CriterionType.SCORE:
        score = _finite_score(value)
        if score is None:
            return 0.0, False
        return _clamp01(score), True
    if crit.output_type is CriterionType.BOOLEAN:
        return (value, True) if isinstance(value, bool) else (False, False)
    if isinstance(value, str) and value in crit.labels:
        return value, True
    return "", False


def _parse_citations(
    raw: Any, spec: RubricSpec, dossier_refs: frozenset[str]
) -> tuple[list[str], str | None]:
    citations = raw if raw is not None else []
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        return [], "'citations' must be a list of strings"
    if citations and not spec.response.allow_citations:
        return [], "judge response carried citations, but the rubric does not allow them"
    unresolved = [c for c in citations if c not in dossier_refs]
    if unresolved:
        return [], f"cited evidence refs do not resolve in the dossier: {unresolved}"
    if spec.response.require_citations and not citations:
        return [], "the rubric requires at least one cited evidence ref, but none was given"
    return citations, None
