# ADR 0031 — Runner-attach seam, `lanes:` config, and the `RunRecord.lane_results` side channel

- **Status:** accepted
- **Date:** 2026-06-06
- **Source:** final product plan `docs/FINAL_PRODUCT_IMPLEMENTATION_PLAN.md` §0.1–0.2 / §M6-S0; tickets EG-H0-1 … EG-H0-7 (`jira_tickets_alignment_foundation_hermetic.xlsx`)
- **Related:** [0017](0017-extension-lane-framework.md) (extension-lane framework), [0029](0029-frozen-spine-snapshots-and-capability-status.md) (frozen spine + capability status), [0008](0008-ci-annotations-exit-class.md) (exit-class taxonomy)

## Context

EvalGlass has a complete extension-lane *framework* (ADR 0017): `ExtensionLane`
metadata, the `LaneResult` shape, a metadata-only `LaneRegistry`, the four lane
ports, and four registered lanes — but **no lane executes during a real run**.
`harness/runner.py::run_config` reads sources, runs the effect-free core, and
returns a `RunRecord` without ever referencing `built_in_lanes()`. The alignment
tests pin this as the *current truth* (`tests/harness/test_lane_attach.py`) and
froze the *post-seam contract* (`tests/harness/test_lane_attach_seam.py`): a lane
result may sit on the `RunRecord` as a side channel, but it must never reach the
verdict, authority, Scorecard, CI, or report.

To let a host actually run a configured lane (e.g. export a Scorecard, read a
trace backend) we must add the missing plumbing. That plumbing touches three
public surfaces — config, the core `RunRecord` contract, and the runner — so it is
recorded here before it lands.

The hard constraint: a lane is **evidence, never authority**. Wiring lanes into the
run must not create a second, hidden path to a verdict. The frozen spine
(`Scorecard`/`VerdictPayload` shape, the verdict/authority matrix, CI exits) must
stay byte-identical for any run, with or without lanes configured.

## Decision

**1. An opt-in `lanes:` config block, fail-closed.** `RuntimeConfig` gains
`lanes: list[LaneConfig] = []`. A `LaneConfig` carries `name` (validated against
`built_in_lanes()`), `enabled` (default **false** — listing a lane never runs it),
`data_policy`, and a lane-specific `options` mapping. An unknown lane name, an
unknown top-level lane key, or a non-mapping `options` is a `SetupError` (setup
diagnostic, exit class 2), never a score. An absent `lanes:` key means no lane
runs — existing configs are unaffected.

**2. One additive `RunRecord.lane_results` side channel — the sole spine
extension.** `RunRecord` gains `lane_results: list[dict]` (default empty). It is
the canonical record of configured-lane outcomes (`ran`/`skipped`/`blocked` +
diagnostics). It is **additive and optional**: `to_dict()` emits it only when
non-empty, `from_dict()` defaults a missing value to `[]` (old artifacts parse
unchanged), and it lands in the **optional** set of the frozen
`runrecord_keys.json` snapshot via the deliberate-update gate (ADR 0029). It lives
on `RunRecord`, **not** on `Scorecard` — the verdict-bearing summary stays
lane-free. This is the one sanctioned change to the otherwise-frozen `RunRecord`
keyset; ADR 0029's "no additive-allow path" for keysets is satisfied by this
explicit, reviewed extension.

**3. The seam attaches lanes around the core, never into it.**
`run_config` dispatches configured, enabled lanes by port:
- **Post-core `SCORE_SINK`** lanes run *after* `run_evaluation`, consuming the
  immutable `Scorecard` read-only and returning a `LaneResult`.
- **Pre-core `TRACE_SOURCE`** lanes (and the `JUDGE_MODEL` live-judge lane)
  dispatch through their existing ports *before* the core, normalizing evidence —
  exactly as the built-in dataset/trace routes already do.

Each lane call is wrapped so a `MissingPrerequisite` becomes a `skipped`
`LaneResult` and any lane failure becomes a `blocked` `LaneResult` + diagnostic —
a lane can never raise into the run or fabricate a score. Every `LaneResult` is
folded **only** into `RunRecord.lane_results`; it is never passed to
`run_evaluation`, `resolve_authority`, `VerdictPayload`, or `Scorecard`
construction. The AST dataflow guard (`test_lane_attach_seam.py`) proves this for
the real `runner.py`: a lane-derived value reaching any verdict/authority/Scorecard
sink fails the build.

**4. `lane_results.json` is a derived convenience, never a source of truth.** If
the harness emits a `lane_results.json` sidecar it is byte-derived from
`RunRecord.lane_results`. The Markdown report, terminal report, CI annotations,
`scorecard.json`, and the exit code are derived **only** from the `Scorecard` and
the core verdict payload — never from lane results.

**5. Deletion and migration stay invariant.** Deleting a lane's adapter file
leaves the required tier green (the registry resolves lazily). A run's
`VerdictPayload` and `scorecard.json` are byte-identical whether or not any lane is
configured — a configured lane adds rows to `lane_results` and nothing else.
Existing host repos keep working: configs without `lanes:` run as before, and old
`RunRecord` JSON without `lane_results` parses.

## Consequences

- A configured lane can finally run in a real run, while the spine stays provably
  lane-free: the verdict, authority, reports, CI, and exits cannot move because a
  lane ran, skipped, or blocked.
- The one spine extension (`RunRecord.lane_results`) is loud, reviewed, snapshot-
  pinned, and dataflow-guarded — it is not a blank cheque for further keyset growth.
- The frozen current-truth canary
  (`test_lane_attach.py::test_current_truth_built_in_lanes_absent_from_runner`)
  legitimately flips to the post-seam assertion in the same slice that wires the
  seam (EG-H0-4/EG-H0-7), and its FS-META manifest entry updates with it (ADR 0029
  deliberate-update gate). This is the sanctioned staged transition (FS-DEL-3).
- If a future change ever let a lane result influence the verdict, authority, exit,
  or report headline, that reverses this ADR's core separation and requires a new
  ADR superseding it.
