# ADR 0061 — Immutable run-series index and honest descriptive progression

**Status:** Accepted

## Context

A fixed config run-id writes to `reports/<run-id>/` and, on a rerun, overwrites it. To draw a
"previous run" delta the CLI read that directory's `scorecard.json` *before* the new run replaced it
— a same-run, pre-overwrite read that is neither a stable identity nor a verified prior run, and that
subtracts raw aggregate points (dishonest across non-comparable runs; deprecated by ADR 0059). There
was no durable, immutable identity for a run, no append-only history of a suite, and no way to draw a
descriptive coverage-over-time view without conflating it with a regression claim.

## Decision

Add an immutable **run-series index** alongside the existing run directory, and source descriptive
progression from it — while keeping comparison truth in the typed `ComparisonResult` (0059).

- **Distinct identities.** `series_id` (the stable suite; the host-declared `dashboard.series` or the
  run-id), `run_id` (a run's requested name), a content-digest **`run_key`** (a run's unique
  immutable identity), and the existing promoted `baseline`. `reports/<run-id>/` remains the mutable
  **latest alias** — overwritten on rerun, so existing consumers, goldens, and tooling see the newest
  run byte-for-byte as before.
- **Immutable, integrity-covered snapshot.** Each distinct run is captured under
  `reports/.series/runs/<run_key>/` with the same manifest + completion-marker integrity as the
  result store (the marker is written last; `verify_run` re-checks digests). An identical rerun (same
  `run_key`) is an idempotent no-op — it never overwrites immutable evidence.
- **Append-only, crash-safe, repairable index** (`reports/.series/index.jsonl`). One entry per
  completed run — `run_key`, verdict, `ci_should_fail`, evaluability, example count, baseline id,
  timestamp — written by an atomic whole-file replace (temp → fsync → rename), deduplicated by
  `run_key` so history is never silently overwritten. `series repair` rebuilds the index from the
  verified snapshots on disk, skipping any that fail integrity and inventing nothing.
- **"Previous" is the immediately previous verified run in the series**, selected by walking the
  index and returning the first snapshot that passes integrity verification — never a same-directory
  pre-overwrite file, and never a partial or tampered run.
- **Descriptive progression only.** The dashboard reads the series index for a coverage history
  (evaluability and example count over local runs), explicitly labelled descriptive and carrying no
  regression/improvement language. A regression is only ever the typed paired comparison (0059); the
  promoted baseline and the previous verified run remain distinct comparison purposes.
- **`series` CLI verb** (`list`, `repair`) inspects and rebuilds the index; it promotes no baseline
  and changes no verdict or exit code.

## Consequences

- Rerunning a fixed name no longer erases prior evidence: every distinct run has a unique immutable,
  integrity-covered directory and a durable index entry, while the addressable `reports/<run-id>/`
  stays the latest alias (so no existing artifact path or golden changes).
- The dishonest same-run `previous_values` read is removed from the CLI; descriptive history comes
  from the index and comparison truth from `ComparisonResult`.
- New host-visible artifacts (`reports/.series/`) and a `series` verb are added; the index is
  rebuildable, so a lost or corrupt index is a repair, never a fabrication.
- Baseline verification continues to use the canonical integrity-covered artifacts; the alias is
  never a source of baseline authority.
