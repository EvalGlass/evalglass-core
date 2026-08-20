"""Per-metric example selector — restrict a metric to a subset of examples (EG-V02-4 / K2).

By default every metric scores every example. On a multi-call-site app that flat model
cross-contaminates: a metric drafted for one call site's output also scores records of other call
sites (field-name collisions → false attribution; absent-schema records → phantom failures). A
metric may instead declare an :class:`ExampleSelector` so it scores **only** the examples whose
own ``metadata`` matches host-declared constraints.

The mechanism is strictly **domain-neutral and vendor-neutral**: the constraint keys and values are
host-supplied (typically a per-workflow tag the host's traces already carry — an OTel span name, a
Langfuse observation name, a dataset field). EvalGlass encodes no specific key or value, and infers
none from any framework or tracing convention (``CLAUDE.md`` — generic by contract).

Two honesty rules are built in:

* **Fail-closed match:** an example matches only if *every* constrained key is present in its
  metadata with an allowed value. An absent key is a non-match — a selector never widens a metric's
  population by accident.
* **Integrity bypass:** an example flagged with :data:`INTEGRITY_METADATA_KEY` (the run-integrity
  example the harness injects when input is unreadable) always matches, so an incomplete-input run
  still blocks an active gate regardless of any selector.

Effect-free, stdlib-only, JSON-serializable (it enters the run's gating provenance).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from evalglass.core._validation import ContractError
from evalglass.core.contracts import Example

#: Reserved ``Example.metadata`` flag marking a run-integrity example (e.g. the route-error guard).
#: Such examples must be scored by every metric regardless of any selector. No domain meaning.
INTEGRITY_METADATA_KEY = "__evalglass_integrity__"

#: Reserved ``Example.metadata`` key the Harness stamps with a subject's configured-source name, so
#: a source-bound metric (D1) scores **only** its candidate sources through the one selector
#: implementation. Host-neutral and reserved (double-underscore prefix); never a domain key.
SOURCE_METADATA_KEY = "__evalglass_source__"


@dataclass(frozen=True)
class ExampleSelector:
    """Matches examples whose ``metadata`` satisfies every host-declared constraint (fail-closed).

    See the module docstring for the honesty rules (fail-closed match + integrity bypass).
    """

    #: key -> the allowed values for that ``metadata`` key. An example matches iff, for every key,
    #: the example's metadata holds that key with a value equal to one of the allowed values.
    constraints: Mapping[str, tuple[Any, ...]]

    def __post_init__(self) -> None:
        if not isinstance(self.constraints, Mapping) or not self.constraints:
            raise ContractError("ExampleSelector: constraints must be a non-empty mapping")
        for key, allowed in self.constraints.items():
            if not isinstance(key, str) or not key:
                raise ContractError("ExampleSelector: each constraint key must be a non-empty str")
            if not isinstance(allowed, tuple) or not allowed:
                raise ContractError(
                    f"ExampleSelector: allowed values for {key!r} must be a non-empty tuple"
                )

    def matches(self, example: Example) -> bool:
        """True iff the example is an integrity example, or satisfies every constraint."""
        metadata = example.metadata
        if metadata.get(INTEGRITY_METADATA_KEY):
            return True
        for key, allowed in self.constraints.items():
            if key not in metadata:
                return False
            # Compare by equality (not set membership) so an unhashable metadata value (e.g. a list)
            # is a clean non-match rather than a TypeError.
            if not any(metadata[key] == value for value in allowed):
                return False
        return True

    def to_dict(self) -> dict[str, list[Any]]:
        return {key: list(allowed) for key, allowed in sorted(self.constraints.items())}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        if not isinstance(data, Mapping):
            raise ContractError(f"ExampleSelector: expected a mapping, got {type(data).__name__}")
        constraints: dict[str, tuple[Any, ...]] = {}
        for key, raw in data.items():
            values = raw if isinstance(raw, list) else [raw]
            constraints[str(key)] = tuple(values)
        return cls(constraints=constraints)
