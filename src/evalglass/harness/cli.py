"""The ``evalglass`` command-line entrypoint (EG-M1-1 / EG-M1-5).

argparse (stdlib — ADR 0005; CLAUDE.md §15) drives the local runner: load config → run →
persist typed artifacts → render report → exit from the core verdict. The CLI owns no
evaluation meaning and never computes a verdict. Exit class comes from ``harness.exits``,
derived only from the core ``VerdictPayload`` (ADR 0005/0008): ``0`` pass/informational,
``1`` fail/blocked, ``2`` infrastructure/setup error. ``--format ci`` renders GitHub CI
annotations instead of the terminal summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from evalglass.harness.errors import SetupError, setup_diagnostic
from evalglass.harness.loader import load_config

if TYPE_CHECKING:
    from evalglass.core import RunRecord
    from evalglass.harness.config import RuntimeConfig
    from evalglass.harness.dashboard import DashboardMeta

_CONFIG_HELP = "Path to evalglass.yaml."


def _source_label(cfg: object) -> str:
    """A human label for the run's trace/data source, for the report header (not authority)."""
    lanes = [ln.name for ln in getattr(cfg, "lanes", []) if getattr(ln, "enabled", False)]
    if lanes:
        return ", ".join(f"{name} lane" for name in lanes)
    if getattr(cfg, "traces", None):
        return "local traces"
    if getattr(cfg, "datasets", None):
        return "local dataset"
    return "no source"


def _dashboard_meta(cfg: RuntimeConfig, run_id: str) -> DashboardMeta:
    """Run labels for the dashboard hero — host-declared where present, else derived."""
    from evalglass.harness.dashboard import DashboardMeta

    dash = getattr(cfg, "dashboard", None)
    application = getattr(dash, "application", None) or ""
    source_label = getattr(dash, "source_label", None) or _source_label(cfg)
    return DashboardMeta(run_id=run_id, application=application, source_label=source_label)


def _emit_reports(
    run_dir: Path,
    record: RunRecord,
    cfg: RuntimeConfig,
    *,
    history: list[dict[str, Any]] | None = None,
) -> None:
    """Write the run's renderings: ``report.md`` + the typed ``dashboard.json`` + ``report.html``.

    The Markdown report and the HTML dashboard both render from typed facts (the Markdown sink from
    the Scorecard, the HTML from the ``evalglass.dashboard/1`` projection) and neither recomputes a
    verdict/authority/delta. The same-run raw ``previous_values`` HTML delta is gone (D4): change is
    read only from the typed ``Scorecard.comparison`` the projection carries.
    """
    from evalglass.harness.dashboard import project_run
    from evalglass.harness.report import MarkdownScoreSink

    (run_dir / "report.md").write_text(
        MarkdownScoreSink().render(record.scorecard), encoding="utf-8"
    )
    projection = project_run(
        record.scorecard,
        record,
        config=cfg,
        meta=_dashboard_meta(cfg, record.run_id),
        history=history,
    )
    (run_dir / "dashboard.json").write_text(
        json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (run_dir / "report.html").write_text(_render_html(projection, record, cfg), encoding="utf-8")


def _render_html(projection: dict[str, Any], record: RunRecord, cfg: RuntimeConfig) -> str:
    """Render the HTML report — the diagnostic dashboard by default; legacy for one release."""
    if os.environ.get("EVALGLASS_HTML_RENDERER") == "legacy":
        from evalglass.harness.report_html_legacy import HtmlScoreSink as LegacyHtmlScoreSink
        from evalglass.harness.report_html_legacy import ReportMeta

        return LegacyHtmlScoreSink(
            meta=ReportMeta(run_id=record.run_id, source=_source_label(cfg))
        ).render(record.scorecard)
    from evalglass.harness.report_html import render_dashboard

    return render_dashboard(projection)


def _now() -> str:
    """A UTC timestamp for the run-series index (a Harness effect; the core has no clock)."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def _record_series(base_dir: Path, record: RunRecord, cfg: RuntimeConfig) -> list[dict[str, Any]]:
    """Record the run in its series index and return the descriptive history for the dashboard.

    The series is the host-declared ``dashboard.series`` or the run id; the returned history feeds
    the dashboard's descriptive progression only — never a regression claim (that stays D4).
    """
    from evalglass.harness.series import record_run

    dash = getattr(cfg, "dashboard", None)
    series_id = getattr(dash, "series", None) or record.run_id
    return record_run(base_dir, record, series_id=series_id, generated_at=_now())


def _series(args: argparse.Namespace) -> int:
    """Inspect (`list`) or rebuild (`repair`) the run-series index — never changing a verdict."""
    from evalglass.harness.exits import ExitClass, exit_code
    from evalglass.harness.series import read_index, repair_index

    base_dir = Path(args.out).resolve()
    if not base_dir.is_dir():
        print(f"setup error [io_error]: reports directory not found: {base_dir}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    if args.series_command == "repair":
        entries = repair_index(base_dir)
        print(f"repaired: {len(entries)} verified run(s) recovered into the series index.")
        return 0
    entries = read_index(base_dir)
    if not entries:
        print("no runs recorded in the series index.")
        return 0
    for entry in entries:
        print(
            f"  {entry.series_id}/{entry.run_id} [{entry.run_key}] "
            f"verdict={entry.verdict} examples={entry.examples}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalglass", description="EvalGlass local evaluation runner."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run an evaluation from a local config.")
    run.add_argument("--config", required=True, help=_CONFIG_HELP)
    run.add_argument(
        "--out", default=None, help="Output directory for artifacts (overrides config)."
    )
    run.add_argument(
        "--format",
        choices=["terminal", "ci"],
        default="terminal",
        help="Stdout rendering: 'terminal' summary (default) or 'ci' GitHub annotations.",
    )
    run.add_argument(
        "--debug",
        action="store_true",
        help="On a setup/infra error, also print the original traceback (off by default).",
    )
    run.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Resolve and write the evaluation plan (run-plan.json) without running any effect.",
    )

    # Side-effect-free preflight: resolve the same plan a run would, and report per-metric
    # applicability, planned request counts, egress decisions, and gate readiness — before egress.
    preflight = sub.add_parser(
        "preflight",
        help="Preflight a config: population, planned requests, and gate readiness (no effects).",
        description=(
            "Resolve the evaluation plan a `run` would execute and report, per metric, the "
            "selector-matched/eligible population, planned judge and replay request counts, the "
            "egress decision, and whether a gate would be authorized if measured. Performs NO "
            "provider call, judge call, task replay, baseline promotion, or authority mutation. "
            "Missing credentials are named by environment variable only; cost is an upper-bound "
            "estimate, never an invoice. Writes the same data to run-plan.json."
        ),
    )
    preflight.add_argument("--config", required=True, help=_CONFIG_HELP)
    preflight.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Stdout rendering: 'text' summary (default) or 'json' (the run-plan projection).",
    )
    preflight.add_argument(
        "--out", default=None, help="Output directory for run-plan.json (overrides config)."
    )

    # Baseline promotion is an explicit, separate command — never a side effect of `run`.
    baseline = sub.add_parser("baseline", help="Manage host-owned baselines.")
    baseline_sub = baseline.add_subparsers(dest="baseline_command", required=True)
    update = baseline_sub.add_parser("update", help="Promote a run record as a baseline.")
    update.add_argument("--from", dest="from_path", required=True, help="Path to a runrecord.json.")
    update.add_argument("--to", dest="to_path", required=True, help="Baseline file path to write.")

    # Continuous drift watch: one drift check per invocation (cron/CI-driven, never a daemon).
    watch = sub.add_parser(
        "watch",
        help="Run one drift check (run → compare to baseline → record), then exit (cron).",
        description=(
            "Run ONE evaluation, compare it to the configured baseline, and record drift, then "
            "exit. Not a resident daemon: 'continuous' means scheduled re-invocation (a nightly "
            "cron or CI job). Drift is explanatory evidence, not a verdict: a regression is "
            "reported only when the runs are comparable and the paired interval clears zero; a "
            "delta inside the interval is within-noise; not-comparable runs are said plainly, "
            "never 'no regression'. Drift adds NO exit class (the exit code still derives only "
            "from the run's verdict) and the watcher NEVER promotes the baseline."
        ),
    )
    watch.add_argument("--config", required=True, help=_CONFIG_HELP)
    watch.add_argument(
        "--out", default=None, help="Output directory for artifacts (overrides config)."
    )

    # Read-only inspection of a run's metrics from its typed artifact. Never re-runs, never gates.
    view = sub.add_parser(
        "view", help="Inspect a run's metrics from its typed artifact (read-only)."
    )
    view.add_argument("--record", required=True, help="Path to a runrecord.json.")
    view.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Stdout rendering: 'text' table (default) or 'json' explorer view.",
    )

    # Inspect or repair the immutable run-series index (EG-DX-E4). Read-only listing and a
    # rebuild-from-verified-snapshots repair; neither promotes a baseline nor changes a verdict.
    series = sub.add_parser(
        "series", help="Inspect or repair the run-series index (immutable history)."
    )
    series_sub = series.add_subparsers(dest="series_command", required=True)
    series_list = series_sub.add_parser("list", help="List the run-series index entries.")
    series_list.add_argument(
        "--out", required=True, help="The reports directory that holds the .series index."
    )
    series_repair = series_sub.add_parser(
        "repair", help="Rebuild the series index from the run snapshots on disk."
    )
    series_repair.add_argument(
        "--out", required=True, help="The reports directory that holds the .series index."
    )

    # Scaffold a shipped, opt-in trace connector lane into evalglass.yaml (EG-P2; ADR 0046). This
    # writes config only — no provider SDK, no live call. The subsequent `run` does the pull.
    connect = sub.add_parser(
        "connect",
        help="Import a local trace export, or scaffold an opt-in live connector, into the config.",
        description=(
            "Bring recorded behavior into a run, two ways. `--from <export>` imports a LOCAL "
            "exported trace file as a first-class traces: route — no credentials and no provider "
            "SDK; the export is validated before the config is touched, so a malformed or empty "
            "file writes nothing. `--live <platform>` enables a shipped, opt-in, deletable trace "
            "connector lane (Langfuse / Phoenix / LangSmith): it writes config only — no provider "
            "SDK is imported and no live call is made here; the following `run` pulls the traces, "
            "and needs the '<platform>-trace' extra installed plus env-var creds. Credentials "
            "are passed as environment-variable NAMES (references), never literal secrets. A "
            "connector's data policy defaults to 'unknown' so egress is refused until you "
            "consciously set it to 'permitted'. Either way the traces are PROPOSED evidence: a "
            "connected run stays informational and cannot gate. All relative paths resolve against "
            "the --config directory. A missing config is refused unless you pass --init (which "
            "writes a conservative informational config). Deleting a connector leaves the required "
            "tier unchanged."
        ),
    )
    connect.add_argument(
        "--from",
        dest="from_path",
        default=None,
        metavar="EXPORT",
        help="Path to a local exported trace file to import as a traces: route.",
    )
    connect.add_argument(
        "--format",
        dest="import_format",
        choices=["local", "opentelemetry", "openinference"],
        default="local",
        help="Shape of the --from export (default: local).",
    )
    connect.add_argument(
        "--init",
        action="store_true",
        help="Create a conservative informational config if --config does not exist.",
    )
    connect.add_argument(
        "--live",
        metavar="PLATFORM",
        default=None,
        help="Scaffold a live tracing connector lane: langfuse, phoenix, or langsmith.",
    )
    connect.add_argument(
        "--config", default="evalglass.yaml", help="Path to the evalglass.yaml to edit."
    )
    connect.add_argument(
        "--endpoint", default=None, help="Provider host/endpoint URL (not a secret)."
    )
    connect.add_argument("--project", default=None, help="Optional provider project/name.")
    connect.add_argument(
        "--credentials",
        nargs="*",
        default=None,
        metavar="NAME=ENV_VAR",
        help="Credential ENV-VAR NAME refs, e.g. public_key=LANGFUSE_PUBLIC_KEY (not a secret).",
    )
    connect.add_argument(
        "--data-policy",
        dest="data_policy",
        default="unknown",
        help="Pull data policy; defaults to 'unknown' (fail-closed — set 'permitted' to pull).",
    )
    connect.add_argument(
        "--limit", type=int, default=None, help="Optional cap on the number of traces pulled."
    )

    # Declarative evidence assembly (Epic B): join local sources into an Example JSONL + a manifest.
    assemble = sub.add_parser(
        "assemble",
        help="Assemble evaluation examples from declared sources and joins (host-owned dataset).",
        description=(
            "Run a declarative evidence_pipeline: join local dataset/trace exports (and opt-in "
            "argv snapshot commands) by declared keys and cardinality, project fields preserving "
            "behavior layers, and write an Example JSONL plus a lineage/digest manifest beside it. "
            "The output routes through the ordinary dataset contract — there is no second scoring "
            "engine, and nothing here grants authority. Deterministic: unchanged inputs and config "
            "reproduce a byte-identical output and digest."
        ),
    )
    assemble.add_argument("--config", required=True, help="Path to the evidence_pipeline config.")
    assemble.add_argument("--out", required=True, help="Output Example JSONL path to write.")
    return parser


def _write_run_plan(base_dir: Path, payload: dict[str, object]) -> Path:
    """Write the versioned, self-verifying (fingerprinted) ``run-plan.json`` artifact."""
    base_dir.mkdir(parents=True, exist_ok=True)
    target = base_dir / "run-plan.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _dry_run(config_path: str, out: str | None) -> int:
    # Resolve the plan a real run would execute and write run-plan.json — no effect, no verdict.
    from evalglass.harness.exits import ExitClass, exit_code
    from evalglass.harness.runner import preflight

    root = Path(config_path).resolve().parent
    try:
        cfg = load_config(config_path)
        pf = preflight(cfg, root, run_lanes=False)
        target = _write_run_plan(root / (out or cfg.output_dir), pf.plan.to_dict())
    except SetupError as exc:
        diag = exc.diagnostic
        print(f"setup error [{diag.code}]: {diag.message}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    except OSError as exc:
        print(f"setup error [io_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    plan = pf.plan
    print(
        f"dry-run: resolved plan for {cfg.run_id} — {len(plan.judge_effects())} judge + "
        f"{len(plan.replay_effects())} replay effect(s) planned; no effect executed."
    )
    print(f"run-plan: {target}")
    # A completed dry-run of a valid config exits zero; it never emits a quality verdict.
    return 0


def _preflight(config_path: str, fmt: str, out: str | None) -> int:
    from evalglass.harness.exits import ExitClass, exit_code
    from evalglass.harness.preflight import report_preflight

    root = Path(config_path).resolve().parent
    try:
        cfg = load_config(config_path)
        report = report_preflight(cfg, root)
        target = _write_run_plan(root / (out or cfg.output_dir), report.to_dict())
    except SetupError as exc:
        diag = exc.diagnostic
        print(f"setup error [{diag.code}]: {diag.message}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    except OSError as exc:
        print(f"setup error [io_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    print(
        json.dumps(report.to_dict(), indent=2, sort_keys=True)
        if fmt == "json"
        else report.render_text()
    )
    print(f"run-plan: {target}")
    # Preflight is a report, not a gate: a completed analysis always exits zero (issues are shown).
    return 0


def _run(
    config_path: str, out: str | None, fmt: str, debug: bool = False, dry_run: bool = False
) -> int:
    # Imported lazily: the runner/result-store pull in the adapters, which import
    # evalglass.harness.config — importing them at module top (cli is loaded by the harness
    # package __init__) would create an import cycle.
    if dry_run:
        return _dry_run(config_path, out)
    from evalglass.adapters.ci_annotation_sink import CiAnnotationSink
    from evalglass.adapters.result_store_fs import FilesystemResultStore
    from evalglass.harness.exits import ExitClass, exit_class_for, exit_code
    from evalglass.harness.report import TerminalScoreSink
    from evalglass.harness.runner import run_config

    root = Path(config_path).resolve().parent
    try:
        cfg = load_config(config_path)
        record = run_config(cfg, root)
        base_dir = root / (out or cfg.output_dir)
        paths = FilesystemResultStore(base_dir).persist(record)
        history = _record_series(base_dir, record, cfg)
        _emit_reports(paths.run_dir, record, cfg, history=history)
        # Optional convenience sidecar, byte-derived from the canonical RunRecord.lane_results
        # (ADR 0031): written only when lanes ran, and never a source of truth — the report, CI,
        # scorecard.json, and exit code are derived only from the Scorecard.
        lane_results = record.to_dict().get("lane_results")
        if lane_results:
            (paths.run_dir / "lane_results.json").write_text(
                json.dumps(lane_results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except SetupError as exc:
        diag = exc.diagnostic
        print(f"setup error [{diag.code}]: {diag.message}", file=sys.stderr)
        # Debugging stays behind an explicit flag: a crashed host evaluator (EG-NR-5) is reported
        # as a typed setup error by default; --debug also prints the original chained traceback.
        if debug and exc.__cause__ is not None:
            import traceback

            traceback.print_exception(
                type(exc.__cause__), exc.__cause__, exc.__cause__.__traceback__, file=sys.stderr
            )
        # An infrastructure/setup failure before a core verdict is its own exit class, never a
        # fabricated quality fail (build contract §8; ADR 0008).
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    except OSError as exc:
        # Filesystem failures (unwritable output, --out points at a file, ...) are setup/infra
        # errors, never a host quality failure.
        print(f"setup error [io_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)

    sink = CiAnnotationSink() if fmt == "ci" else TerminalScoreSink()
    print(sink.render(record.scorecard))
    print(f"artifacts: {paths.run_dir}")
    # Exit derives only from the core verdict payload (build contract §8; CLAUDE.md §11).
    return exit_code(exit_class_for(record.scorecard))


def _watch(config_path: str, out: str | None) -> int:
    # One drift check per invocation (cron/CI-driven): run → compare to baseline → record → exit.
    # Drift is explanatory evidence; the exit code still derives ONLY from the run's verdict, and
    # the baseline is never written here (that stays the explicit `baseline update` act).
    from dataclasses import replace

    from evalglass.adapters.result_store_fs import FilesystemResultStore
    from evalglass.harness.baseline import load_run_record
    from evalglass.harness.drift import (
        Comparability,
        evaluate_drift,
        persist_drift,
        with_drift_diagnostic,
    )
    from evalglass.harness.exits import ExitClass, exit_class_for, exit_code
    from evalglass.harness.report import TerminalScoreSink
    from evalglass.harness.runner import run_config

    root = Path(config_path).resolve().parent
    try:
        cfg = load_config(config_path)
        # `watch` exists to compare against the baseline, so it requests comparability whenever a
        # baseline is configured (the core still decides comparable/not_comparable honestly from the
        # fingerprints). This only enables the comparison; it never relaxes the licensing rule.
        if cfg.baseline_path and not cfg.comparison_requested:
            cfg = replace(cfg, comparison_requested=True)
        record = run_config(cfg, root)
        # A configured baseline that exists is loaded for the item-paired comparison; a configured
        # baseline whose FILE is absent (a legitimate first run, before any promotion) is a graceful
        # missing-baseline, not an error. A present-but-malformed baseline is a setup error.
        baseline = None
        if cfg.baseline_path:
            baseline_file = root / cfg.baseline_path
            if baseline_file.exists():
                baseline = load_run_record(baseline_file)
        directions = {m.spec.name: m.spec.direction for m in cfg.metrics}
        drift = evaluate_drift(record, baseline, directions)
        # Surface drift as an explanatory diagnostic AFTER the verdict — the verdict, authority,
        # scores, and exit are unchanged (mirrors route diagnostics; drift adds no verdict path).
        record = replace(record, scorecard=with_drift_diagnostic(record.scorecard, drift))
        base_dir = root / (out or cfg.output_dir)
        paths = FilesystemResultStore(base_dir).persist(record)
        persist_drift(drift, paths.run_dir)
        history = _record_series(base_dir, record, cfg)
        _emit_reports(paths.run_dir, record, cfg, history=history)
    except SetupError as exc:
        diag = exc.diagnostic
        print(f"setup error [{diag.code}]: {diag.message}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    except OSError as exc:
        print(f"setup error [io_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)

    print(TerminalScoreSink().render(record.scorecard))
    # Honest drift wording: never "quality is fine", never "no drift" when not comparable.
    regressed = drift.regressions()
    if drift.comparability is Comparability.MISSING_BASELINE:
        print("drift: no baseline to compare against (missing_baseline) — drift not evaluated.")
    elif drift.comparability is Comparability.NOT_COMPARABLE:
        print(
            "drift: the current run is not comparable to the baseline — no regression claim made."
        )
    elif regressed:
        print(f"drift: comparable regression on {', '.join(regressed)} (see drift.json).")
    else:
        print("drift: no comparable regression found (this does not mean quality is fine).")
    print(f"artifacts: {paths.run_dir}")
    # Exit derives ONLY from the run's verdict — drift never adds an exit class (EG-P4-3).
    return exit_code(exit_class_for(record.scorecard))


def _canonical_runrecord(from_path: str, run_dir: Path) -> Path:
    """The manifest-verified ``runrecord.json`` in ``run_dir``, requiring ``--from`` to name it.

    ``verify_run`` digests the manifest-listed runrecord.json; promotion must adopt exactly that
    file, not a sibling the manifest never covered (e.g. a modified ``forged.json`` dropped beside a
    valid run) — otherwise verification would pass while an unverified record is promoted (EG-NR-4).
    """
    canonical = run_dir / "runrecord.json"
    if Path(from_path).resolve() != canonical.resolve():
        raise SetupError(
            setup_diagnostic(
                "baseline_source_not_canonical",
                f"--from must be the verified runrecord.json of a complete run, not "
                f"{Path(from_path).name!r}",
                location=from_path,
            )
        )
    return canonical


def _baseline_update(from_path: str, to_path: str) -> int:
    # Promote an existing run record as a baseline. Explicit and separate from `run` — an
    # ordinary evaluation never writes a baseline (build contract §12; ADR 0009). Promotion is an
    # authority-bearing act, so it adopts only a COMPLETE, integrity-verified run: the run directory
    # containing --from must carry a valid manifest + completion marker whose digests still match
    # (EG-NR-4). A copied, hand-assembled, partial, or tampered record fails closed at exit 2 — a
    # downstream tool that trusts a baseline can never be handed a preflighted one.
    from evalglass.adapters.result_store_fs import verify_run
    from evalglass.harness.baseline import load_run_record, promote
    from evalglass.harness.exits import ExitClass, exit_code

    try:
        run_dir = Path(from_path).parent
        verify_run(run_dir)
        record = load_run_record(_canonical_runrecord(from_path, run_dir))
        promote(record, Path(to_path))
    except SetupError as exc:
        diag = exc.diagnostic
        print(f"setup error [{diag.code}]: {diag.message}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    except OSError as exc:
        print(f"setup error [io_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    print(f"baseline updated: {to_path} (from run {record.run_id!r})")
    return 0


def _view(record_path: str, fmt: str) -> int:
    # Read-only: load the typed RunRecord through the explorer (a view, not a meaning engine), echo
    # the stored verdict, and render the per-subject metric rows. It writes nothing and never
    # re-derives a verdict — a successful inspection always exits 0; a malformed/unreadable artifact
    # is an infrastructure error, never a fabricated quality fail.
    from evalglass.harness.exits import ExitClass, exit_code
    from evalglass.harness.explorer import ExplorerError, explore

    try:
        view = explore(Path(record_path))
    except ExplorerError as exc:
        print(f"setup error [explorer_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    if fmt == "json":
        print(json.dumps(view.to_dict(), indent=2, sort_keys=True))
        return 0
    print(f"run: {view.run_id}")
    print(f"verdict: {view.verdict} (ci_should_fail={str(view.ci_should_fail).lower()})")
    if view.baseline_state is not None:
        print(f"baseline: {view.baseline_state}")
    for subject in view.subjects:
        unit = f" / unit {subject.unit_id}" if subject.unit_id else ""
        print(f"\nsubject {subject.example_id}{unit}")
        for row in subject.rows:
            validity = "" if row.validity == "valid" else f", {row.validity}"
            # Surface the trust context for the value: authority level + reasons, and any diagnostic
            # codes — so a number is never shown without whether it can be trusted.
            trust = ""
            if row.authority is not None:
                reasons = ", ".join(row.authority.get("reasons", []))
                trust = f" [authority: {row.authority.get('level')}"
                trust += f" — {reasons}]" if reasons else "]"
            diags = f" diagnostics: {', '.join(row.diagnostics)}" if row.diagnostics else ""
            print(f"  {row.metric}: {row.display_value} ({row.status}{validity}){trust}{diags}")
    for note in view.diagnostics:
        print(f"note: {note}")
    return 0


def _parse_credentials(pairs: Sequence[str] | None) -> dict[str, str] | None:
    """Parse ``NAME=ENV_VAR`` CLI pairs into a credential mapping (None ⇒ use platform defaults).

    Only the shape is checked here (``NAME=REF``); whether ``REF`` is a valid env-var *name* (and
    not a literal secret) is enforced fail-closed by the connector boundary in
    ``connector_lane_config``.
    """
    if pairs is None:
        return None
    creds: dict[str, str] = {}
    for item in pairs:
        name, sep, ref = item.partition("=")
        if not sep or not name.strip() or not ref.strip():
            raise ValueError(
                f"credential {item!r} must be NAME=ENV_VAR (e.g. public_key=MY_ENV_VAR)"
            )
        creds[name.strip()] = ref.strip()
    return creds


def _assemble(config_path: str, out: str) -> int:
    from evalglass.harness.assembly import run_assembly
    from evalglass.harness.exits import ExitClass, exit_code

    try:
        manifest = run_assembly(Path(config_path), Path(out))
    except SetupError as exc:
        diag = exc.diagnostic
        print(f"setup error [{diag.code}]: {diag.message}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    except OSError as exc:
        print(f"setup error [io_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    print(f"assembled: {manifest.output_count} example(s) -> {out} [{manifest.completeness.value}]")
    if manifest.diagnostics:
        print(f"  {len(manifest.diagnostics)} join diagnostic(s) — the assembly is partial.")
    print(f"  manifest: {out}.manifest.json (config {manifest.config_digest[:19]}...)")
    # Assembly is a host-owned build step, not a gate: a completed assembly always exits zero.
    return 0


def _connect(args: argparse.Namespace) -> int:
    # Exactly one mode: a local import (--from) or a live-lane scaffold (--live). The verb imports
    # the connect module lazily (like `_run`) so the CLI import stays adapter-free.
    from evalglass.harness.exits import ExitClass, exit_code

    if bool(args.from_path) == bool(args.live):
        print(
            "setup error [connect_error]: pass exactly one of --from <export> (local import) "
            "or --live <platform> (live scaffold).",
            file=sys.stderr,
        )
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    if args.from_path:
        return _connect_import(args)
    return _connect_live(args)


def _connect_import(args: argparse.Namespace) -> int:
    from evalglass.harness.connect import ConnectError, apply_import
    from evalglass.harness.exits import ExitClass, exit_code

    try:
        summary = apply_import(args.config, args.from_path, fmt=args.import_format, init=args.init)
    except (ConnectError, ValueError) as exc:
        print(f"setup error [connect_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    except OSError as exc:
        print(f"setup error [io_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    verb = "added" if summary["created"] else "updated"
    print(
        f"imported: {verb} traces route {summary['path']!r} ({summary['format']}, "
        f"{summary['records']} unit(s)) in {args.config}"
    )
    print(
        "  these traces are PROPOSED evidence — the run stays informational and cannot gate until "
        "you validate host-owned gold."
    )
    print(f"  next: `evalglass preflight --config {args.config}` to see the planned population.")
    return 0


def _connect_live(args: argparse.Namespace) -> int:
    # Scaffold-then-run (ADR 0046): write/enable the connector lane, no live call here. The verb
    # imports the connect module lazily (like `_run`) so cli import stays adapter-free.
    from evalglass.harness.connect import ConnectError, apply_connect
    from evalglass.harness.exits import ExitClass, exit_code

    try:
        credentials = _parse_credentials(args.credentials)
        lane = apply_connect(
            args.config,
            args.live,
            init=args.init,
            endpoint=args.endpoint,
            project=args.project,
            credentials=credentials,
            data_policy=args.data_policy,
            limit=args.limit,
        )
    except (ConnectError, ValueError) as exc:
        # A malformed platform / literal secret / bad pair is a setup error — never a verdict, and
        # (for a rejected literal) the boundary error never echoes the secret value.
        print(f"setup error [connect_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    except OSError as exc:
        print(f"setup error [io_error]: {exc}", file=sys.stderr)
        return exit_code(ExitClass.INFRASTRUCTURE_ERROR)
    print(f"connected: enabled optional lane {lane['name']!r} in {args.config}")
    print(
        f"  data_policy={lane['data_policy']} — a live pull yields PROPOSED data, so this "
        "opt-in lane stays informational and cannot gate."
    )
    print(
        f"  next: install the '{args.live}-trace' extra, export the credential env vars, set "
        "data_policy: permitted once you've reviewed egress, then run "
        f"`evalglass run --config {args.config}`."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse args and dispatch. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    # argparse (required subparsers) guarantees one of these; it exits 2 on a missing/unknown one.
    if args.command == "baseline":
        return _baseline_update(args.from_path, args.to_path)
    if args.command == "view":
        return _view(args.record, args.format)
    if args.command == "connect":
        return _connect(args)
    if args.command == "assemble":
        return _assemble(args.config, args.out)
    if args.command == "series":
        return _series(args)
    if args.command == "watch":
        return _watch(args.config, args.out)
    if args.command == "preflight":
        return _preflight(args.config, args.format, args.out)
    return _run(args.config, args.out, args.format, args.debug, args.dry_run)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
