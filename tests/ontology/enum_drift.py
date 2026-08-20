"""Track B — code↔ontology enum drift (EG-AT5-3; alignment plan §D 6C, Appendix A).

Compares the ontology's ``Enum`` entities (their ``EnumValue`` members) to the **live** Python
enums, producing an explicit, ordered drift report. Track B does not assume the artifact already
mirrors live code; it reports the drift exactly, and a committed *expected-drift manifest* pins the
known, intentional differences (the authority resolution-ladder vs ``AuthorityLevel``; the partial
``DataPolicy``; the exit-code vs ``ExitClass`` representation; the live enums the ontology does not
model yet). The guard is green only when the produced drift equals that manifest.

Test-tier only — it imports live enums on purpose to compare them; ``src/evalglass/**`` never
imports this module.
"""

from __future__ import annotations

import enum
import importlib
import pkgutil
from collections.abc import Mapping
from typing import Any

import evalglass.core
from evalglass.core.authority import (
    AuthorityLevel,
    DatasetStatus,
    JudgeCalibration,
    MetricStatus,
    ThresholdApproval,
)
from evalglass.core.contracts import DataPolicy
from evalglass.core.provenance import BaselineState
from evalglass.core.scores import ScoreStatus, Validity
from evalglass.core.verdict import Verdict
from evalglass.harness.exits import ExitClass
from evalglass.harness.lanes import LanePort, LaneStatus, Maturity
from tests.ontology.ontology_loader import Ontology

#: Every live product enum the ontology is reconciled against (Appendix A).
LIVE_ENUMS: dict[str, type[enum.Enum]] = {
    "Verdict": Verdict,
    "ScoreStatus": ScoreStatus,
    "Validity": Validity,
    "DataPolicy": DataPolicy,
    "BaselineState": BaselineState,
    "AuthorityLevel": AuthorityLevel,
    "DatasetStatus": DatasetStatus,
    "MetricStatus": MetricStatus,
    "ThresholdApproval": ThresholdApproval,
    "JudgeCalibration": JudgeCalibration,
    "ExitClass": ExitClass,
    "LaneStatus": LaneStatus,
    "LanePort": LanePort,
    # The capability-status enum (Appendix A); the ontology models no Enum entity for it yet.
    "Maturity": Maturity,
}

#: Which ontology ``Enum`` entity is meant to model which live enum.
ONTOLOGY_TO_LIVE: dict[str, str] = {
    "enum.verdict": "Verdict",
    "enum.score-status": "ScoreStatus",
    "enum.validity": "Validity",
    "enum.data-policy": "DataPolicy",
    "enum.baseline-state": "BaselineState",
    "enum.authority": "AuthorityLevel",
    "enum.dataset-status": "DatasetStatus",
    "enum.metric-status": "MetricStatus",
    "enum.exit-class": "ExitClass",
    "enum.threshold-approval": "ThresholdApproval",
    "enum.judge-calibration": "JudgeCalibration",
    "enum.lane-port": "LanePort",
    "enum.lane-status": "LaneStatus",
    "enum.maturity": "Maturity",
}


#: Modules outside ``core`` whose enums are also part of the reconciled product surface.
_EXTRA_ENUM_MODULES = ("evalglass.harness.exits", "evalglass.harness.lanes")


def discover_live_enums() -> dict[str, str]:
    """Every ``enum.Enum`` defined under ``core/`` + ``harness/exits`` + ``harness/lanes``.

    Discovered dynamically (import + introspection) so a **newly added** live enum that nobody
    mapped or excepted is caught by the master guard (EG-AT5-8), not silently ignored.
    """
    found: dict[str, str] = {}

    def _collect(module_name: str) -> None:
        module = importlib.import_module(module_name)
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, enum.Enum)
                and obj.__module__ == module_name
            ):
                found[obj.__name__] = obj.__module__

    core_pkg = evalglass.core
    for info in pkgutil.walk_packages(core_pkg.__path__, core_pkg.__name__ + "."):
        _collect(info.name)
    for module_name in _EXTRA_ENUM_MODULES:
        _collect(module_name)
    return found


def live_member_values(live_name: str) -> set[str]:
    return {member.value for member in LIVE_ENUMS[live_name]}


def enum_member_drift(ontology_enum_id: str, ontology_values: set[str]) -> dict[str, Any] | None:
    """Drift record for one ontology enum vs its mapped live enum, or ``None`` when they match.

    This is the per-enum detector the negative controls exercise (drop / add a member → drift).
    """
    live_name = ONTOLOGY_TO_LIVE[ontology_enum_id]
    live = live_member_values(live_name)
    if ontology_values == live:
        return None
    return {
        "ontology_enum": ontology_enum_id,
        "live_enum": live_name,
        "kind": "member_mismatch",
        "ontology_only": sorted(ontology_values - live),
        "live_only": sorted(live - ontology_values),
    }


def _member_value(label: str) -> str:
    """``"Verdict: pass"`` -> ``"pass"`` (the artifact encodes the value in the EnumValue label)."""
    return label.split(": ", 1)[1] if ": " in label else label


def extract_enum_members(ontology: Ontology) -> dict[str, set[str]]:
    """Map each ontology ``Enum`` id to its set of ``EnumValue`` member values (via hasValue)."""
    label_by_id = {e.id: e.label for e in ontology.entities}
    members: dict[str, set[str]] = {e.id: set() for e in ontology.by_class("Enum")}
    for rel in ontology.relations:
        if rel.predicate == "hasValue" and rel.src in members:
            members[rel.src].add(_member_value(label_by_id[rel.dst]))
    return members


def compute_enum_drift(members: Mapping[str, set[str]]) -> list[dict[str, Any]]:
    """The full ordered drift report: per-enum member mismatches + live enums not modeled yet."""
    drift: list[dict[str, Any]] = []
    for ontology_enum_id in sorted(ONTOLOGY_TO_LIVE):
        record = enum_member_drift(ontology_enum_id, set(members.get(ontology_enum_id, set())))
        if record is not None:
            drift.append(record)
    modelled = set(ONTOLOGY_TO_LIVE.values())
    for live_name in sorted(LIVE_ENUMS):
        if live_name not in modelled:
            drift.append(
                {"ontology_enum": None, "live_enum": live_name, "kind": "missing_ontology_enum"}
            )
    return drift
