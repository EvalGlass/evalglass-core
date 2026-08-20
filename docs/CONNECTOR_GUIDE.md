# Optional live trace connectors — host guide & privacy review

This guide covers the opt-in live trace connectors (Langfuse, Phoenix, LangSmith) added in the
EG-R live-connector tranche: how a host adopts one, and the privacy / egress / dependency review
that keeps them honest. Connectors **import evidence, never authority** — an optional provider pull
can never make a stronger Scorecard claim.

## Host migration (existing repos are unaffected)

- An existing `evalglass.yaml` **without** a `lanes:` block runs exactly as before — connectors are
  opt-in and nothing loads them unless you enable a lane.
- Existing `runrecord.json` without `lane_results` parses unchanged (`lane_results` defaults to `[]`).
- To adopt a connector, add an opt-in lane and install its extra (e.g. `pip install
  'evalglass[langsmith-trace]'`). **Lean by default, complete by composition:** the granular
  extras (`langfuse-trace`, `phoenix-trace`, `langsmith-trace`) install exactly one connector each;
  the grouped `traces` extra (`pip install 'evalglass[traces]'`) pulls all three, and `evalglass[all]`
  the full optional surface. The grouped extras compose the granular ones and pin no SDK of their
  own, so the required tier stays SDK-free either way.

  ```yaml
  lanes:
    - name: langsmith-trace
      enabled: true
      data_policy: permitted        # egress is refused for forbidden/missing/unknown
      options:
        endpoint: https://api.smith.langchain.com
        credentials:
          api_key: LANGSMITH_API_KEY    # an environment-variable NAME — never an inline secret
  ```

- After enabling a lane, **compare the Scorecard verdict payload before and after**: it must be
  byte-identical. A connector contributes recorded behavior as input evidence; it never changes the
  verdict, authority, or CI exit. Its outcome is recorded in `RunRecord.lane_results` as
  side-channel evidence (`ran` / `skipped` / `blocked`) — never a gating signal.
- Gate promotion stays host-owned: you promote a gate by editing host-owned config + validation
  records, never by enabling a connector.

## Privacy, egress, and dependency review (EG-R5-5)

- **No secrets in artifacts.** Credentials are environment-variable *references* (names) in config;
  the secret is read only when the lane is enabled and is never written to `RunRecord`, `Scorecard`,
  `lane_results`, reports, logs, or evidence packs. The connector boundary rejects inline secret
  values (an env-var-name regex), and the rejection message never echoes the offending value.
- **Egress before effects.** `forbidden`, `missing`, and `unknown` data policies refuse egress
  *before* any provider call — only `permitted` / `redacted` may reach the network.
- **No SDK on a required path.** Each provider SDK is a pinned, isolated optional extra
  (`langfuse-trace`, `phoenix-trace`, `langsmith-trace`), imported lazily inside the lane path. The
  required, hermetic tier installs no extra and imports no provider SDK; deleting a connector adapter
  leaves the required tier and the other connectors green.
- **LangChain is never pulled.** The LangSmith connector imports only `langsmith`, never
  `langchain` / `langchain-core`.
- **Live verification is opt-in.** Real provider pulls are `live_lane`-only, gated on
  `EVALGLASS_LIVE_LANES=1` plus provider env vars; they never run in ordinary CI.

## What these connectors are not

EvalGlass is repo-native, local-first quality control. The connectors are optional trace-import
lanes — **not** hosted EvalGlass telemetry, **not** a required dependency, and **not** any form of
certification or safety proof. A green run with a connector enabled means exactly what a green run
without one means: only what the supplied evidence supports.
