"""ClaimSpec — the construct/validity argument behind a metric (M7 G10).

Neither alpha nor the book models validity as a first-class object: ``dataset_status:
validated`` is a bare host assertion, not an argument that connects a construct, a target
population, a sampling frame, known threats, and the interpretation the number licenses.
A tighter interval never fixes a score that fails to generalize to its construct
(Cronbach & Meehl); measurement-science language must not imply the tool implemented
measurement science merely because it prints a band.

:class:`ClaimSpec` is that argument, made explicit and *optional*. It carries no gating
power on its own — it is host-owned truth a human writes and reviews — but it makes the
scorecard's claim narrower when absent and links the validity evidence when present, and
its digest can be bound by an :class:`~evalglass.core.grant.AuthorityGrant` so a gate can
require a specific approved validity case.

Effect-free, stdlib-only; the core never reads the clock (expiry takes ``now`` from the
harness). See ``docs/TETA_REDESIGN.md`` §2 (G10).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core._validation import ContractError, _as_mapping, _opt_str, _require_str


def _tuple(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ContractError(f"ClaimSpec.{name} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"ClaimSpec.{name} entries must be non-empty strings")
        out.append(item)
    return tuple(out)


@dataclass(frozen=True)
class ClaimSpec:
    """A host-owned construct/validity argument for a metric's interpretation."""

    construct: str
    intended_use: str
    target_population: str
    sampling_frame: str
    excluded_constructs: tuple[str, ...] = ()
    prohibited_extrapolations: tuple[str, ...] = ()
    coverage_facets: tuple[str, ...] = ()
    known_threats: tuple[str, ...] = ()
    validity_evidence_refs: tuple[str, ...] = ()
    reviewer: str | None = None
    review_expires_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("construct", "intended_use", "target_population", "sampling_frame"):
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                raise ContractError(f"ClaimSpec.{name} must be a non-empty string")
        # Validate + normalize the sequence fields (lists -> tuples) so a directly-built
        # spec is validated exactly like a parsed one and compares equal after a round trip.
        for name in (
            "excluded_constructs",
            "prohibited_extrapolations",
            "coverage_facets",
            "known_threats",
            "validity_evidence_refs",
        ):
            object.__setattr__(self, name, _tuple(getattr(self, name), name))
        for name in ("reviewer", "review_expires_at"):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, str) or not v.strip()):
                raise ContractError(f"ClaimSpec.{name}, if present, must be a non-empty string")

    def is_expired(self, now: str) -> bool:
        """Whether the review has lapsed as of ``now`` (ISO-8601, string-comparable)."""
        return self.review_expires_at is not None and now > self.review_expires_at

    def digest(self) -> str:
        """Content address the whole validity argument (for grant binding)."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "construct": self.construct,
            "intended_use": self.intended_use,
            "target_population": self.target_population,
            "sampling_frame": self.sampling_frame,
        }
        for name in (
            "excluded_constructs",
            "prohibited_extrapolations",
            "coverage_facets",
            "known_threats",
            "validity_evidence_refs",
        ):
            v = getattr(self, name)
            if v:
                out[name] = list(v)
        for name in ("reviewer", "review_expires_at"):
            v = getattr(self, name)
            if v is not None:
                out[name] = v
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "ClaimSpec")
        return cls(
            construct=_require_str(m, "construct", "ClaimSpec"),
            intended_use=_require_str(m, "intended_use", "ClaimSpec"),
            target_population=_require_str(m, "target_population", "ClaimSpec"),
            sampling_frame=_require_str(m, "sampling_frame", "ClaimSpec"),
            excluded_constructs=_tuple(m.get("excluded_constructs"), "excluded_constructs"),
            prohibited_extrapolations=_tuple(
                m.get("prohibited_extrapolations"), "prohibited_extrapolations"
            ),
            coverage_facets=_tuple(m.get("coverage_facets"), "coverage_facets"),
            known_threats=_tuple(m.get("known_threats"), "known_threats"),
            validity_evidence_refs=_tuple(
                m.get("validity_evidence_refs"), "validity_evidence_refs"
            ),
            reviewer=_opt_str(m, "reviewer", "ClaimSpec"),
            review_expires_at=_opt_str(m, "review_expires_at", "ClaimSpec"),
        )
