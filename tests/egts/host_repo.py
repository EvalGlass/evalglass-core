"""EGTS host-repo fixture factories + snapshot helper.

Two factories live here:

* :func:`make_host_repo` (EGTS-M3) — a bare disposable *host* repo (``src/``,
  ignore files, optional CI) for **discovery / install** read-only proofs.
* :func:`make_vendored_host` (alignment AT0, EG-AT0-3) — a host that is *already*
  vendored and scaffolded into a known **authority state**, so e2e/EGTS tests can
  run the vendored runtime (``python -m _evalglass.harness.cli run``) against it
  without re-running the whole installer each time.

``make_vendored_host`` uses the **real** installer (``vendor`` + ``scaffold``),
never a hand-built runtime tree, so the fixture exercises the production vendoring
path. The authority state is driven by a **closed enum**; an unknown or
self-contradictory request fails at construction (``tests/CLAUDE.md §4``).

Authority note (AT0 AUTH-LEDGER decision, see ``adrs/0028``): the runtime never
reads ``evals/authority.json`` — gating authority is resolved from
``evalglass.yaml`` + ``calibration/*.json`` only. So these fixtures grant gating
authority through the config/calibration, and leave ``authority.json`` as the
empty host-owned ledger the scaffold writes.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import subprocess  # nosec B404 — drives the vendored CLI in a clean subprocess (no shell)
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

import evalglass
from evalglass.installer.scaffold import scaffold
from evalglass.installer.vendor import vendor

_DEFAULT_APP = (
    "import openai\n"
    "client = openai.OpenAI()\n"
    "def ask(q):\n"
    "    return client.chat.completions.create(model='gpt', messages=[{'role': 'user'}])\n"
)
_DEFAULT_GITIGNORE = ".venv/\n__pycache__/\n*.pyc\n"


@dataclass(frozen=True)
class HostRepo:
    """A fresh, isolated fake host repository for one skill-proof scenario."""

    fixture_id: str
    root: Path
    extra: dict[str, str] = field(default_factory=dict)


def make_host_repo(
    base: Path,
    fixture_id: str,
    *,
    app_source: str | None = _DEFAULT_APP,
    gitignore: str | None = _DEFAULT_GITIGNORE,
    with_ci: bool = True,
    files: Mapping[str, str] | None = None,
) -> HostRepo:
    """Materialize a disposable host repo under ``base/<fixture_id>/``."""
    root = base / fixture_id / "repo"
    (root / "src").mkdir(parents=True, exist_ok=True)
    if app_source is not None:
        (root / "src" / "app.py").write_text(app_source, encoding="utf-8")
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    if with_ci:
        (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        (root / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    for rel, body in (files or {}).items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    return HostRepo(fixture_id=fixture_id, root=root)


def snapshot(root: Path) -> dict[str, str]:
    """Map every file under ``root`` to a content sha256 (to prove read-only behavior)."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --------------------------------------------------------------------------- #
# AT0 EG-AT0-3 — VendoredHost (a host already vendored into a known authority state)
# --------------------------------------------------------------------------- #


class AuthorityState(enum.StrEnum):
    """Closed set of pre-baked host authority states (alignment plan §3.2 F-1)."""

    FRESH_INFORMATIONAL = "fresh_informational"
    PROPOSED_DATASET = "proposed_dataset"
    WORST_SOURCE_DILUTED = "worst_source_diluted"
    UNCALIBRATED_JUDGE = "uncalibrated_judge"
    HOST_PROMOTED_GATE = "host_promoted_gate"
    HOST_GATE_FAIL = "host_gate_fail"
    HOST_GATE_BLOCKED = "host_gate_blocked"
    COMPARABLE_BASELINE = "comparable_baseline"
    NOT_COMPARABLE_BASELINE = "not_comparable_baseline"


@dataclass(frozen=True)
class CliResult:
    """The observable output of one vendored-runtime invocation."""

    exit_code: int
    stdout: str
    stderr: str
    scorecard: dict[str, Any] | None
    runrecord: dict[str, Any] | None
    report: str | None = None  # rendered report.md text, when the run wrote one


@dataclass(frozen=True)
class VendoredHost:
    """A host repo with a real vendored runtime + host-owned assets in a known state."""

    state: AuthorityState
    root: Path
    run_id: str

    @property
    def evals_dir(self) -> Path:
        return self.root / "evals"

    @property
    def lock_path(self) -> Path:
        return self.evals_dir / "evalglass.lock"

    def snapshot(self) -> dict[str, str]:
        return snapshot(self.root)

    def run(self, args: list[str], *, plugin_present: bool = False) -> CliResult:
        """Run the **vendored** runtime in a clean subprocess (target T2).

        ``PYTHONPATH=evals`` and a scrubbed environment (no ambient credentials);
        optionally sets ``*_PLUGIN_ROOT`` for deletion-invariance proofs.
        """
        result = _run_vendored_cli(self.root, args, plugin_present=plugin_present)
        run_reports = self.evals_dir / "reports" / self.run_id
        sc = _read_json(run_reports / "scorecard.json")
        rr = _read_json(run_reports / "runrecord.json")
        report_md = run_reports / "report.md"
        return CliResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            scorecard=sc,
            runrecord=rr,
            report=report_md.read_text(encoding="utf-8") if report_md.is_file() else None,
        )


def make_vendored_host(
    base: Path,
    fixture_id: str,
    *,
    authority_state: AuthorityState | str,
    with_diluting_trace: bool = False,
) -> VendoredHost:
    """Build a vendored+scaffolded host whose config encodes ``authority_state``.

    Fail-closed: an unknown ``authority_state`` raises; a ``host_promoted_gate``
    request that *also* asks for a diluting trace is self-contradictory (worst-source
    would prevent gating) and raises, so a test can never silently prove the wrong
    thing.
    """
    state = _coerce_state(authority_state)
    if with_diluting_trace and state is not AuthorityState.WORST_SOURCE_DILUTED:
        if state is AuthorityState.HOST_PROMOTED_GATE:
            raise ValueError(
                "contradictory request: host_promoted_gate with a diluting trace can never "
                "gate (worst-source authority resolves to proposed); refusing to build it"
            )
        raise ValueError(
            f"with_diluting_trace is only meaningful for worst_source_diluted, not {state}"
        )

    root = base / fixture_id / "host"
    root.mkdir(parents=True, exist_ok=True)

    # Real vendoring + scaffolding — never a hand-built runtime tree.
    vendor(
        Path(evalglass.__file__).parent,
        root,
        framework_version=evalglass.__version__,
    )
    scaffold(root)

    evals = root / "evals"
    run_id = state.value
    config, files = _state_config(state, run_id)
    for rel, body in files.items():
        dest = evals / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")

    if state in (AuthorityState.COMPARABLE_BASELINE, AuthorityState.NOT_COMPARABLE_BASELINE):
        config = _prepare_baseline(root, state, config)

    (evals / "evalglass.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return VendoredHost(state=state, root=root, run_id=run_id)


# --------------------------------------------------------------------------- #
# Internal config templates and subprocess plumbing
# --------------------------------------------------------------------------- #

_MATCH_ROW = json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n"
_MISMATCH_ROW = json.dumps({"input": "2+2", "output": "5", "reference": "4"}) + "\n"
#: No ``reference`` → a reference metric cannot evaluate it (non_evaluable, never 0.0).
_NO_REFERENCE_ROW = json.dumps({"input": "2+2", "output": "4"}) + "\n"
_JUDGE_ROWS = "".join(
    json.dumps({"input": q, "output": a, "context": {"judge": {"value": v}}}) + "\n"
    for q, a, v in (("q1", "a1", 0.9), ("q2", "a2", 0.7), ("q3", "a3", 0.6))
)
_TRACE_ROW = json.dumps({"trace_id": "t1", "behavior": {"input": "2+2", "output": "4"}}) + "\n"

_EXACT_MATCH = {
    "name": "exact_match",
    "evaluator_ref": "exact_match@1",
    "lens": "reference",
    "score_type": "binary",
    "dataset": "datasets/at0.jsonl",
}
_JUDGE_METRIC = {
    "name": "faithfulness",
    "evaluator_ref": "judge_score@1",
    "lens": "non_reference",
    "score_type": "continuous",
    "score_range": [0, 1],
    "required_evidence": ["judge"],
    "dataset": "datasets/judge.jsonl",
}


def _gating(metric: dict[str, Any], threshold: float) -> dict[str, Any]:
    """A copy of ``metric`` configured to *try* to gate at ``threshold``."""
    return {
        **metric,
        "metric_status": "gating",
        "threshold_approval": "approved",
        "threshold": threshold,
    }


def _state_config(state: AuthorityState, run_id: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Return ``(evalglass.yaml dict, host files to write)`` for ``state``."""
    base_files = {"datasets/at0.jsonl": _MATCH_ROW}
    run = {"run": {"id": run_id}, "output": {"dir": "reports"}}

    if state is AuthorityState.FRESH_INFORMATIONAL:
        cfg = {**run, "datasets": [{"path": "datasets/at0.jsonl"}], "metrics": [dict(_EXACT_MATCH)]}
        return cfg, base_files

    if state is AuthorityState.PROPOSED_DATASET:
        # A reference metric *configured* to gate, but on a proposed dataset → informational.
        cfg = {
            **run,
            "datasets": [{"path": "datasets/at0.jsonl"}],  # status defaults to proposed
            "metrics": [_gating(_EXACT_MATCH, 1.0)],
        }
        return cfg, base_files

    if state is AuthorityState.WORST_SOURCE_DILUTED:
        cfg = {
            **run,
            "datasets": [
                {"path": "datasets/at0.jsonl", "status": "validated", "data_policy": "permitted"}
            ],
            "traces": [{"path": "traces/at0.jsonl", "format": "local"}],  # contributes proposed
            "metrics": [_gating(_EXACT_MATCH, 1.0)],
        }
        return cfg, {**base_files, "traces/at0.jsonl": _TRACE_ROW}

    if state is AuthorityState.UNCALIBRATED_JUDGE:
        # Config *tries* to gate, but no calibration file → judge uncalibrated → informational.
        cfg = {
            **run,
            "datasets": [
                {"path": "datasets/judge.jsonl", "status": "validated", "data_policy": "permitted"}
            ],
            "judge": {"adapter": "fake", "default_value": 0.8},
            "metrics": [_gating(_JUDGE_METRIC, 0.5)],
        }
        return cfg, {"datasets/judge.jsonl": _JUDGE_ROWS}

    if state is AuthorityState.HOST_PROMOTED_GATE:
        # Validated dataset + approved threshold + gating, NO diluting trace → can_gate, pass.
        cfg = {
            **run,
            "datasets": [
                {"path": "datasets/at0.jsonl", "status": "validated", "data_policy": "permitted"}
            ],
            "metrics": [_gating(_EXACT_MATCH, 1.0)],
        }
        return cfg, base_files

    if state is AuthorityState.HOST_GATE_FAIL:
        # Full gating chain, but the (mismatching) output scores 0.0 < threshold → fail (ci=true).
        cfg = {
            **run,
            "datasets": [
                {"path": "datasets/at0.jsonl", "status": "validated", "data_policy": "permitted"}
            ],
            "metrics": [_gating(_EXACT_MATCH, 0.5)],
        }
        return cfg, {"datasets/at0.jsonl": _MISMATCH_ROW}

    if state is AuthorityState.HOST_GATE_BLOCKED:
        # Active gate, but the only example lacks a reference → non_evaluable → no valid
        # measurement → blocked (ci=true). The claim cannot be made honestly, so it is not pass.
        cfg = {
            **run,
            "datasets": [
                {"path": "datasets/at0.jsonl", "status": "validated", "data_policy": "permitted"}
            ],
            "metrics": [_gating(_EXACT_MATCH, 0.5)],
        }
        return cfg, {"datasets/at0.jsonl": _NO_REFERENCE_ROW}

    # Baseline states share the host_promoted-style config; comparability is set up post-hoc.
    cfg = {
        **run,
        "datasets": [
            {"path": "datasets/at0.jsonl", "status": "validated", "data_policy": "permitted"}
        ],
        "metrics": [dict(_EXACT_MATCH)],
    }
    return cfg, base_files


def _prepare_baseline(root: Path, state: AuthorityState, config: dict[str, Any]) -> dict[str, Any]:
    """Run once, promote a baseline, wire comparison (mismatch a dimension for not-comparable)."""
    evals = root / "evals"
    # First run to produce a promotable RunRecord.
    (evals / "evalglass.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    _run_vendored_cli(root, ["run", "--config", "evals/evalglass.yaml"])
    # `baseline update` resolves --from/--to relative to cwd (root); the config's
    # baseline.path resolves relative to the config parent (evals/).
    runrecord = f"evals/reports/{config['run']['id']}/runrecord.json"
    _run_vendored_cli(
        root, ["baseline", "update", "--from", runrecord, "--to", "evals/baselines/base.json"]
    )
    config = {**config, "baseline": {"path": "baselines/base.json", "comparison_requested": True}}
    if state is AuthorityState.NOT_COMPARABLE_BASELINE:
        # Change a gating dimension (the dataset content) so the re-run is not comparable.
        (evals / "datasets" / "at0b.jsonl").write_text(_MISMATCH_ROW, encoding="utf-8")
        metrics = [{**m, "dataset": "datasets/at0b.jsonl"} for m in config["metrics"]]
        config = {
            **config,
            "datasets": [{**config["datasets"][0], "path": "datasets/at0b.jsonl"}],
            "metrics": metrics,
        }
    return config


def _run_vendored_cli(
    root: Path, args: list[str], *, plugin_present: bool = False
) -> subprocess.CompletedProcess[str]:
    """Invoke the vendored ``_evalglass.harness.cli`` in a clean subprocess (no shell)."""
    evals = root / "evals"
    env = {
        "PATH": _safe_path(),
        "PYTHONPATH": str(evals),
        "PYTHONHASHSEED": "0",
        "LC_ALL": "C",
        "HOME": str(root),  # scrub ambient creds/config
    }
    if plugin_present:
        env["CLAUDE_PLUGIN_ROOT"] = str(root / "_fake_plugin")
    return subprocess.run(  # noqa: S603 — fixed argv, shell=False, controlled env
        [sys.executable, "-m", "_evalglass.harness.cli", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _safe_path() -> str:
    """A minimal PATH so python is found but ambient tooling is excluded."""
    py_dir = str(Path(sys.executable).parent) if sys.executable else ""
    return os.pathsep.join(p for p in (py_dir, "/usr/bin", "/bin") if p)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _coerce_state(value: AuthorityState | str) -> AuthorityState:
    if isinstance(value, AuthorityState):
        return value
    try:
        return AuthorityState(value)
    except ValueError:
        allowed = ", ".join(s.value for s in AuthorityState)
        raise ValueError(f"unknown authority_state {value!r}; expected one of: {allowed}") from None
