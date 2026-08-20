"""Judge instrument identity (M7 G9).

Alpha recorded a judge with opaque *reference* strings (``model_ref``, ``rubric_ref``,
``prompt_ref``) plus per-call usage. That is not enough to tell whether two runs used
the *same* measuring instrument: a judge can change provider, seed, temperature, or the
resolved prompt text while every ``*_ref`` name stays the same, and the old agreement
labels would silently look like they still calibrate the new instrument (the LLM-only
-> hybrid swap an audit caught).

:class:`JudgeInstrument` captures the complete identity — provider, model, decoding
settings, and the **content** digests of the resolved prompt and rubric (not their
names) — and content-addresses all of it. That digest is what a
:class:`~evalglass.core.agreement.JudgeAgreementStudy` binds, so any real change to the
instrument shifts the digest and resolves the calibration as ``drifted``.

Effect-free, stdlib-only. The harness populates the fields from the judge call and
resolves the prompt/rubric text to digests; the core only defines and hashes identity.
See ``docs/TETA_REDESIGN.md`` §5 (G9).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

from evalglass.core._validation import ContractError, _as_mapping, _opt_mapping, _require_str

_HEX = frozenset("0123456789abcdef")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(c in _HEX for c in value)


@dataclass(frozen=True)
class JudgeInstrument:
    """The complete, content-addressed identity of a judge measurement instrument."""

    provider: str
    model: str
    prompt_sha256: str
    rubric_sha256: str
    parser_version: str
    seed: int | None = None
    temperature: float | None = None
    decoding: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("provider", "model", "parser_version"):
            v = getattr(self, name)
            if not isinstance(v, str) or not v.strip():
                raise ContractError(f"JudgeInstrument.{name} must be a non-empty string")
        for name in ("prompt_sha256", "rubric_sha256"):
            if not _is_sha256(getattr(self, name)):
                raise ContractError(f"JudgeInstrument.{name} must be a 64-char hex sha256")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ContractError("JudgeInstrument.seed, if present, must be an int")
        if self.temperature is not None:
            if isinstance(self.temperature, bool) or not isinstance(self.temperature, int | float):
                raise ContractError("JudgeInstrument.temperature must be a number")
            if not math.isfinite(self.temperature):
                raise ContractError("JudgeInstrument.temperature must be finite")

    def digest(self) -> str:
        """Content address over every identity-bearing field (feeds study drift detection)."""
        payload = {
            "provider": self.provider,
            "model": self.model,
            "prompt_sha256": self.prompt_sha256,
            "rubric_sha256": self.rubric_sha256,
            "parser_version": self.parser_version,
            "seed": self.seed,
            "temperature": self.temperature,
            "decoding": dict(self.decoding),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "prompt_sha256": self.prompt_sha256,
            "rubric_sha256": self.rubric_sha256,
            "parser_version": self.parser_version,
        }
        if self.seed is not None:
            out["seed"] = self.seed
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.decoding:
            out["decoding"] = dict(self.decoding)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        m = _as_mapping(data, "JudgeInstrument")
        seed = m.get("seed")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise ContractError("JudgeInstrument.seed must be an int")
        temp = m.get("temperature")
        if temp is not None and (isinstance(temp, bool) or not isinstance(temp, int | float)):
            raise ContractError("JudgeInstrument.temperature must be a number")
        return cls(
            provider=_require_str(m, "provider", "JudgeInstrument"),
            model=_require_str(m, "model", "JudgeInstrument"),
            prompt_sha256=_require_str(m, "prompt_sha256", "JudgeInstrument"),
            rubric_sha256=_require_str(m, "rubric_sha256", "JudgeInstrument"),
            parser_version=_require_str(m, "parser_version", "JudgeInstrument"),
            seed=seed,
            temperature=None if temp is None else float(temp),
            decoding=_opt_mapping(m, "decoding", "JudgeInstrument"),
        )
