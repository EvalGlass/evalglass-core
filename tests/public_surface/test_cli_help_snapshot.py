"""FS-SNAP-3 — freeze the CLI's parsed verb/flag surface (EG-AT1 Slice 2, EG-AT1-2).

The CLI contract is the *parsed* verb/flag surface, not the rendered ``--help``
text (which varies across Python patch versions). A new verb or flag — the way a
re-admitted lane would leak into the runtime CLI — drifts the frozen surface.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from evalglass.harness.cli import build_parser
from tests.public_surface._normalize import (
    help_prose,
    parser_surface,
    report_overclaim_words,
)

_SNAP = Path(__file__).parent / "_snapshots"


def _load(name: str) -> dict[str, Any]:
    data = json.loads((_SNAP / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.mark.public_surface
def test_cli_parsed_surface_frozen() -> None:
    assert parser_surface(build_parser()) == _load("cli_help_surface.json")


@pytest.mark.public_surface
def test_cli_run_and_baseline_flags_exact() -> None:
    surface = parser_surface(build_parser())
    assert surface["prog"] == "evalglass"
    assert set(surface["commands"]) == {
        "run",
        "baseline",
        "view",
        "connect",
        "watch",
        "preflight",
        "assemble",
        "series",
    }
    # series (Epic E): inspect/repair the immutable run-series index — never changes a verdict.
    series = surface["commands"]["series"]["commands"]
    assert set(series) == {"list", "repair"}
    assert series["repair"]["options"]["--out"]["required"] is True
    # assemble (Epic B): declarative evidence assembly → a host-owned Example JSONL + manifest.
    asm = surface["commands"]["assemble"]["options"]
    assert set(asm) == {"--config", "--out"}
    assert asm["--config"]["required"] is True
    assert asm["--out"]["required"] is True
    # preflight: a side-effect-free preview; text/json are projections of one plan.
    preflight = surface["commands"]["preflight"]["options"]
    assert set(preflight) == {"--config", "--format", "--out"}
    assert preflight["--config"]["required"] is True
    # run --dry-run resolves + writes the plan without any effect.
    assert "--dry-run" in surface["commands"]["run"]["options"]
    # connect: local import (--from) or opt-in connector-lane scaffold (--live) — exactly one.
    conn = surface["commands"]["connect"]["options"]
    assert set(conn) == {
        "--from",
        "--format",
        "--init",
        "--live",
        "--config",
        "--endpoint",
        "--project",
        "--credentials",
        "--data-policy",
        "--limit",
    }
    # Neither --from nor --live is argparse-required (exactly-one is enforced in the handler).
    assert conn["--live"]["required"] is False
    assert conn["--from"]["required"] is False
    assert conn["--from"]["dest"] == "from_path"
    assert conn["--format"]["choices"] == ["local", "openinference", "opentelemetry"]
    assert conn["--config"]["default"] == "evalglass.yaml"
    assert conn["--data-policy"]["default"] == "unknown"  # fail-closed egress default
    # watch (EG-P4): one drift check per invocation; exit still derives only from the verdict.
    w = surface["commands"]["watch"]["options"]
    assert set(w) == {"--config", "--out"}
    assert w["--config"]["required"] is True
    run = surface["commands"]["run"]["options"]
    # --debug (EG-NR-5) surfaces the original traceback on a setup/infra error; off by default.
    assert set(run) == {"--config", "--out", "--format", "--debug", "--dry-run"}
    assert run["--debug"]["default"] is False
    assert run["--config"]["flags"] == ["--config"]  # every spelling recorded
    assert run["--config"]["required"] is True
    assert run["--format"]["choices"] == ["ci", "terminal"]
    assert run["--format"]["default"] == "terminal"
    # view is a read-only inspection verb: a record path + a text/json render choice.
    view = surface["commands"]["view"]["options"]
    assert set(view) == {"--record", "--format"}
    assert view["--record"]["required"] is True
    assert view["--format"]["choices"] == ["json", "text"]
    assert view["--format"]["default"] == "text"
    assert set(surface["commands"]["baseline"]["commands"]) == {"update"}
    update = surface["commands"]["baseline"]["commands"]["update"]["options"]
    assert update["--from"]["dest"] == "from_path"
    assert update["--from"]["required"] is True
    assert update["--to"]["dest"] == "to_path"
    assert update["--to"]["required"] is True


@pytest.mark.public_surface
def test_cli_injected_flag_fails() -> None:
    """Sensitivity: an added --dashboard flag drifts the frozen surface."""
    golden = _load("cli_help_surface.json")
    assert "--dashboard" not in golden["commands"]["run"]["options"]
    tampered = copy.deepcopy(golden)
    tampered["commands"]["run"]["options"]["--dashboard"] = {
        "dest": "dashboard",
        "flags": ["--dashboard"],
        "required": False,
        "choices": None,
        "default": None,
    }
    assert tampered != golden


@pytest.mark.public_surface
def test_cli_help_strings_frozen() -> None:
    """The help/description strings are frozen in the (width-independent) surface.

    They live in ``cli_help_surface.json`` (asserted by ``test_cli_parsed_surface_frozen``),
    so a help/description drift — e.g. an overclaiming 'certify quality' phrase —
    moves the snapshot. This test pins the load-bearing strings explicitly.
    """
    surface = parser_surface(build_parser())
    assert surface["description"] == "EvalGlass local evaluation runner."
    assert surface["commands"]["run"]["help"] == "Run an evaluation from a local config."
    assert surface["commands"]["run"]["options"]["--config"]["help"] == "Path to evalglass.yaml."


@pytest.mark.public_surface
def test_cli_help_text_no_overclaim() -> None:
    """No unearned-success word may appear in user-visible --help prose."""
    assert report_overclaim_words(help_prose(parser_surface(build_parser()))) == set()
