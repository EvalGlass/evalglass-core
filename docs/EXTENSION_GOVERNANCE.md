# Extension Governance

How to add an optional extension to EvalGlass without manufacturing false confidence
(CLAUDE.md §14/§19; build contract §2/§10/§12; ADRs 0017, 0021).

## Authoring an extension lane

1. Attach through an **existing port** (`TraceSource`, `ScoreSink`, `JudgeModel`,
   `TaskRunner`) — never add a new core port for an optional concern.
2. Declare it as an `ExtensionLane` (ADR 0017): `purpose`, `port`, `module`, `factory`,
   `boundary`, `deletion_rule`, pinned optional dependencies, and prerequisites.
3. Keep the lane **opt-in and deletable**: no required path may import it (the
   `tests/core_isolation/test_lane_boundary.py` guard + `egts verify-deletion` prove it).
   A missing prerequisite raises `MissingPrerequisite` (skip), never fails a required run.
4. A lane returns a `LaneResult` — **never** a `Score`, authority, or verdict.
5. Add a `test-lane <name>` proof with a **negative control** per checker, and a coverage
   row. Prefer stdlib + stubs; a real SDK is a **pinned, isolated extra**, never a required dep.

## Generated / annotated / benchmark evidence

- **Synthetic data** starts `proposed` until a host validates it (it can never self-validate).
- **Annotation output** is an authority input **only** with a host validation record; otherwise
  it is informational.
- **Benchmark results** are threshold *evidence* only; a threshold is approved solely by a host
  `ApprovedThreshold` record (with an approver and rationale) — never derived from a benchmark.

## Generating and reviewing synthetic datasets (EG-H3)

`generate_synthetic_dataset(name, root=…, seed_examples=…, count=…)`
(`evalglass.harness.synthetic`) deterministically expands host-provided seed examples into a
local dataset and a reviewable metadata sidecar:

```text
evals/datasets/generated/<name>.jsonl       # the generated examples
evals/datasets/generated/<name>.meta.json   # {"origin": "synthetic", "status": "proposed", …}
```

The generated dataset is **`proposed`** — never `validated` or `gating`. Generation manufactures
no authority: the metadata records `origin: synthetic` and a generator version so a reviewer can
see exactly what produced it.

**Validating generated data is a separate, host-owned action.** A run can only gate on this data
after a human reviews it and the host promotes it through its own validated-dataset / approved
authority records — exactly as for any other dataset. There is no flag on the generator, and no
`declared_status` passed to the import funnel, that turns generated data into validated data; a
synthetic-origin (`proposed`) dataset always resolves `can_gate=false`.

## Importing and exporting annotations (EG-H3)

`import_annotations(path)` / `export_annotations(records, root=…, name=…)`
(`evalglass.harness.annotation`) read and write host annotation records under
`evals/annotations/*.jsonl`. The annotation **foundation** ships; a rich annotation **UI** does
not. An annotation informs authority **only** when a typed, non-blank host `validation_record`
backs it — a missing, blank, or whitespace record is informational evidence, never a gate. A
**non-string** `validation_record` is malformed input: `import_annotations` rejects it fail-closed
(`AnnotationError`), so it never round-trips as a non-authoritative annotation. The surface exposes
no approve/gate/certify/promote/tune/writeback verb and writes no threshold approval or metric
status: a label can never approve itself.

## Live trace connectors — opt-in, isolated SDK extras (EG-R0 … EG-R5)

The live trace connectors — **Langfuse, Phoenix, and LangSmith** — are governed by ADR 0033
(cross-cutting boundary) and one ADR per provider (0034/0035/0036). The connector *boundary* and
its pinned, isolated optional extras exist (`EG-R0-2`); the connector *adapters* are implemented
per provider in `EG-R1`/`EG-R2`/`EG-R3`, all three prove their normalization scenario, and
`EG-M5C-6` is now **`covered`** (`EG-R4` flipped the row). The lanes stay opt-in at maturity
`planned` (never a `now` default) — being proven is not promotion to a required dependency.

The governing rule is the same one that holds for every lane: **a connector imports evidence,
never authority.** A provider pull yields normalized `TraceEnvelope`/`EvalUnit` input and a
`LaneResult`; it can never make the `Scorecard`, verdict, authority, or CI exit any stronger than
the same run with the connector absent.

Each provider SDK is an **opt-in optional extra**, imported lazily inside the lane path only — never
on a required import path, never in `project.dependencies` (which stays PyYAML-only). Install one
connector's SDK explicitly:

```bash
pip install "evalglass[langfuse-trace]"     # langfuse
pip install "evalglass[phoenix-trace]"      # arize-phoenix-client (the span-reading client)
pip install "evalglass[langsmith-trace]"    # langsmith
# or, in this repo, sync one optional extra:  uv sync --extra <provider>-trace
```

The **planned** Phoenix connector pins the lightweight `arize-phoenix-client`, **not** the full
`arize-phoenix` server package (which would transitively pull openai/anthropic/fastapi); the
dependency-budget guard (`tests/test_dependency_budget.py`) bans the server and any other provider
SDK from the lock. The required CI tier still runs offline (`pytest -m "not live_lane"`); a real
provider pull is a `live_lane`-only smoke test, double-guarded by `EVALGLASS_LIVE_LANES=1` and the
provider's own endpoint/credentials, and is never a merge requirement.

The first **planned** connector — the opt-in `langfuse-trace` lane (EG-R1) — is configured in
`evalglass.yaml`; credentials are env-var **references** read only when the lane is enabled:

```yaml
lanes:
  - name: langfuse-trace
    enabled: true
    data_policy: permitted        # forbidden/missing/unknown refuses egress before any call
    options:
      endpoint: https://<langfuse-host>
      credentials:
        public_key: LANGFUSE_PUBLIC_KEY     # the ENV-VAR NAME, never the secret value
        secret_key: LANGFUSE_SECRET_KEY
```

With the `langfuse-trace` extra absent, an enabled lane is a `MissingPrerequisite` skip (never a
failure); with a non-egress `data_policy` it is blocked before any call. `EG-M5C-6` is `covered`
(EG-R4); the connector lanes remain opt-in at maturity `planned`, so coverage never makes a
provider SDK a required runtime dependency.

## Rejected shortcuts

- A lane that emits a `Score`/verdict/authority (a second verdict path).
- An optional SDK imported by `core` / `harness` / a required adapter.
- A `ScoreSink` that mutates the verdict, authority, or CI exit.
- A vendor/trace object reaching the core, evaluators, `RunRecord`, or `Scorecard`.
- An async lane that **orchestrates** the host instead of observing recorded behavior.
- Synthetic data auto-validated, or a benchmark approving a threshold.

## Review checklist — when a change needs explicit review

A new **port**, a new **runtime dependency** (vs an isolated optional extra), a new
**authority record** type, or any change to verdict/authority resolution must be recorded
as an **ADR** under `adrs/` and reviewed before merge. An optional lane that stays within
an existing port, grants no authority, and is deletable does **not** need a new ADR — only
its lane metadata, proof, and a coverage row.
