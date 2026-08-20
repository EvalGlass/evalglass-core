#!/usr/bin/env sh
# EvalGlass SessionStart bootstrap — display-only skill-discovery pointer.
#
# Contract (ADR 0022, "SessionStart hook"):
#   - MUST exit 0 unconditionally and never block a session.
#   - MUST only point to the umbrella skill and its entry phrase.
#   - MUST NOT read, recompute, or echo any scorecard / runrecord / verdict / authority /
#     gate / quality state, and MUST assert no capability or quality claim.
# Its stdout is injected as session context — keep it a pointer, nothing more.

printf '%s\n' "EvalGlass plugin available. Type /evalglass for a status overview, or say \"evaluate my agentic app with EvalGlass\" to begin."

exit 0
