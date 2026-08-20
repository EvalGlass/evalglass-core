# Plugin implementation lessons (P0–P2) — read before F1 / A1 / P3

Hard-won lessons from building the EvalGlass Claude Code plugin: **P0** (skeleton, PR #113), **P1**
(core verbs + first-run journey, #114), **P2** (release hygiene #115, README #116, examples/demo/docs
#117). Decision: ADR 0022 (plugin packaging & delivery) and ADR 0023 (Codex second runtime). These
complement `CLAUDE.md` §21–23 (the framework build-loop lessons) — read both.

> **Historical record.** These lessons were captured during the P0–P3 build. The forward-looking
> epics they mention — **F1** (score-subject identity → `view --by-call`), **A1** (authoring tier +
> `connect --live`), and **P3** (Codex second runtime) — have since landed; read §9 as the shipped
> plan-of-record, not open work.

> Meta-lesson: **packaging slices touched zero `src/evalglass` code** except a version bump. The
> only framework change ahead is **F1**, and it must follow the *framework* loop, not the packaging
> loop. Keep the two disciplines distinct.

---

## 1. The per-slice cycle that worked (copy this)

One slice = one PR (`CLAUDE.md` §23). For every plugin slice:

```sh
# 1. Isolate off the framework-only main (NEVER work on docs/site-v2 — see §2).
git worktree add /tmp/eg-<slice> -b feat/plugin-<slice> origin/main
VENV=/Users/laurentiu/virtualenvs/evalglass/evalglass/.venv/bin   # the editable install lives here

# 2. Author + tests-first in the worktree, then the local gates (the REAL gate — CI excludes some):
PYTHONPATH=/tmp/eg-<slice>/src $VENV/python -m pytest tests/plugin -q
$VENV/ruff check tests/plugin && $VENV/ruff format --check tests/plugin && $VENV/mypy tests/plugin
claude plugin validate . --strict          # the `claude` binary is installed locally — use it
PYTHONPATH=/tmp/eg-<slice>/src $VENV/python -m pytest -q   # full suite — catch framework regressions

# 3. Commit (convention below, NO AI attribution), push, PR to main, poll CI, squash-merge.
gh pr create --base main ... ; gh pr checks <N> ; gh pr merge <N> --squash

# 4. Clean up (the gh --delete-branch step fails in a worktree — do it manually):
git worktree remove /tmp/eg-<slice> --force ; git worktree prune ; git branch -D feat/plugin-<slice>
git fetch origin main
```

- **Commit/PR title:** `<type>(plugin): <summary> (P<n>, EGP-P<n>-<k>)`. Types used: `feat` (new
  surface), `chore` (release hygiene), `docs` (README/examples/docs). **No `Co-Authored-By` / "Generated
  with…"** — the project overrides the default attribution (`CLAUDE.md` §22; memory).
- **Slice big epics early.** P0 (35 pts) and P1 (61 pts) went as single cohesive epic-PRs and were
  *stretches*; **P2 (37 pts) as three slices A/B/C reviewed and merged far more cleanly.** F1/A1/P3:
  slice from the start.

## 2. Worktree isolation is mandatory here (not optional)

The day-to-day checkout sits on branch **`docs/site-v2` with uncommitted site work**, and `main`'s
HEAD is `#112 "extract the website into evalglass-site"` — i.e. **the framework repo is now
framework-only; the website is a separate repo.** Consequences:

- **Never commit plugin work on `docs/site-v2`** (it would carry the site branch's commits into the
  PR and pollute it). Always branch off `origin/main` in a throwaway worktree.
- Stray untracked P0/P1 copies linger in the `docs/site-v2` checkout — they are already on `main`;
  ignore them, don't re-commit them.
- `gh pr merge --delete-branch` errors with *"'main' is already checked out"* because the worktree
  holds the branch — the **merge still succeeds**; just clean the worktree up by hand afterward.

## 3. Claude Code plugin mechanics — verified facts & gotchas

- **The umbrella is a SKILL, not a command file.** claude-seo ships `/seo <verb>` as a skill named
  `seo` with **no `commands/` dir at all**; we mirrored it with `skills/evalglass/SKILL.md`. Don't
  assume a `commands/*.md` umbrella works — the exact `/evalglass <verb>` token is still a P0
  acceptance probe (transcript), with namespaced `/evalglass:run` as the documented fallback.
- **`.claude-plugin/` holds only `plugin.json` + `marketplace.json`.** All component dirs
  (`skills/`, `hooks/`, …) live at the **plugin root**. Declaring components in `plugin.json` while a
  marketplace entry also declares them triggers a "conflicting manifests" failure — so we declare
  none and rely on auto-discovery.
- **`claude plugin validate . --strict` is the manifest gate and runs locally** (binary at
  `/opt/homebrew/bin/claude`, v2.1.160). Run it every slice — it's instant and catches manifest drift.
- **Two/three execution targets, never mixed** (P1): integration-time acts run the **bundled**
  framework via `bin/evalglass-launch` (`PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/src python -m
  evalglass.installer …`) because a marketplace-only user has **no pip-installed `evalglass-install`**;
  host evaluation runs the **vendored** `_evalglass` (`PYTHONPATH=evals …`); the quickstart demo runs
  the bundled example. Nothing the plugin writes into a host may reference the plugin.

## 4. Ground the framework before "implementing" a verb

P1 looked like 61 points of new code; it needed **zero `src/` changes**. Before writing anything:
`grep`/read the existing skill + `scaffold.py` + `discovery.py` + harness CLI. We found `scaffold.py`
**already** emits `evals/evalglass.yaml`, the **CI workflow**, a sample dataset, an empty
`authority.json`, and the README checklist; `discover` already returns candidate call sites; the run
invocation already matches. So most "implement `/evalglass <verb>`" tickets are **skill prose + the
launcher + tests**, not new capability. Assume the framework (M0–M5 complete) already does the work.

## 5. CI & quality-gate gotchas (these cost real time)

- **SonarCloud is a SEPARATE check from "all required checks."** PR #114 had "all required checks:
  pass" while **"SonarCloud Code Analysis: fail"** (`new_security_rating` E). When a Sonar check
  fails, query the exact condition — don't guess:
  ```
  mcp__sonarqube__get_project_quality_gate_status(projectKey="Syntelesis-Lab-evalglass", pullRequest=N)
  mcp__sonarqube__search_sonar_issues_in_projects(projects=[...], pullRequestId="N", impactSoftwareQualities=["SECURITY"])
  ```
- **Never use `/tmp` literals in tests** → `python:S5443` (publicly-writable dir), a Sonar CRITICAL
  that fails the gate. Use pytest's private `tmp_path`. (This bit us on a *deliberately-bad* path arg.)
- The test matrix is **py3.12 + py3.13**; CI also runs ruff, mypy strict, bandit, core-isolation,
  pip-audit, trivy, trufflehog, licensecheck. Local `ruff`/`mypy`/`pytest` must be green first.
- CI takes ~2–3 min; poll with a bounded loop (`gh pr checks <N>`), break when `pending=0`.

## 6. Subprocess-in-tests pitfalls (all hit during P1)

- **`$?` after a pipe is the *pipe's* exit, not the command's.** `launcher … | head` showed `exit=0`
  while the launcher exited 2. Verify exit codes without a pipe (`cmd >/dev/null 2>&1; echo $?`).
- Ruff on test subprocess calls: use an **absolute/`sys.executable` path** (avoids `S607` partial
  path — don't do `["sh", path]`, do `[str(path)]` for an executable), pass **`check=False`** (avoids
  `PLW1510`), and split compound `assert a and b` (`PT018`). `tests/**` ignores `S101/ANN/D/ARG` only.
- Reading repo-under-test files vs importing: the editable install points at the **main checkout's**
  `src`, so its `__version__` lags a worktree bump. **Version/contract tests must read the
  worktree's files** (`REPO_ROOT`-relative), not `import evalglass`.

## 7. Honesty applied to our own delivery (the doctrine, in code)

- **The honesty-audit gate works — it caught its own draft.** In P2 it flagged a `RELEASE_CHECKLIST`
  line containing "trusted by" (inside a *prohibition*: "no … trusted-by logos"). The fix is the same
  as the framework's scan-gate verdict-literal lesson: **a content gate must let prose NAME the
  forbidden phrase in a prohibition** — exempt negation lines (`never|no |not |fabricated|❌|…`).
- **Generate real artifacts; never fabricate.** The README's Scorecard sample was produced by running
  the bundled quickstart; committed example scorecards are real runs and must carry
  `informational`/`blocked` verdicts (the gate asserts it). A gate with no artifact in scope reports
  **"not exercised," not PASS**.
- **scan-gate / validator-gate have empty jurisdiction over pure packaging** (they hunt
  effects-in-core / verdict duplication / authority manufacture in *product* code). Report them **not
  exercised** for packaging slices — don't fake a PASS. They DO apply to F1 (core) and A1 (optional lane).
- Things you **cannot** honestly produce headless: a real demo **GIF/cast** (ship the reproducible
  *script*; media is a maintainer step with `asciinema`/`agg`), and a **cross-repo** reference re-home
  (the agent-reference lives in the separate `evalglass-site` repo).

## 8. Version & release

- Five version-bearing locations: `plugin.json` · `pyproject.toml [project].version` ·
  `src/evalglass/__init__.py:__version__` · `CITATION.cff` · **git tag**. `tests/plugin/
  test_version_alignment.py` enforces the four in-repo ones; the tag is release-time.
- **Before bumping the version, `grep` the literal across `tests/` + snapshots.** Bumping 0.0.0→0.1.0
  was safe (only `pyproject`/`__init__` + one test *arg* referenced it; no snapshot pinned it).
- **Tagging `v0.1.0` + the GitHub Release is a maintainer go/no-go**, not an agent action — it's
  outward-facing. The gates (strict-validate, honesty-audit, version alignment) are in
  `docs/plugin/RELEASE_CHECKLIST.md`.

---

## 9. Epic-specific guidance

### F1 — Score subject identity (the ONE framework change)
- This is **framework work, not packaging.** It changes the public `Score` contract → write the **ADR
  first**, follow the **M-series loop** (`CLAUDE.md` §23: tests-first → **scan-gate + validator-gate
  (now IN jurisdiction)** → review → PR → CI), keep it **JSON-compatible**, and **update the public
  surface / serialization snapshots deliberately** (M0 has them — adding `example_id`/`unit_id` to
  `Score` changes `to_dict`/`from_dict` output). Add EGTS coverage.
- It is **additive provenance only** — it must NOT change score *meaning* or the Verdict Engine
  (keep the frozen-core invariants). `check_core_isolation` must stay green.
- It unblocks the plugin's `view --by-call` **only after** the **artifact-shape gate** (plan §10)
  proves `Score` carries the subject in a real `runrecord.json`. Land F1, prove the artifact, *then*
  ship the plugin reader.

### A1 — authoring tier + `connect --live`
- `add-metric`/`add-judge`/`calibrate` must keep generated assets **`proposed`/uncalibrated/
  empty-authority** (reuse `harness/governance.py` + `scaffold.py` patterns). **Do not reintroduce a
  gate-activation verb** — `promote-gate` was removed; the honesty-audit no-authority-verb test
  (`tests/plugin/test_skills.py`) enforces it.
- **`connect --live` (Phoenix/Langfuse) is an OPTIONAL LANE** (ADR 0017/0018): isolated, pinned,
  opt-in, **deletable**, with **verify-deletion** proof; **no required import path may load it.**
  scan-gate IS in jurisdiction (optional-SDK-leakage). If a second adapter mirrors an existing one,
  **factor the whole shared flow** (memory: `adapters/_span_mapping.py`) or Sonar duplication (>3% on
  new code) fails the gate.

### P3 — Codex second runtime
- One canonical `skills/` tree; add `.codex-plugin/plugin.json` (`interface{}` block) + an `AGENTS.md`
  bootstrap (trigger-and-routing only — **add it to the honesty-audit scan target set**); a
  deterministic `scripts/sync-to-codex-plugin.sh` with a drift self-check; and a `.version-bump.json`
  (now 5+ version files). Template: **`obra/superpowers`** (`.codex-plugin`/`.cursor-plugin`/
  `.opencode`) — re-clone it (`/tmp/eg-research/` may be gone): `https://github.com/obra/superpowers`.
- Multi-runtime is purely integration-time delivery; the **runtime-after-removal / deletion-invariant
  must hold across runtimes**, proven by a per-runtime acceptance-probe transcript.

---

## 10. Reusable test surfaces already in `tests/plugin/`

Extend these rather than reinventing: `test_manifests.py` (schema), `test_layout_boundary.py`
(vendoring boundary — `MANAGED_PACKAGES` never includes plugin dirs), `test_skills.py` (frontmatter +
no-authority-verb + honesty guardrail), `test_hooks.py` (bootstrap exit-0/state-free),
`test_launcher.py` (bundled launcher), `test_verbs.py` (umbrella routing invariants),
`test_first_run_e2e.py` (**deletion-invariant verdict identity** — reuses `vendor()`+`scaffold()`
like `tests/skill/test_runtime_independence.py`), `test_version_alignment.py`, `test_honesty_audit.py`
(the fail-closed prose gate — **add new prose surfaces to its target list**).
