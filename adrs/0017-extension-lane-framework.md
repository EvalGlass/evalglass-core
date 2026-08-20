# ADR 0017 — Extension-lane framework and optional-dependency policy

- **Status:** accepted
- **Date:** 2026-05-31
- **Generalizes:** ADR 0016 (optional live judge lane)

## Context

M5 adds optional integrations (trace conformance, trace backends, score-sink
exports, richer units, governance). Each must attach through an **existing** port,
preserve the typed contracts, grant no authority, and be **deletable without
changing required-tier behavior** (`CLAUDE.md §14/§19`; build contract §6/§8;
EG-M5 epic). ADR 0016 set the per-lane shape for the live judge; M5a needs a small
shared framework so every lane declares the same metadata and the required tier
provably imports none of them. The framework itself must be required-tier-safe —
it cannot import a concrete lane or it would defeat the deletion guarantee.

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Framework home | `src/evalglass/harness/lanes.py` — `ExtensionLane`, `LaneResult`, `LaneStatus`, `LanePort`, `MissingPrerequisite`, `LaneRegistry`, `built_in_lanes()` | Stdlib + effect-free core (`Diagnostic`) only; imports **no** concrete lane. |
| Lane metadata | `ExtensionLane` declares `name`, `purpose`, `port`, `module`, `factory`, `boundary`, `deletion_rule`, `optional_dependencies`, `prerequisites` | JSON-compatible, fail-closed `from_dict` (schema-open input → `LaneError`). |
| Discovery | `LaneRegistry` lists lanes from **metadata only**; the concrete module is imported solely by `resolve()` via `importlib.import_module`, on demand | A static `import` of a lane in a required path is therefore detectable and forbidden. |
| Concrete lanes | live under `adapters/` (where `judge_live` already lives), each opt-in and deletable | No `lanes/` package churn; consistent with M4. |
| `MissingPrerequisite` | one canonical class in the framework; `judge_live` re-exports it | Absent prereq → **skip/block**, never a failed required path; the attach seam catches one class. |
| Lane result | `LaneResult` (`ran`/`skipped`/`blocked` + diagnostics + report) carries **no** score/verdict/authority field | A lane informs; it never decides — no second verdict path. |
| Optional dependencies | each lane needing a real third-party dep declares a **pinned, isolated** extra in `[project.optional-dependencies]`, never in `dependencies` | M5a lanes are stdlib/stub → extras are declared but carry no pin yet; no `uv.lock` relock of the required set. |
| Proof surface | `egts test-lane <name>` runs one lane's proof; lanes are excluded from every required suite; `egts verify-deletion` (S5) proves removal leaves required proof green | New EGTS checkers: `optional_lane`, `hermetic_import`. |

## Consequences

- Every optional lane shares one declaration and one "skip on missing prerequisite"
  contract; the framework can attach a lane through its existing port without the
  required import graph ever naming a lane.
- Deleting a lane file (or omitting its extra) cannot break the required tier — the
  import-boundary guard (`tests/core_isolation/test_lane_boundary.py`) and
  `egts verify-deletion` prove it, generalizing the ADR 0016 deletion guard across
  all lanes.
- A lane grants no authority and adds no verdict path; reach grows without trust
  growing.
- No new **required** dependency enters the repo in M5a; future real-vendor lanes
  add only their own isolated extra.

## Alternatives considered

- **A separate top-level `src/evalglass/lanes/` package.** Rejected — it duplicates
  the adapter home, and `judge_live` already lives in `adapters/`; a single
  framework module + adapter lanes is less churn and keeps the boundary guard simple.
- **A registry that eagerly imports each lane to validate it.** Rejected — eager
  import defeats deletability and would pull optional dependencies into the required
  graph; metadata-only discovery with lazy `resolve()` is the whole point.
- **Let lanes raise their own `MissingPrerequisite`.** Rejected — divergent classes
  would force the attach seam to catch a moving target; one canonical class (re-exported
  for back-compat) keeps "skip, don't fail" uniform.
- **Allow a lane to emit a `Score`/verdict directly.** Rejected — that is a second
  verdict path; lanes return `LaneResult` evidence only (build contract §2 non-negotiable 1).
