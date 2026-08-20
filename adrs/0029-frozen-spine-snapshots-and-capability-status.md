# ADR 0029 — Frozen public-surface snapshots and the capability-status taxonomy

- **Status:** accepted
- **Date:** 2026-06-06
- **Source:** alignment test plan `docs/PRODUCT_ARCHITECTURE_TEST_PLAN.md` §4.3 (FS-SNAP) / §4.4 (FS-UPD) / §1.4; tickets EG-AT1-2, EG-AT1-3
- **Related:** [0008](0008-ci-annotations-exit-class.md) (exit-class taxonomy), [0017](0017-extension-lane-framework.md) (extension-lane framework), [0024](0024-score-subject-identity.md) (additive provenance)

## Context

The v2 alignment work re-frames EvalGlass as an AI quality-control tool and
re-admits former non-goals as opt-in lanes/sinks, and a companion ontology and a
capability-status taxonomy now describe the product. None of that may move the
**trust spine**: the public, machine-readable contracts a reader (or a CI gate)
relies on — the `Scorecard`/`RunRecord` JSON shapes, the `evalglass` CLI surface,
the CI-annotation and report renderings, and every typed enum. A silent change to
one of these is exactly the "false green" the project exists to prevent.

Two ambiguities had to be settled before that spine could be frozen:

1. **How a frozen public surface may legitimately change.** Without a rule, a
   contributor could edit a golden to match drifted product output and call it
   green.
2. **What the capability statuses `now`/`next`/`planned`/`experimental` mean.**
   They look like outcomes, and the docs use the overloaded word "status" for
   several distinct axes; conflating capability status with a run verdict, score
   status, or authority level would be a category error with trust consequences.

## Decision

**1. The public spine is snapshot-frozen, with a deliberate-update gate (no
auto-bless).** The `Scorecard`/`RunRecord` keysets, the parsed CLI verb/flag
surface and its help/description strings, the CI-annotation and report shapes, and
every `Enum` defined under `evalglass.core` / `evalglass.harness` are pinned to
committed goldens under `tests/public_surface/_snapshots/`. Enum and keyset freezes
have **no additive-allow path**. There is **no `--snapshot-update` flag**: changing
a golden means editing the golden and its test literal in the **same reviewed
commit**, where per-slice scan/validator/Codex review inspect the diff. A
spine-defining change (a new `Verdict`/`ScoreStatus`/`Validity`/`AuthorityLevel`
member, a scorecard/runrecord keyset change, a CLI/CI/report contract change)
requires its own spine-touching ADR. Snapshots are introspected into deterministic
shapes (keysets, the parsed surface, the help *strings* — never argparse's
width-wrapped rendered text) so they are byte-stable across the Python matrix.

**2. Capability status is capability, not authority — and orthogonal to every
runtime outcome enum.** `now`/`next`/`planned`/`experimental` describe how mature a
capability is on the roadmap. They are proven **disjoint** from `Verdict`,
`ScoreStatus`, `Validity`, `AuthorityLevel`, and `LaneStatus`. In particular:

- `infrastructure_error` is an `ExitClass` member (exit code 2), **never** a
  `Verdict` (which is exactly `informational/pass/fail/blocked`).
- `AuthorityLevel` is `none/informational/gating`; the resolution **ladder**
  `informational/blocked/can_gate` is `ResolvedAuthority.level` plus the `can_gate`
  / `blocked` booleans — a different *type*, not an enum.

The capability taxonomy is introduced as **test-only data**
(`tests/plugin/status_registry.py`), never imported by `src/**`. Its one product
home is an **additive** `ExtensionLane.maturity` field, deferred to AT3: additive
to `ExtensionLane.to_dict()` (so the AT1 base keyset stays frozen, extended only by
deliberate update), conservative by default (never `now`), and **never read by the
Verdict Engine, the exit mapping, or authority resolution**.

This is a **documentation/test decision**: it changes no product runtime code. AT3
adding `ExtensionLane.maturity` is the only sanctioned additive change to the lane
metadata surface and updates the lane snapshot under this gate.

## Consequences

- A green spine snapshot honestly means "the public contract is unchanged"; any
  change is loud, reviewed, and (for spine-defining changes) ADR-backed.
- Status/ontology work (AT3, AT5) cannot confuse a capability label with a run
  outcome — the disjointness is a test, not a convention.
- The freeze is forward-safe: a newly added enum is discovered and must be frozen,
  and a new public-surface guard or golden auto-joins the FS-META canary set, so the
  contract cannot grow a blind spot.
- If a future product change makes a capability status feed a verdict, exit, or
  authority decision, that reverses this ADR's core separation and requires a new
  ADR superseding this one.
