"""F-8 — golden artifact engine (EG-AT0-5).

Goldens are produced from **real** ``VendoredHost`` runs (never hand-authored)
and diffed deterministically. The normalization map is **explicit and total**:
the typed JSON artifacts (``scorecard.json`` / ``runrecord.json``) and
``report.md`` are byte-deterministic given a fixed run-id and the hermetic core,
so they are masked by *nothing*; only the CLI stdout's absolute ``artifacts:``
path is genuinely nondeterministic and is masked to ``<HOST>``. A
``normalization-is-total`` test proves every masked location is actually
nondeterministic and every unmasked location is stable across two runs.

Regenerate (never in CI)::

    python -m tests.egts.golden regenerate fresh_informational

CI only ever calls :func:`assert_matches_golden`; it never regenerates.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tests.egts.host_repo import AuthorityState, VendoredHost, make_vendored_host

GOLDEN_DIR = Path(__file__).parent / "golden"

#: scenario id -> the authority state that produces it.
SCENARIOS: dict[str, AuthorityState] = {
    "fresh_informational": AuthorityState.FRESH_INFORMATIONAL,
    "host_promoted_gate": AuthorityState.HOST_PROMOTED_GATE,
}

#: JSON masks — empty by design (the artifacts are deterministic). Adding one
#: requires the ``normalization-is-total`` test to prove it is nondeterministic.
_JSON_MASKS: tuple[str, ...] = ()


def normalize_json(obj: Any) -> Any:
    """Apply the (currently empty) JSON mask set; returns a canonical copy."""
    if isinstance(obj, Mapping):
        return {k: ("<masked>" if k in _JSON_MASKS else normalize_json(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_json(v) for v in obj]
    return obj


def _canon(obj: Any) -> str:
    return json.dumps(normalize_json(obj), indent=2, sort_keys=True) + "\n"


def normalize_text(text: str, host_root: Path) -> str:
    """Mask the one genuinely nondeterministic token in CLI text: the host abs path."""
    return text.replace(str(host_root.resolve()), "<HOST>").replace(str(host_root), "<HOST>")


def _host_for(scenario_id: str, base: Path) -> VendoredHost:
    if scenario_id not in SCENARIOS:
        allowed = ", ".join(sorted(SCENARIOS))
        raise KeyError(f"unknown golden scenario {scenario_id!r}; known: {allowed}")
    return make_vendored_host(base, scenario_id, authority_state=SCENARIOS[scenario_id])


def render_artifacts(scenario_id: str, base: Path) -> dict[str, str]:
    """Run the real surface for ``scenario_id`` and return the four canonical goldens."""
    host = _host_for(scenario_id, base)
    result = host.run(["run", "--config", "evals/evalglass.yaml", "--format", "ci"])
    if result.scorecard is None or result.runrecord is None:
        raise RuntimeError(f"scenario {scenario_id} produced no artifacts: {result.stderr}")
    report_md = (host.evals_dir / "reports" / host.run_id / "report.md").read_text(encoding="utf-8")
    return {
        "scorecard.json": _canon(result.scorecard),
        "runrecord.json": _canon(result.runrecord),
        "report.md": normalize_text(report_md, host.root),
        "ci-annotations.txt": normalize_text(result.stdout, host.root),
    }


def regenerate(scenario_id: str, base: Path | None = None) -> Path:
    """Produce and write the golden set for ``scenario_id`` (never called by CI)."""
    base = base or Path(tempfile.mkdtemp(prefix=f"golden-{scenario_id}-"))
    artifacts = render_artifacts(scenario_id, base)
    out = GOLDEN_DIR / scenario_id
    out.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        (out / name).write_text(content, encoding="utf-8")
    return out


def load_golden(scenario_id: str) -> dict[str, str]:
    out = GOLDEN_DIR / scenario_id
    if not out.is_dir():
        raise FileNotFoundError(
            f"no committed golden for {scenario_id!r} — run `golden regenerate`"
        )
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(out.iterdir()) if p.is_file()}


def assert_matches_golden(scenario_id: str, artifacts: Mapping[str, str]) -> None:
    """Compare freshly-rendered (already-normalized) ``artifacts`` to the stored golden."""
    golden = load_golden(scenario_id)
    for name, expected in golden.items():
        actual = artifacts.get(name)
        if actual != expected:
            raise AssertionError(
                f"golden drift in {scenario_id}/{name}: emitted artifact differs from the "
                f"committed golden. Regenerate deliberately only on an intended contract change."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="golden", description="EvalGlass golden artifact engine")
    sub = parser.add_subparsers(dest="command", required=True)
    regen = sub.add_parser("regenerate", help="Regenerate a scenario's golden from a real run.")
    regen.add_argument("scenario_id", choices=sorted(SCENARIOS))
    args = parser.parse_args(argv)
    if args.command == "regenerate":
        out = regenerate(args.scenario_id)
        print(f"regenerated golden: {out}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
