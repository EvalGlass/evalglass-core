# Demo (reproducible)

The above-the-fold demo media for the README/marketplace is generated from
[`record-demo.sh`](./record-demo.sh) — committed commands, never hand-edited screenshots — so it
cannot drift from real behavior (EGP-P2-4).

## Regenerate

```bash
# Plain run (what the cast shows):
sh examples/demo/record-demo.sh

# Record an asciinema cast:
asciinema rec assets/demo.cast -c "sh examples/demo/record-demo.sh"

# (Optional) render the cast to a GIF with agg:
agg assets/demo.cast assets/demo.gif
```

The cast/GIF is stored under `assets/` and referenced by the README. It shows: run → a **populated**
Scorecard → an **informational** verdict with the diagnostic that no gate is active. It does **not**
show per-call (`--by-call`) output — that ships only after framework follow-up F1.

> Media artifacts (`assets/demo.cast`, `assets/demo.gif`) are produced on a maintainer machine with
> `asciinema`/`agg` installed and committed separately; this directory holds the reproducible source.
