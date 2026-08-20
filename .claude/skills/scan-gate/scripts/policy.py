"""Typed policy loader for the scan-gate skill.

A policy declares path groups, per-profile detector selection + network mode,
and rules (detector + severity + which path groups they apply to). Detectors
themselves are implemented in later slices; this loader validates structure so a
malformed policy fails closed (PolicyError -> BLOCKED) instead of silently
running an empty or wrong scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.contracts import NETWORK_MODES, Severity

try:
    import yaml  # type: ignore[import-untyped]
except ImportError as exc:  # pragma: no cover - pyyaml is present in the dev venv
    yaml = None
    _YAML_ERR: Exception | None = exc
else:
    _YAML_ERR = None

# Detector names the scan-gate knows about. Keeps policy typos from silently
# selecting a non-existent detector. Detectors land in later slices.
ALLOWED_DETECTORS = frozenset(
    {
        "path_classifier",
        "imports_effects",
        "secrets",
        "generated_authority",
        "ci_script_guard",
        "manifest_drift",
    }
)


class PolicyError(Exception):
    """Raised when a policy is missing, unreadable, or structurally invalid."""


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    detector: str
    severity: Severity
    applies_to: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    name: str
    detectors: tuple[str, ...]
    network: str


@dataclass(frozen=True, slots=True)
class Policy:
    version: str
    profiles: dict[str, ProfileConfig]
    path_groups: dict[str, tuple[str, ...]]
    rules: tuple[Rule, ...]

    def profile(self, name: str) -> ProfileConfig:
        try:
            return self.profiles[name]
        except KeyError:
            allowed = ", ".join(sorted(self.profiles))
            raise PolicyError(f"unknown profile {name!r}; available: {allowed}") from None


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise PolicyError(msg)


def _str(value: Any, ctx: str) -> str:
    _expect(isinstance(value, str), f"{ctx}: expected a string")
    return str(value)


def _str_list(value: Any, ctx: str, *, non_empty: bool = False) -> tuple[str, ...]:
    _expect(
        isinstance(value, list) and all(isinstance(x, str) for x in value),
        f"{ctx}: expected a list of strings",
    )
    if non_empty:
        _expect(len(value) > 0, f"{ctx}: must not be empty")
    return tuple(value)


def load_policy(path: Path | str) -> Policy:
    if yaml is None:  # pragma: no cover
        raise PolicyError(f"PyYAML is required to load policies: {_YAML_ERR}")
    path = Path(path)
    if not path.is_file():
        raise PolicyError(f"policy file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PolicyError(f"invalid YAML in {path}: {exc}") from exc

    _expect(isinstance(raw, dict), f"{path}: top-level policy must be a mapping")
    for key in ("version", "profiles", "path_groups", "rules"):
        _expect(key in raw, f"{path}: missing required key {key!r}")
    _expect(
        isinstance(raw["version"], str) and raw["version"] != "",
        f"{path}: version must be a non-empty string",
    )

    path_groups: dict[str, tuple[str, ...]] = {}
    _expect(
        isinstance(raw["path_groups"], dict) and bool(raw["path_groups"]),
        f"{path}: path_groups must be a non-empty mapping",
    )
    for name, globs in raw["path_groups"].items():
        path_groups[name] = _str_list(globs, f"path_groups.{name}", non_empty=True)

    profiles: dict[str, ProfileConfig] = {}
    _expect(
        isinstance(raw["profiles"], dict) and bool(raw["profiles"]),
        f"{path}: profiles must be a non-empty mapping",
    )
    for name, cfg in raw["profiles"].items():
        _expect(isinstance(cfg, dict), f"profiles.{name}: must be a mapping")
        detectors = _str_list(cfg.get("detectors"), f"profiles.{name}.detectors", non_empty=True)
        unknown = sorted(set(detectors) - ALLOWED_DETECTORS)
        _expect(not unknown, f"profiles.{name}: unknown detector(s): {', '.join(unknown)}")
        network = _str(cfg.get("network", "disabled"), f"profiles.{name}.network")
        _expect(
            network in NETWORK_MODES,
            f"profiles.{name}.network: invalid {network!r}; "
            f"allowed: {', '.join(sorted(NETWORK_MODES))}",
        )
        profiles[name] = ProfileConfig(name=name, detectors=detectors, network=network)

    _expect(
        isinstance(raw["rules"], list) and bool(raw["rules"]),
        f"{path}: rules must be a non-empty list",
    )
    rules: list[Rule] = []
    for i, rule in enumerate(raw["rules"]):
        ctx = f"rules[{i}]"
        _expect(isinstance(rule, dict), f"{ctx}: must be a mapping")
        for key in ("id", "detector", "severity", "applies_to", "message"):
            _expect(key in rule, f"{ctx}: missing required key {key!r}")
        detector = _str(rule["detector"], f"{ctx}.detector")
        _expect(detector in ALLOWED_DETECTORS, f"{ctx}: unknown detector {detector!r}")
        severity_raw = _str(rule["severity"], f"{ctx}.severity")
        try:
            severity = Severity(severity_raw)
        except ValueError:
            allowed = ", ".join(s.value for s in Severity)
            raise PolicyError(
                f"{ctx}: invalid severity {severity_raw!r}; allowed: {allowed}"
            ) from None
        applies_to = _str_list(rule["applies_to"], f"{ctx}.applies_to", non_empty=True)
        dangling = sorted(set(applies_to) - set(path_groups))
        _expect(
            not dangling,
            f"{ctx}: applies_to references unknown path group(s): {', '.join(dangling)}",
        )
        rules.append(
            Rule(
                id=_str(rule["id"], f"{ctx}.id"),
                detector=detector,
                severity=severity,
                applies_to=applies_to,
                message=_str(rule["message"], f"{ctx}.message"),
            )
        )

    return Policy(
        version=raw["version"], profiles=profiles, path_groups=path_groups, rules=tuple(rules)
    )
