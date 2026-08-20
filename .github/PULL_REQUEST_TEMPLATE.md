<!--
Thanks for contributing to EvalGlass. Before requesting review, please fill
out the sections below. Items in *italics* are signals to reviewers about the
trust-model impact of this change — see CLAUDE.md §5, §11, §12.
-->

## Summary

<!-- One paragraph: what changed and why. Link to issues / ADRs. -->

## Architectural impact

<!-- Check every box that applies. -->

- [ ] Touches `src/evalglass/core/**` (effect-free Evaluation Core)
- [ ] Touches the Verdict Engine (`src/evalglass/core/verdict/**`)
- [ ] Changes a public contract (CLI, report JSON, scorecard schema, evaluator protocol)
- [ ] Adds or modifies a port / adapter
- [ ] Adds a runtime dependency to `pyproject.toml` &nbsp;→ &nbsp;**ADR required**; link: ___
- [ ] Touches the scaffolding the skill installs into host repos
- [ ] None of the above (docs / refactor / tests only)

## Test families covered

<!-- See CLAUDE.md §9. Tick the families this PR exercises. -->

- [ ] core isolation
- [ ] verdict matrix
- [ ] evaluator contract
- [ ] fixture end-to-end
- [ ] adapter conformance
- [ ] judge tests
- [ ] baseline tests
- [ ] data-policy tests
- [ ] vendoring tests
- [ ] public surface snapshot
- [ ] N/A (no behavioral change)

## Authority / trust-model

<!-- See CLAUDE.md §5. -->

- [ ] No change to dataset, metric, threshold, judge calibration, baseline, or data-policy state
- [ ] Changes authority state — explain which and why: ___

## Cardinal question (CLAUDE.md §12)

> Could a green scorecard from this change be misread as proof of correctness
> when it is only informational, unvalidated, uncalibrated, or non-comparable?

- [ ] No — and the reason: ___

## Reviewer checklist

- [ ] Evaluation Core / Runtime Harness boundary preserved
- [ ] No domain knowledge in the core
- [ ] No silent gating introduced
- [ ] Scores carry useful diagnostics (where applicable)
- [ ] Provenance recorded where results need interpretation
- [ ] Public contracts not drifted silently
- [ ] Optional parts remain optional
- [ ] Host-owned files not overwritten
