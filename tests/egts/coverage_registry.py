"""Coverage registry + proof-planner foundation (EGTS-M0-2).

The registry records, per product ticket / public contract, which scenarios prove
it and the current status. It exists to make missing proof a first-class result
(``tests/CLAUDE.md §14``): an obligation that is neither proven (``covered`` with a
scenario) nor explicitly accounted for (``blocked``/``optional``) is a **gap**.
Claiming ``covered`` with no scenario is the worst case — an integrity violation.

The proof planner foundation selects obligations for a milestone or ticket.
This module mirrors ``scenario.py``'s small fail-closed validation helpers rather
than importing them, so the two stay independent.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


class CoverageError(ValueError):
    """Raised when a coverage registry is structurally invalid."""


class CoverageStatus(enum.StrEnum):
    COVERED = "covered"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    OPTIONAL = "optional"
    NOT_STARTED = "not_started"


_ACCOUNTED = frozenset({CoverageStatus.BLOCKED, CoverageStatus.OPTIONAL})


@dataclass(frozen=True)
class CoverageRow:
    product_ticket: str
    public_contract: str
    status: CoverageStatus
    scenario_ids: list[str] = field(default_factory=list)
    architecture_section: str | None = None
    fixture_families: list[str] = field(default_factory=list)
    checker_families: list[str] = field(default_factory=list)
    required_command: str | None = None
    negative_control: str | None = None
    #: Why a ``not_started`` obligation is *honestly* deferred (e.g. a capability
    #: that is not built and no required path loads). Mandatory for ``not_started``
    #: (parse fails without it) so a deferred row reads as "NOT EXERCISED — <reason>"
    #: rather than a silent gap. Alignment AT0, EG-AT0-6.
    not_exercised_reason: str | None = None

    @property
    def is_satisfied(self) -> bool:
        """A row is satisfied when it is covered-with-a-scenario, or explicitly accounted for.

        A ``not_started`` row is *accounted* only when it carries an explicit
        ``not_exercised_reason`` — an honestly-deferred capability, never a silent gap.
        """
        if self.status is CoverageStatus.COVERED:
            return bool(self.scenario_ids)
        if self.status is CoverageStatus.NOT_STARTED:
            return bool(self.not_exercised_reason)
        return self.status in _ACCOUNTED

    @property
    def is_not_exercised(self) -> bool:
        """An honestly-deferred obligation: ``not_started`` with a stated reason."""
        return self.status is CoverageStatus.NOT_STARTED and bool(self.not_exercised_reason)

    @property
    def is_integrity_violation(self) -> bool:
        """Claiming ``covered`` with no scenario is an overclaim — proof that does not exist."""
        return self.status is CoverageStatus.COVERED and not self.scenario_ids


@dataclass(frozen=True)
class CoverageRegistry:
    rows: list[CoverageRow]


def _require(data: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in data:
        raise CoverageError(f"{ctx}: missing required field '{key}'")
    return data[key]


def _require_str(data: Mapping[str, Any], key: str, ctx: str) -> str:
    value = _require(data, key, ctx)
    if not isinstance(value, str) or not value:
        raise CoverageError(f"{ctx}: field '{key}' must be a non-empty string, got {value!r}")
    return value


def _str_list(value: Any, key: str, ctx: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise CoverageError(f"{ctx}: field '{key}' must be a list of non-blank strings")
    return list(value)


def _parse_row(data: Any, index: int) -> CoverageRow:
    ctx = f"coverage row {index}"
    if not isinstance(data, Mapping):
        raise CoverageError(f"{ctx}: must be a mapping, got {type(data).__name__}")
    status_raw = _require(data, "status", ctx)
    try:
        status = CoverageStatus(status_raw)
    except ValueError:
        allowed = ", ".join(s.value for s in CoverageStatus)
        raise CoverageError(
            f"{ctx}: field 'status' has unknown value {status_raw!r}; expected one of: {allowed}"
        ) from None
    optional_str = data.get("architecture_section")
    command = data.get("required_command")
    negative = data.get("negative_control")
    reason_raw = data.get("not_exercised_reason")
    reason = reason_raw if isinstance(reason_raw, str) and reason_raw.strip() else None
    if status is CoverageStatus.NOT_STARTED and reason is None:
        raise CoverageError(
            f"{ctx}: a 'not_started' row must carry a non-blank 'not_exercised_reason' so a "
            "deferred obligation reads as 'NOT EXERCISED — <reason>', never a silent gap"
        )
    return CoverageRow(
        product_ticket=_require_str(data, "product_ticket", ctx),
        public_contract=_require_str(data, "public_contract", ctx),
        status=status,
        scenario_ids=_str_list(data.get("scenario_ids", []), "scenario_ids", ctx),
        architecture_section=optional_str if isinstance(optional_str, str) else None,
        fixture_families=_str_list(data.get("fixture_families", []), "fixture_families", ctx),
        checker_families=_str_list(data.get("checker_families", []), "checker_families", ctx),
        required_command=command if isinstance(command, str) else None,
        negative_control=negative if isinstance(negative, str) else None,
        not_exercised_reason=reason,
    )


def parse_registry(data: Mapping[str, Any]) -> CoverageRegistry:
    """Validate a coverage-registry mapping into a typed :class:`CoverageRegistry`."""
    if not isinstance(data, Mapping) or "rows" not in data:
        raise CoverageError("coverage registry must be a mapping with a 'rows' list")
    rows = data["rows"]
    if not isinstance(rows, list):
        raise CoverageError("coverage registry 'rows' must be a list")
    if not rows:
        raise CoverageError(
            "coverage registry 'rows' is empty — a registry must enumerate at least one "
            "obligation, or completeness checks would pass with nothing proven"
        )
    return CoverageRegistry(rows=[_parse_row(row, i) for i, row in enumerate(rows)])


def load_registry(path: Path | str) -> CoverageRegistry:
    """Load and validate a coverage registry from a YAML file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return parse_registry(data)


def find_gaps(registry: CoverageRegistry) -> list[CoverageRow]:
    """Rows that are not honestly satisfied (open, partial, or overclaimed)."""
    return [row for row in registry.rows if not row.is_satisfied]


def integrity_violations(registry: CoverageRegistry) -> list[CoverageRow]:
    """Rows claiming ``covered`` without any scenario to back the claim."""
    return [row for row in registry.rows if row.is_integrity_violation]


def plan_obligations(
    registry: CoverageRegistry,
    *,
    milestone: str | None = None,
    ticket: str | None = None,
) -> list[CoverageRow]:
    """Select obligations for a milestone (e.g. ``"M0"``) or a specific ticket."""
    rows = registry.rows
    if ticket is not None:
        rows = [row for row in rows if row.product_ticket == ticket]
    if milestone is not None:
        prefix = f"EG-{milestone}-"
        rows = [row for row in rows if row.product_ticket.startswith(prefix)]
    return list(rows)
