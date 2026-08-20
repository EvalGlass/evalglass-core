#!/usr/bin/env sh
# Reproducible EvalGlass demo (EGP-P2-4). The demo MEDIA (GIF / asciinema cast) is generated
# from THIS script, not hand-edited — so it can never drift from real behavior. See README.md.
#
# It runs the bundled quickstart and shows the honest first-run payoff: real non-reference signal
# and an INFORMATIONAL verdict (not a manufactured pass), with the per-metric breakdown.
#
# Usage (from the repo root):  sh examples/demo/record-demo.sh
#   To record a cast:          asciinema rec demo.cast -c "sh examples/demo/record-demo.sh"
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
PY="${PYTHON:-python3}"

say() { printf '\n$ %s\n' "$*"; }

say "evalglass: evaluate the bundled quickstart (no install required)"
say "PYTHONPATH=src $PY -m evalglass.harness.cli run --config examples/quickstart/evals/evalglass.yaml"
PYTHONPATH="$ROOT/src" "$PY" -m evalglass.harness.cli \
  run --config "$ROOT/examples/quickstart/evals/evalglass.yaml"

printf '\n# Verdict is INFORMATIONAL: real non-reference signal, no gate active — evidence, not a pass.\n'
printf '# scorecard.json / runrecord.json / report.md are written under the example reports dir.\n'
