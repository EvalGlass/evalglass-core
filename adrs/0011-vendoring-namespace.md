# ADR 0011 — Vendoring namespace and runtime invocation

- **Status:** accepted
- **Date:** 2026-05-31

## Context

The skill vendors `src/evalglass/{core,harness,adapters}` into a host repo. The
installed host layout (architecture §10/§11; build contract §11) is:

```text
evals/_evalglass/
  core/
  harness/
  adapters/
```

so the top-level package on disk is `_evalglass`. But the framework source uses
**129 absolute intra-package imports** (`from evalglass.core import …`, including
lazy in-function imports in `cli.py` / `runner.py`) and **zero** relative imports.
Two hard requirements (P13 boundary, P2/P14 reproducibility):

- The vendored runtime must run **standalone** — no installed `evalglass`, no
  `skill/`, no coding agent.
- It must **not silently bind a stray installed `evalglass`**, which would mask a
  vendoring bug and break the "you are running this pinned, vendored copy"
  guarantee.

A related latent bug surfaces here: `runner.py` sources the provenance framework
version via `importlib.metadata.version("evalglass")` with a
`"evalglass@0.0.0"` fallback. A standalone vendored copy has no installed dist, so
host provenance would always read `evalglass@0.0.0` — losing the pinned version.

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Namespace | **Rewrite `import` / `from evalglass…` statements to `_evalglass`** at vendor time (option A) | AST / import-statement-scoped; rewrites the lazy in-function imports too; **never** touches string literals, comments, or the `version(...)` argument. |
| Layout | `evals/_evalglass/{core,harness,adapters}` | The exact architecture §10/§11 layout. |
| Invocation | `python -m _evalglass.harness.cli run --config evals/evalglass.yaml` | Namespace-isolated — cannot resolve to an installed `evalglass`. |
| Skill | **Not vendored** | Only `core/harness/adapters` are copied (ADR 0010). |
| Version | The vendor step **bakes the pinned framework version** into the vendored top `__init__.py`; the harness reads `evalglass.__version__` first (fallback `importlib.metadata`) | Else host provenance reads `evalglass@0.0.0`. This is the one small, deliberate harness change in M3. |
| Proof | EGTS-M3-4 runs the vendored CLI in a **clean subprocess** (framework `src/` off `sys.path`, `skill/` removed); S2 tests assert the transform left zero residual `evalglass.` imports and corrupted no string / version arg | The transform is mechanical, so it is pinned by tests, not trust. |

Rationale: **vendoring/relocation is an adoption-layer concern owned by the skill —
the core must not be restyled to make itself vendorable.** Keeping the source in
its natural absolute-import form and letting the *skill* own the rewrite respects
the dependency direction, is the industry-standard approach (`pip._vendor`,
`setuptools._vendor` rewrite imports), and keeps the manifest honest about the
bytes it actually runs (EGTS proves the transform is faithful).

## Consequences

- The vendored runtime is namespace-isolated: `python -m _evalglass.harness.cli`
  can never accidentally import an installed framework copy, so a vendoring or
  pinning bug fails loudly rather than being masked.
- The `vendor-manifest.json` checksums describe the bytes the host runs; host-patch
  detection (on-disk checksum ≠ recorded) is exact (ADR 0012).
- A new import-statement transform is maintained in the skill; any future source
  change that adds an absolute `evalglass.` import is caught by the S2 / EGTS-M3-4
  clean-subprocess tests, not silently shipped.
- Host provenance fingerprints carry the real pinned framework version.

## Alternatives considered

- **(D) Relative-import source refactor.** Convert the 129 absolute intra-package
  imports to relative, then vendor **byte-identical** as `_evalglass` (no transform;
  strongest provenance — vendored checksums equal source bytes; trivial literal
  re-vendor diff). The principled alternative, rejected as the default because it
  contorts already-shipped, EGTS-proven M0–M2 code for an adoption-layer
  convenience (a dependency-direction inversion) and forces re-proving those
  milestones. It is the right call only if byte-identical vendoring is valued above
  a core-pristine source.
- **(B) Keep the package name `evalglass`; vendor under `evals/_evalglass/evalglass/`
  + a `sys.path` launcher.** Byte-identical, but the package name stays `evalglass`,
  so `python -m evalglass.harness.cli` can resolve to an *installed* copy depending
  on path order — weak namespace isolation that can silently mask a vendoring bug —
  and the layout deviates from §10. Rejected.
