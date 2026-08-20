"""EG-AT0-7 — AUTH-LEDGER-DECISION gate.

Encodes the decision (ADR 0028) that ``evals/authority.json`` is a host-owned
*ledger only*: the runtime resolves gating authority from ``evalglass.yaml`` +
``calibration/*.json`` and **never reads** ``authority.json``. Until this
decision is recorded (the ADR test) and proven (the runtime-ignores-ledger
test), authority fixtures cannot be trusted, so this gate is the precondition
for treating an empty ledger as the no-authority default.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests.egts.host_repo import AuthorityState, make_vendored_host

_SRC = Path(__file__).resolve().parents[2] / "src" / "evalglass"
_RUNTIME_PKGS = ("core", "harness", "adapters")


def test_authority_ledger_decision_is_recorded_in_an_adr() -> None:
    """The gate is red until the ledger-only policy is encoded in an ADR (ADR 0028)."""
    adr = _SRC.parents[1] / "adrs" / "0028-authority-json-is-ledger-only.md"
    assert adr.is_file(), "ADR 0028 (authority-ledger decision) must exist"
    text = adr.read_text(encoding="utf-8").lower()
    assert "ledger" in text
    assert "never read" in text
    index = (_SRC.parents[1] / "adrs" / "README.md").read_text(encoding="utf-8")
    assert "0028-authority-json-is-ledger-only.md" in index


def test_no_runtime_module_references_authority_json_or_record() -> None:
    """Structural proof of ADR 0028: no runtime module reads the ledger.

    ``authority.json`` / ``AuthorityRecord`` live only in the installer. A
    runtime module referencing either would be a hidden second authority path.
    """
    offenders: list[str] = []
    for pkg in _RUNTIME_PKGS:
        for path in (_SRC / pkg).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            # AST-confirm it's a real reference, not an incidental substring in a word.
            if ("authority.json" in source or "AuthorityRecord" in source) and _references_ledger(
                source
            ):
                offenders.append(str(path.relative_to(_SRC.parents[1])))
    assert not offenders, f"runtime modules must not read the authority ledger: {offenders}"


def _references_ledger(source: str) -> bool:
    if "authority.json" in source:
        return True
    tree = ast.parse(source)
    return any(
        isinstance(node, ast.Name) and node.id == "AuthorityRecord" for node in ast.walk(tree)
    )


@pytest.mark.fixture_e2e
@pytest.mark.slow
def test_populating_authority_json_does_not_grant_a_gate(tmp_path: Path) -> None:
    """A proposed-dataset run stays informational even if the ledger is filled in.

    The config *tries* to gate (``metric_status: gating``) on a ``proposed``
    dataset; populating ``authority.json`` with approvals must NOT flip the
    verdict, because the runtime never consults the ledger.
    """
    host = make_vendored_host(tmp_path, "ledger", authority_state=AuthorityState.PROPOSED_DATASET)
    ledger = host.evals_dir / "authority.json"
    ledger.write_text(
        json.dumps(
            {
                "approved_thresholds": ["exact_match"],
                "validated_datasets": ["datasets/at0.jsonl"],
                "calibrated_judges": [],
            }
        ),
        encoding="utf-8",
    )
    result = host.run(["run", "--config", "evals/evalglass.yaml"])
    assert result.exit_code == 0, result.stderr
    assert result.scorecard is not None
    # The ledger did NOT grant authority — still informational (dataset proposed).
    assert result.scorecard["authority"]["exact_match"]["can_gate"] is False
    assert result.scorecard["verdict"]["verdict"] == "informational"
