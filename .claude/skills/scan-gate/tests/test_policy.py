"""Slice 3 (SG-P0-3): typed policy loader tests.

Proves: the shipped fast/required policies load and validate; profile selection
resolves; and every malformed-policy case (bad YAML, missing key, bad severity,
unknown detector, dangling path-group reference, unknown profile) raises
PolicyError -- which the CLI maps to BLOCKED (missing proof, never PASS).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.contracts import Severity
from scripts.policy import Policy, PolicyError, load_policy

SKILL_ROOT = Path(__file__).resolve().parent.parent
POLICIES = SKILL_ROOT / "policies"


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "policy.yml"
    p.write_text(text, encoding="utf-8")
    return p


VALID = """
version: test-policy@1
profiles:
  fast:
    detectors: [path_classifier, secrets]
    network: disabled
path_groups:
  all: ["**"]
  required_tier: ["src/evalglass/core/**"]
rules:
  - id: secrets.no_new_secrets
    detector: secrets
    severity: fail
    applies_to: [all]
    message: "No new secrets."
"""


def test_shipped_policies_load_and_validate() -> None:
    for name in ("evalglass.fast.yml", "evalglass.required.yml"):
        policy = load_policy(POLICIES / name)
        assert isinstance(policy, Policy)
        assert policy.version
        assert policy.profiles


def test_shipped_fast_has_fast_profile() -> None:
    policy = load_policy(POLICIES / "evalglass.fast.yml")
    prof = policy.profile("fast")
    assert "path_classifier" in prof.detectors
    assert prof.network == "disabled"


def test_valid_policy_round_trips(tmp_path: Path) -> None:
    policy = load_policy(_write(tmp_path, VALID))
    assert policy.profile("fast").detectors == ("path_classifier", "secrets")
    assert policy.rules[0].severity is Severity.FAIL


def test_unknown_profile_raises(tmp_path: Path) -> None:
    policy = load_policy(_write(tmp_path, VALID))
    with pytest.raises(PolicyError):
        policy.profile("nope")


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        load_policy(tmp_path / "absent.yml")


def test_bad_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, "version: [unterminated\n"))


def test_missing_top_level_key_raises(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, "version: x\nprofiles: {}\n"))


def test_bad_severity_raises(tmp_path: Path) -> None:
    bad = VALID.replace("severity: fail", "severity: catastrophic")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, bad))


def test_unknown_detector_raises(tmp_path: Path) -> None:
    bad = VALID.replace("detectors: [path_classifier, secrets]", "detectors: [teleporter]")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, bad))


def test_rule_dangling_path_group_raises(tmp_path: Path) -> None:
    bad = VALID.replace("applies_to: [all]", "applies_to: [does_not_exist]")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, bad))


def test_bad_network_mode_raises(tmp_path: Path) -> None:
    bad = VALID.replace("network: disabled", "network: wide-open")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, bad))


def test_zero_rules_blocked(tmp_path: Path) -> None:
    head, _, _ = VALID.partition("rules:")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, head + "rules: []\n"))


def test_empty_detectors_blocked(tmp_path: Path) -> None:
    bad = VALID.replace("detectors: [path_classifier, secrets]", "detectors: []")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, bad))


def test_empty_applies_to_blocked(tmp_path: Path) -> None:
    bad = VALID.replace("applies_to: [all]", "applies_to: []")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, bad))


def test_non_string_network_is_policy_error_not_crash(tmp_path: Path) -> None:
    bad = VALID.replace("network: disabled", "network: [disabled]")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, bad))


def test_non_string_detector_is_policy_error_not_crash(tmp_path: Path) -> None:
    bad = VALID.replace("detector: secrets\n    severity", "detector: [secrets]\n    severity")
    with pytest.raises(PolicyError):
        load_policy(_write(tmp_path, bad))
