# ADR 0053 — Structured rubric contract and structured judge-result

**Status:** Accepted

## Context

A judge is only as meaningful as its construct and evidence boundary. Until now a rubric was a
markdown blob (`rubric.py`) and a judge response was reduced to a scalar `score` + `rationale`. The
richer content a good rubric produces — per-criterion facet values, rule violations, cited evidence,
an explicit refusal — had nowhere typed to live, so a host that wanted it maintained a private parser
and cache. There was also no way to *bound* what a judge sees: the whole example flowed into the
prompt regardless of what the rubric declared it needed.

## Decision

Introduce a structured, versioned, host-owned rubric contract and a matching structured judge-result,
both typed and both granting no authority.

1. **`RubricSpec` (`evalglass.rubric/1`).** A rubric declares a one-sentence construct, ordered
   **anchored** criteria (each with score bands or an explicit non-score output type — an unanchored
   criterion is refused), a declared **evidence boundary** (`evidence_layers` — the dossier the judge
   may see), refusal conditions, and a response schema (which facets are accepted, whether
   violations/citations are allowed/required). It carries version/prompt/parser identity and a
   **content digest** that turns on score-determining content — reviewing a rubric does not change the
   digest, but a construct/criteria/version/parser change does, so it breaks comparability.

2. **Lifecycle.** A new rubric is `proposed` until a host reviews it; calibration stays a separate,
   later act. The rubric never grants authority regardless of lifecycle — authority is calibration +
   an approved threshold, through the Verdict Engine.

3. **Structured response parser.** A judge's JSON is validated against the rubric: it distinguishes a
   valid score from a **refusal**, **missing evidence**, and a **parser error**; it **rejects any
   facet not declared** as a criterion; and it resolves cited evidence refs against the bounded
   dossier — an invented citation is a parser error. A non-OK outcome carries no score.

4. **Bounded dossier.** The OpenAI judge renders the structured prompt showing only the rubric's
   declared `evidence_layers`, each size-capped, and treats them as untrusted DATA (the system prompt
   forbids following instructions inside them). The judge may cite only the layers it was shown.

5. **Extended evidence contracts.** `JudgeResult` and the core `JudgeEvidence` gain additive optional
   `facets` / `violations` / `citations` / `refusal_reason`. Structured scored content may appear only
   on an `OK` status (the same rule that forbids a value on a failed judge); a refusal maps to
   `MISSING` carrying its reason, never a fabricated low score. Fields serialize only when present, so
   existing artifacts are byte-identical.

6. **Compatibility.** A markdown rubric loads as a scalar `RubricSpec` (an unanchored construct, no
   facets), so the command judge's and the existing OpenAI judge's score+rationale contract keep
   working. The structured contract is opt-in per rubric file (`.json`).

## Consequences

- A host can author, review, and run a structured rubric with no custom parser code; the run yields
  typed facets/violations/citations rather than a scalar hidden behind host parsing.
- The rubric's evidence boundary is enforced: a metric cannot see behaviour its rubric did not
  declare, and a judge cannot cite outside the dossier.
- Rubric/prompt/parser/schema changes enter provenance and break comparability, keeping calibration
  and baselines honest.
- The persisted, portable form of this structured evidence — resolvable from `Score.evidence_refs`
  without a host cache — is delivered by ADR 0054 (persist complete judge evidence).
