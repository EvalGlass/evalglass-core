# ADR 0007 — Subprocess TaskRunner contract

- **Status:** accepted
- **Date:** 2026-05-31

## Context

M2 adds host *replay*: when a dataset/trace example lacks an output, EvalGlass
must be able to run the host system to produce one (build contract §8; EG-M2-1).
The host system is arbitrary host-owned code, so how EvalGlass invokes it is a
**trust surface**: a careless contract could enable shell injection, hang the
run, or let a host crash masquerade as a low quality score.

## Decision

| Concern | Choice | Notes |
|---|---|---|
| Port | `harness/ports.py` `TaskRunner` Protocol + `TaskRequest`/`TaskResult` | Returns evidence/data only — never a score, authority, or verdict. |
| Transport | JSON on stdin → JSON on stdout | `{"example_id", "input"}` in; `{"output": ...}` out. Simple, language-agnostic, host-owned. |
| Command | host-declared `argv` **list**, run with `shell=False` | The argv is the entire trust surface; input is data and is never shell-interpreted. No `shell=True`, ever. |
| Config | `config.py` `TaskConfig` (argv, `timeout_s`); fail-closed parse | Empty/non-list argv or non-positive/non-finite timeout is a setup error. Opt-in: absent `task:` → no replay. |
| Timeout | required, positive, finite (default 30s) | A hung host is bounded; a timeout is infrastructure evidence. |
| Failure mapping | spawn failure, timeout, non-zero exit, malformed/absent output → `TaskResult.output=None` + typed `Diagnostic` (`task_spawn_failed` / `task_timeout` / `task_nonzero_exit` / `task_malformed_output` / `task_missing_output`) | A host/infra failure is **infrastructure evidence, never a `0.0` score or a quality verdict** (build contract §8). stderr is captured (bounded) into the diagnostic `cause`. |
| Bandit | `# noqa: S603` on the single `subprocess.run` site | Justified: host-declared argv, `shell=False`, no string interpolation into a command. |

## Consequences

- Replay cannot inject a shell command: input travels on stdin as JSON data,
  and the command is a fixed host-declared argv.
- A host that crashes, hangs, or emits garbage produces typed infrastructure
  diagnostics, not a fabricated quality result — the S3 replay route (EG-M2-1b)
  feeds these into the existing route-error/excluded path so an active gate
  **blocks** rather than passing over a failed replay.
- The `TaskRunner` is effectful and lives in an adapter; the core never sees a
  subprocess, only the normalized `output` (or its absence + diagnostics).

## Alternatives considered

- **`shell=True` with a command string.** Rejected — direct injection risk and
  non-portable quoting. A host-declared argv list is safe and explicit.
- **Treat a non-zero exit as a `0.0` score.** Rejected — that is exactly the
  false-confidence collapse the failure taxonomy exists to prevent: an
  infrastructure failure is not a measured quality of the host's answer.
- **No timeout (rely on CI wall-clock).** Rejected — a hung host should fail as a
  bounded, typed timeout diagnostic, not an opaque CI kill.
