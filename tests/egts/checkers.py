"""EGTS checkers — compare declared expectations to real product output.

Checkers are assertion tools, not an alternate EvalGlass engine. They read the
product's emitted :class:`Scorecard` and compare it to a scenario's **declared**
expectation; they never recompute the verdict from metric values
(``tests/CLAUDE.md §4`` / `test_architecture_build_contract.md §9`). A checker
that cannot fail is worthless, so every checker raises :class:`CheckerError` on a
mismatch — and the proof suite exercises that failure path as a negative control.
"""

from __future__ import annotations

import ast
import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from evalglass.core import BaselineState, Scorecard, Verdict
from evalglass.installer import EvalglassLock, VendorManifest

# Maps the product's verdict (the single source) to an EGTS exit class. This is a
# fixed lookup over the *declared* verdict, not a recomputation of it.
_EXIT_CLASS = {
    Verdict.INFORMATIONAL: "zero",
    Verdict.PASS: "zero",
    Verdict.FAIL: "nonzero_fail",
    Verdict.BLOCKED: "nonzero_blocked",
}


class CheckerError(AssertionError):
    """Raised when real product output does not match a declared expectation."""


def check_verdict(scorecard: Scorecard, *, expected: Verdict | str) -> None:
    """Assert the product-emitted verdict equals the declared one (never recomputed).

    Compares by string value, not enum identity: a scenario's declared verdict may be
    a ``tests.egts.scenario.Verdict`` (a distinct StrEnum class) or a plain string.
    """
    actual = scorecard.verdict.verdict
    if str(actual) != str(expected):
        raise CheckerError(
            f"verdict mismatch: product emitted {str(actual)!r}, scenario declared "
            f"{str(expected)!r}"
        )


def check_authority(
    scorecard: Scorecard, metric: str, *, expected_level: str, expected_blocked: bool = False
) -> None:
    """Assert the product-resolved authority for a metric matches the declaration.

    Checks ``level`` **and** ``blocked``: a blocked gate resolves to ``level=gating`` with
    ``blocked=True``, so comparing the level alone would let a policy/baseline-blocked metric
    pass a plain ``gating`` declaration. ``expected_blocked`` defaults to ``False`` (a clean
    informational or gating-and-able metric).
    """
    resolved = scorecard.authority.get(metric)
    if resolved is None:
        raise CheckerError(f"no resolved authority for metric {metric!r}")
    if resolved.level.value != str(expected_level):
        raise CheckerError(
            f"authority-level mismatch for {metric!r}: product {resolved.level.value!r}, "
            f"scenario declared {str(expected_level)!r}"
        )
    if resolved.blocked != expected_blocked:
        raise CheckerError(
            f"authority-blocked mismatch for {metric!r}: product blocked={resolved.blocked}, "
            f"scenario declared {expected_blocked}"
        )


def check_route_fidelity(scorecard: Scorecard, *, probe_metric: str) -> None:
    """Assert a route-fidelity probe scored a clean ``1.0`` — no raw/vendor shape leaked.

    The probe (a host evaluator) scores ``1.0`` only when the evaluator received a normalized
    core ``Example``; a value below ``1.0`` means a raw/vendor trace shape reached an
    evaluator-visible field (``test_architecture_build_contract.md §9`` route fidelity).
    """
    for aggregated in scorecard.metrics:
        if aggregated.metric == probe_metric:
            if aggregated.value is None or aggregated.value < 1.0:
                raise CheckerError(
                    f"route fidelity violated: probe {probe_metric!r} scored {aggregated.value} "
                    "(<1.0 means a raw/vendor trace shape reached the evaluator)"
                )
            return
    raise CheckerError(f"route-fidelity probe {probe_metric!r} not found in scorecard")


def check_report_no_overclaim(report: str, scorecard: Scorecard) -> None:
    """Assert a rendered Markdown report states the Scorecard's verdict and claims no more.

    The report is a *rendering* of typed data: its headline ``**Verdict:** <v>`` must equal the
    Scorecard's verdict, and no other verdict may appear as a headline — an informational run
    must never read as a pass (``test_architecture_build_contract.md §9``; the negative control
    feeds a mutated report and proves this fails).
    """
    actual = scorecard.verdict.verdict
    if f"**Verdict:** {actual.value}" not in report:
        raise CheckerError(f"report does not state the product verdict {actual.value!r}")
    for verdict in Verdict:
        if verdict is not actual and f"**Verdict:** {verdict.value}" in report:
            raise CheckerError(
                f"report overclaims: headline verdict {verdict.value!r} but the Scorecard is "
                f"{actual.value!r}"
            )


def check_ci_no_overclaim(ci_output: str, scorecard: Scorecard) -> None:
    """Assert the ``--format ci`` annotations headline the Scorecard verdict and no stronger one.

    The CI summary states ``verdict=<v>``; it must equal the product verdict and no other verdict
    word may appear as a headline (an informational run must never read as a pass). The negative
    control feeds a mutated CI string and proves this fails.
    """
    actual = scorecard.verdict.verdict
    if f"verdict={actual.value}" not in ci_output:
        raise CheckerError(f"CI output does not state the product verdict {actual.value!r}")
    for verdict in Verdict:
        if verdict is not actual and f"verdict={verdict.value}" in ci_output:
            raise CheckerError(
                f"CI overclaims: headline verdict {verdict.value!r} but the Scorecard is "
                f"{actual.value!r}"
            )
    # The headline ci= token must agree with the payload's ci_should_fail (a fail/blocked run
    # claiming exit-zero would contradict the nonzero exit it actually produces).
    expected_ci = "exit-nonzero" if scorecard.verdict.ci_should_fail else "exit-zero"
    if f"ci={expected_ci}" not in ci_output:
        raise CheckerError(
            f"CI output's ci= token disagrees with ci_should_fail="
            f"{scorecard.verdict.ci_should_fail} (expected ci={expected_ci})"
        )


def check_baseline_state(scorecard: Scorecard, *, expected: str) -> None:
    """Assert the product-resolved baseline comparability state equals the declared one."""
    actual = scorecard.baseline_state.value if scorecard.baseline_state is not None else None
    if actual != str(expected):
        raise CheckerError(
            f"baseline-state mismatch: product {actual!r}, scenario declared {str(expected)!r}"
        )


def check_regression_comparable(scorecard: Scorecard) -> None:
    """Assert a regression claim is backed by a comparable fingerprint; else fail.

    The negative control feeds a non-comparable run, proving EGTS refuses to read a score delta
    as a regression without comparability (``test_architecture_build_contract.md §10``).
    """
    state = scorecard.baseline_state.value if scorecard.baseline_state is not None else None
    if state != BaselineState.COMPARABLE.value:
        raise CheckerError(
            f"regression claim is not comparable: baseline_state={state!r} — a score delta "
            "without a comparable fingerprint is not regression proof"
        )


def check_no_egress(workspace_root: Path, *, marker: str = "CALLED") -> None:
    """Assert no host egress occurred (the specimen marker is absent) — data-policy refusal.

    The negative control runs a permitted source (the marker appears) and this checker fails,
    proving it actually detects egress rather than always passing.
    """
    if (workspace_root / marker).exists():
        raise CheckerError(
            f"egress occurred: marker {marker!r} present under {workspace_root} — forbidden/"
            "undeclared data was sent to the host subprocess"
        )


def check_replay_via_subprocess(workspace_root: Path, *, marker: str = "CALLED") -> None:
    """Assert the replay actually ran the host subprocess (a marker the specimen writes on run).

    Proves route fidelity for the ``TaskRunner``: output produced in-process (bypassing the
    subprocess) leaves no marker, so this checker fails — that is the EGTS-M2-1 negative control.
    """
    if not (workspace_root / marker).exists():
        raise CheckerError(
            f"replay route fidelity violated: host-subprocess marker {marker!r} not found under "
            f"{workspace_root} — output was not produced via the subprocess TaskRunner"
        )


def check_exit_class(scorecard: Scorecard, *, expected: str) -> None:
    """Assert the exit class implied by the product verdict equals the declared one."""
    actual = _EXIT_CLASS[scorecard.verdict.verdict]
    if actual != expected:
        raise CheckerError(
            f"exit-class mismatch: product verdict {scorecard.verdict.verdict.value!r} "
            f"implies {actual!r}, scenario declared {expected!r}"
        )
    # The verdict's ci_should_fail must agree with the exit class — a structural
    # consistency the product guarantees and the checker re-confirms.
    expected_ci = expected != "zero"
    if scorecard.verdict.ci_should_fail != expected_ci:
        raise CheckerError(
            f"ci_should_fail {scorecard.verdict.ci_should_fail} disagrees with exit class "
            f"{expected!r}"
        )


# --- EGTS-M3 skill checkers (compare declared expectations to real skill artifacts) ---

_MANAGED_ROOT = "evals/_evalglass"


def check_no_host_mutation(before: dict[str, str], after: dict[str, str]) -> None:
    """Assert a read-only step (discover/plan/dry-run) left the host byte-identical.

    ``before``/``after`` are path->sha256 snapshots. The negative control mutates the host
    between snapshots and proves this fails (so it really detects mutation).
    """
    if before != after:
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
        raise CheckerError(
            f"host repo was mutated by a read-only step: added={added} "
            f"removed={removed} changed={changed}"
        )


def check_managed_boundary(manifest: VendorManifest) -> None:
    """Assert every manifest-recorded file is a managed file under ``evals/_evalglass/``.

    A manifest that claims a host-owned path (or escapes the managed root) would let an
    upgrade reach host truth — the negative control feeds such a record and proves this fails.
    """
    if manifest.managed_root != _MANAGED_ROOT:
        raise CheckerError(
            f"manifest managed_root is {manifest.managed_root!r}, not {_MANAGED_ROOT!r}"
        )
    for rec in manifest.files:
        if not rec.path.startswith(f"{_MANAGED_ROOT}/") or ".." in rec.path.split("/"):
            raise CheckerError(f"manifest records a non-managed/escaping path: {rec.path!r}")


def check_manifest_checksums(host_root: Path, manifest: VendorManifest) -> None:
    """Assert each recorded managed file exists on disk with the recorded sha256."""
    for rec in manifest.files:
        p = host_root / rec.path
        if not p.is_file():
            raise CheckerError(f"manifest file missing on disk: {rec.path}")
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != rec.sha256:
            raise CheckerError(f"manifest checksum mismatch for {rec.path}: recorded {rec.sha256}")


def check_lock_records_runtime(lock: EvalglassLock) -> None:
    """Assert the lock records the framework version and the three runtime features."""
    if not lock.framework_version:
        raise CheckerError("lock has no framework_version")
    missing = {"core", "harness", "adapters"} - set(lock.installed_features)
    if missing:
        raise CheckerError(f"lock missing runtime features: {sorted(missing)}")


def check_host_file_unchanged(path: Path, before: bytes) -> None:
    """Assert a host-owned file was not overwritten/deleted by vendoring or scaffolding."""
    if not path.is_file():
        raise CheckerError(f"host-owned file was deleted: {path}")
    if path.read_bytes() != before:
        raise CheckerError(f"host-owned file was overwritten: {path}")


def check_no_silent_authority(scorecard: Scorecard) -> None:
    """Assert a fresh-scaffold run grants no gating authority — every metric is informational.

    The first run of a scaffolded host must be ``informational`` with no active gate (no
    silent authority). The negative control feeds a scorecard with a gating metric and proves
    this fails.
    """
    if scorecard.verdict.verdict is not Verdict.INFORMATIONAL:
        raise CheckerError(
            f"fresh-scaffold run is {scorecard.verdict.verdict.value!r}, not informational — "
            "a scaffolded install must not gate"
        )
    for metric, resolved in scorecard.authority.items():
        if resolved.can_gate or resolved.blocked:
            raise CheckerError(f"scaffolded metric {metric!r} resolved to an active gate")


# --- EGTS-M4 judge checkers --------------------------------------------------

#: Provider SDKs and network clients that must never appear in a required-tier import. The live
#: trace-connector SDKs (``langfuse`` / ``langsmith`` and ``phoenix``, the top-level module of
#: ``arize-phoenix-client``) join the set in EG-R0-5: their optional extras exist, but a *static*
#: import of one anywhere in the required closure is a leak — the connectors import lazily by name.
_FORBIDDEN_IMPORTS = frozenset(
    {
        "openai",
        "anthropic",
        "cohere",
        "litellm",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "http",
        "langfuse",
        "phoenix",
        "langsmith",
    }
)


def check_no_provider_sdk(
    src_root: Path, packages: Sequence[str], *, allow: Sequence[str] = ()
) -> None:
    """Assert no required-tier module imports a provider SDK or a network client (hermetic tier).

    The required judge tier uses fake evidence only — no live model, no provider SDK, no network.
    ``allow`` names *relative paths* exempt from the rule (the opt-in live lane), matched exactly
    so a same-named required module is never skipped. The negative control feeds a module that
    imports a provider SDK and proves this fails.
    """
    allowed = set(allow)
    offenders: list[str] = []
    for pkg in packages:
        for py in (src_root / pkg).rglob("*.py"):
            if py.relative_to(src_root).as_posix() in allowed:
                continue
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [node.module or ""]
                for module in modules:
                    if module.split(".", 1)[0] in _FORBIDDEN_IMPORTS:
                        offenders.append(f"{py.name}: {module}")
    if offenders:
        raise CheckerError(
            f"required tier imports a provider SDK / network client (non-hermetic): {offenders}"
        )


def check_judge_ledger(
    ledger: Sequence[tuple[str, str]], *, expected: Sequence[tuple[str, str]]
) -> None:
    """Assert the judge was called for exactly the expected ``(example_id, metric)`` calls.

    Multiplicity-aware (a ``Counter``, not a set): a forbidden-policy example must be **absent**,
    and a duplicate/extra provider call is caught. The negative control declares an expectation
    that omits a real call and proves this fails.
    """
    if Counter(ledger) != Counter(expected):
        raise CheckerError(
            f"judge ledger mismatch: judge was called for {sorted(ledger)}, expected "
            f"{sorted(expected)}"
        )


# --- EGTS-M5 optional-lane checkers ------------------------------------------

#: Authority-bearing attributes a lane result must never expose — a lane informs, never decides.
_FORBIDDEN_LANE_ATTRS = ("score", "scores", "verdict", "authority", "ci_should_fail")


def check_lane_grants_no_authority(result: object) -> None:
    """Assert a lane result is *evidence, not authority*: no score/verdict/authority field.

    A lane attaches through an existing port and yields a ``LaneResult`` (a ``status`` plus
    diagnostics). If a lane result grew a ``verdict``/``authority``/``score`` field it would be a
    second, hidden verdict path — the negative control feeds such an object and proves this fails.
    """
    present = [attr for attr in _FORBIDDEN_LANE_ATTRS if hasattr(result, attr)]
    if present:
        raise CheckerError(f"lane result exposes authority-bearing field(s): {present}")
    if not hasattr(result, "status"):
        raise CheckerError("lane result has no 'status' — it is not a LaneResult")


def check_lane_metadata(lane: object) -> None:
    """Assert a lane declares purpose, boundary, deletion rule, port, and a dotted module path.

    A lane with undeclared boundary/deletion-rule is an integration hazard (no stated isolation or
    removal contract); the negative control feeds an under-declared lane and proves this fails.
    """
    for field_name in ("name", "purpose", "boundary", "deletion_rule", "module", "factory"):
        value = getattr(lane, field_name, None)
        if not isinstance(value, str) or not value.strip():
            raise CheckerError(f"lane metadata field {field_name!r} is undeclared/empty: {value!r}")
    module = getattr(lane, "module", "")
    if "." not in module:
        raise CheckerError(f"lane.module is not a dotted import path: {module!r}")
    if getattr(lane, "port", None) is None:
        raise CheckerError("lane metadata has no 'port' (which runtime seam it attaches to)")


def check_lane_imports_isolated(
    src_root: Path, lane_module: str, *, packages: Sequence[str] = ("core", "harness", "adapters")
) -> None:
    """Assert no required-tier module statically imports the optional lane (``hermetic_import``).

    A lane is opt-in and deletable: only its own file and the lazy ``resolve()`` may load it. A
    static ``import evalglass...lane`` in ``core``/``harness``/required ``adapters`` would break
    deletion and could pull an optional SDK into the required graph. The negative control adds such
    an import and proves this fails.
    """
    lane_file = (src_root.parent / (lane_module.replace(".", "/") + ".py")).resolve()
    offenders: list[str] = []
    for pkg in packages:
        for py in (src_root / pkg).rglob("*.py"):
            if py.resolve() == lane_file:
                continue
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                static_import = isinstance(node, ast.Import) and any(
                    a.name == lane_module for a in node.names
                )
                static_from = (
                    isinstance(node, ast.ImportFrom) and (node.module or "") == lane_module
                )
                if static_import or static_from:
                    offenders.append(py.name)
    if offenders:
        raise CheckerError(
            f"required tier statically imports optional lane {lane_module!r}: {offenders}"
        )


#: Open-convention (OTel/OpenInference) attribute keys that must never appear in the core — if a
#: core module names one, it has begun to branch on a vendor trace shape (build contract §6).
_CONVENTION_TOKENS = (
    "llm.input_messages",
    "llm.output_messages",
    "llm.model_name",
    "gen_ai.",
    "openinference",
    "opentelemetry",
)


def check_core_no_convention_branching(src_root: Path) -> None:
    """Assert the effect-free core references no OpenTelemetry/OpenInference convention token.

    The open-convention mapping lives wholly in the ``TraceSource`` adapter; the core sees only the
    normalized ``TraceEnvelope``. A convention key (e.g. ``llm.input_messages``) appearing in a core
    string literal means the core has started to branch on a vendor type. Scans string constants in
    ``<src_root>/core/**``. The negative control feeds such a core file and proves this fails.
    """
    core_root = src_root / "core"
    offenders: list[str] = []
    for py in core_root.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                offenders.extend(
                    f"{py.name}: {tok}" for tok in _CONVENTION_TOKENS if tok in node.value
                )
    if offenders:
        raise CheckerError(f"core references open-convention token(s) — vendor leak: {offenders}")


def check_envelopes_no_vendor_leak(
    envelopes: Sequence[object], *, forbidden_keys: Sequence[str]
) -> None:
    """Assert no produced ``TraceEnvelope`` carries a vendor-internal key (boundary isolation).

    A backend adapter must normalize spans at its boundary; a vendor wrapper key (e.g.
    ``_backend_internal``) appearing in an envelope's ``behavior``/``metadata``/``provenance`` means
    a vendor object crossed into the core-visible path. The negative control feeds such an envelope
    and proves this fails (EGTS-M5-3; build contract §6 trace rule).
    """
    bad = set(forbidden_keys)
    offenders: list[str] = []
    for env in envelopes:
        for section in ("behavior", "metadata", "provenance"):
            mapping = getattr(env, section, None)
            if isinstance(mapping, Mapping):
                offenders.extend(f"{section}.{k}" for k in mapping if k in bad)
    if offenders:
        raise CheckerError(f"vendor object leaked past the trace boundary: {offenders}")


def check_scorecard_unchanged(scorecard: Scorecard, before: Mapping[str, object]) -> None:
    """Assert a ScoreSink export left the Scorecard byte-identical — it consumes, never mutates.

    The export sink must treat the Scorecard as immutable: its serialized form after ``export`` must
    equal the form captured before. The negative control mutates the scorecard and proves this fails
    (EGTS-M5-4; build contract §9 — Scorecard JSON is the source of truth).
    """
    after = scorecard.to_dict()
    if after != dict(before):
        raise CheckerError(
            "scorecard changed across export — a sink must consume it, not mutate it"
        )


#: Orchestration primitives an observation-only lane must never use — it reads recorded behavior,
#: it does not run/drive the host (build contract §6/§9; EG-M5-5).
_ORCHESTRATION_IMPORTS = frozenset({"subprocess", "asyncio", "multiprocessing"})
_ORCHESTRATION_CALLS = frozenset({"system", "popen", "run", "spawn", "fork", "exec", "execv"})


def check_lane_observation_only(src_root: Path, lane_module: str) -> None:
    """Assert an async/observation lane only *reads* recorded behavior — it never orchestrates.

    The lane module must not import an orchestration primitive (``subprocess``/``asyncio``/
    ``multiprocessing``) or call ``os.system``/``Popen``/``run``/``exec``/``fork`` — that would mean
    it drives the host rather than observing a recording. The negative control feeds a lane that
    orchestrates and proves this fails (EGTS-M5-5).
    """
    lane_file = (src_root.parent / (lane_module.replace(".", "/") + ".py")).resolve()
    if not lane_file.is_file():
        raise CheckerError(f"observation lane module not found: {lane_file}")
    tree = ast.parse(lane_file.read_text(encoding="utf-8"), filename=str(lane_file))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                f"import {a.name}"
                for a in node.names
                if a.name.split(".")[0] in _ORCHESTRATION_IMPORTS
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").split(".")[0] in _ORCHESTRATION_IMPORTS
        ):
            offenders.append(f"from {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _ORCHESTRATION_CALLS:
                offenders.append(f"call {name}()")
    if offenders:
        raise CheckerError(f"observation lane {lane_module!r} orchestrates the host: {offenders}")


def check_scores_carry_subject_identity(runrecord: Mapping[str, object]) -> None:
    """Artifact-shape gate (F1 / ADR 0024): every individual score in a real
    ``runrecord.json`` carries explicit ``example_id`` and ``unit_id`` so a reader
    can group by call by *field*, never by list order. Fails closed if any score
    lacks identity — that is the regression ``view --by-call`` must not ship over.
    """
    scores = runrecord.get("scores")
    if not isinstance(scores, list) or not scores:
        raise CheckerError("runrecord has no scores to shape-check")
    missing: list[int] = []
    for i, score in enumerate(scores):
        if not isinstance(score, Mapping) or "example_id" not in score or "unit_id" not in score:
            missing.append(i)
    if missing:
        raise CheckerError(
            f"runrecord.json scores missing subject identity at indices {missing}; "
            "view --by-call must not be enabled until real output carries the field"
        )


def group_scores_by_subject(
    runrecord: Mapping[str, object],
) -> dict[str, list[Mapping[str, object]]]:
    """The fail-closed by-call reader contract: group scores by explicit subject
    identity. Raises (never guesses by list order) if a score lacks ``example_id``.
    """
    check_scores_carry_subject_identity(runrecord)
    scores = runrecord["scores"]
    assert isinstance(scores, list)  # narrowed by the checker above
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for score in scores:
        assert isinstance(score, Mapping)
        grouped.setdefault(str(score["example_id"]), []).append(score)
    return grouped
