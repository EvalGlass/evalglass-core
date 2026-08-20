#!/usr/bin/env sh
# EvalGlass plugin validation (EGP-P0-8).
#
# Runs the hermetic structural floor (always) and the live `claude plugin validate . --strict`
# when the `claude` binary is available. Exits non-zero if either fails.
#
# Usage:  tools/validate_plugin.sh
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Structural floor: pytest tests/plugin =="
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
"$PY" -m pytest tests/plugin -q

echo
echo "== Live: claude plugin validate . --strict =="
if command -v claude >/dev/null 2>&1; then
  claude plugin validate . --strict
else
  echo "SKIPPED — 'claude' binary not found (run this where Claude Code is installed)."
fi

echo
echo "Structural validation passed. Interactive probes (invocation token, NL trigger, SessionStart"
echo "binding, no-arg dashboard) are manual — maintainer acceptance probes."
