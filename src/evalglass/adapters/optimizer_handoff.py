"""Optional prompt-optimizer handoff lane (EG-H2-5; ADR 0031; alignment plan §5.3, delta D5).

An opt-in, deletable SCORE_SINK lane that packages a run's findings for an external prompt
optimizer as a **write-only** export. It is a *next*-status capability — useful evidence packaging,
never an automation authority:

- **Write-only.** It writes one findings artifact under ``reports/optimizer/`` and never writes back
  into host-owned truth (datasets / evaluators / rubrics / ``evalglass.yaml`` / baselines /
  host authority records / source). A destination escaping the host root fails closed to
  ``BLOCKED``.
- **No recompute.** The findings are derived from the typed Scorecard; the verdict is **echoed
  verbatim** from ``scorecard.to_dict()``. This module imports no Verdict Engine, authority
  resolver, or aggregator — it renders typed artifacts, it does not re-derive meaning.
- **A lane, not an authority.** It returns a :class:`~evalglass.harness.lanes.LaneResult` only — no
  ``score``/``verdict``/``authority`` field. No required path imports it; deleting this file leaves
  the local JSON + Markdown reports intact. Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.core import Diagnostic, Scorecard, Severity
from evalglass.core.contracts import DataPolicy
from evalglass.harness.lanes import LaneResult, LaneStatus

_FINDINGS_FILENAME = "findings.json"

#: An explicit, non-authoritative framing recorded into the handoff so a downstream consumer (or a
#: reviewer) cannot read it as an approval: EvalGlass does not tune prompts and this grants nothing.
_HANDOFF_NOTE = (
    "evidence handoff for prompt optimization; EvalGlass does not tune prompts, "
    "and this artifact grants no score, verdict, authority, or gating decision"
)


class OptimizerHandoffSink:
    """Write a one-way, Scorecard-derived findings artifact under ``reports/optimizer/``."""

    #: The fixed write subtree under the host root. It is NOT host-configurable: a configurable
    #: destination could be pointed at a host-truth tree (``datasets``), and the lane's contract is
    #: that it writes only under ``reports/optimizer/`` — never back into host-owned truth.
    _WRITE_PARTS = ("reports", "optimizer")

    def __init__(
        self,
        *,
        root: Path,
        data_policy: str | DataPolicy = DataPolicy.UNKNOWN,
        name: str = "optimizer-handoff",
    ) -> None:
        self._root = root
        self._target = root.joinpath(*self._WRITE_PARTS)
        # ``data_policy`` is the host-declared egress policy the seam threads to every SCORE_SINK
        # factory. This handoff writes *locally* under the fixed reports subtree (not egress to an
        # external destination), so it does not gate the write; it is retained for seam symmetry.
        self._data_policy = data_policy
        self._name = name

    def export(self, scorecard: Scorecard) -> LaneResult:
        data = scorecard.to_dict()
        # Findings are DERIVED from the typed Scorecard — the verdict and metric/diagnostic
        # summaries are echoed verbatim, never recomputed. No meaning engine is consulted.
        findings = {
            "verdict": data["verdict"],
            "metrics": data.get("metrics", []),
            "diagnostics": data.get("diagnostics", []),
            "note": _HANDOFF_NOTE,
        }
        payload = json.dumps(findings, indent=2, sort_keys=True)
        final = self._target / _FINDINGS_FILENAME
        try:
            # Fail closed if any existing path component is a symlink: a symlinked ``reports/`` or
            # a pre-planted ``findings.json`` symlink would let ``write_text`` follow the link and
            # clobber a dataset/config file or a target outside the host root. Refuse first.
            probe = self._root
            for part in (*self._WRITE_PARTS, _FINDINGS_FILENAME):
                probe = probe / part
                if probe.is_symlink():
                    return _blocked(
                        self._name,
                        "optimizer_handoff_symlink_refused",
                        f"handoff refused: {probe} is a symlink (would redirect the write)",
                    )
            # Defense in depth: the fixed subtree is always in-root, but a symlinked root could
            # still escape — refuse if the resolved destination leaves the host root.
            if not final.resolve().is_relative_to(self._root.resolve()):
                return _blocked(
                    self._name,
                    "optimizer_handoff_outside_root",
                    f"handoff refused: destination escapes the host root ({final})",
                )
            self._target.mkdir(parents=True, exist_ok=True)
            final.write_text(payload, encoding="utf-8")
        except OSError as exc:
            # A failed write is a diagnostic — the core verdict is untouched and authoritative.
            return _blocked(
                self._name,
                "optimizer_handoff_failed",
                f"could not write optimizer findings to {self._target}: {exc}",
            )
        return LaneResult(
            lane=self._name,
            status=LaneStatus.RAN,
            report=f"wrote optimizer handoff findings to {self._target / _FINDINGS_FILENAME}",
        )


def _blocked(name: str, code: str, message: str) -> LaneResult:
    return LaneResult(
        lane=name,
        status=LaneStatus.BLOCKED,
        report=message,
        diagnostics=[Diagnostic(code=code, severity=Severity.ERROR, message=message)],
    )
