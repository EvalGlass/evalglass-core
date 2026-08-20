"""Explicit baseline promotion via the CLI (EG-M2-2b).

Promotion is a separate, explicit command — ``evalglass baseline update --from <runrecord> --to
<baseline>``. An ordinary ``evalglass run`` never writes a baseline (a run that could promote its
own baseline could never regress against itself). A bad ``--from`` is a setup error (exit 2).
"""

from __future__ import annotations

import json
from pathlib import Path

from evalglass.harness.baseline import load_baseline
from evalglass.harness.cli import main

_RUN_CFG = """
run:
  id: demo
datasets:
  - path: d.jsonl
    status: validated
    data_policy: permitted
metrics:
  - name: exact_match
    evaluator_ref: exact_match@1
    lens: reference
    score_type: binary
    dataset: d.jsonl
output:
  dir: reports
"""


def _config_with_run(tmp_path: Path) -> Path:
    (tmp_path / "d.jsonl").write_text(
        json.dumps({"input": "2+2", "output": "4", "reference": "4"}) + "\n", encoding="utf-8"
    )
    cfg = tmp_path / "evalglass.yaml"
    cfg.write_text(_RUN_CFG, encoding="utf-8")
    return cfg


def test_run_writes_no_baseline(tmp_path: Path) -> None:
    cfg = _config_with_run(tmp_path)
    assert main(["run", "--config", str(cfg)]) == 0
    # The run persists under reports/ only — it must never create a baseline.
    assert not (tmp_path / "baselines").exists()


def test_baseline_update_promotes_run_record(tmp_path: Path) -> None:
    cfg = _config_with_run(tmp_path)
    assert main(["run", "--config", str(cfg)]) == 0
    runrecord = tmp_path / "reports" / "demo" / "runrecord.json"
    baseline = tmp_path / "baselines" / "main.json"
    assert main(["baseline", "update", "--from", str(runrecord), "--to", str(baseline)]) == 0
    assert baseline.is_file()
    # The promoted baseline is a valid RunRecord whose provenance can be loaded.
    assert load_baseline(baseline).dimensions  # non-empty fingerprint


def test_baseline_update_missing_from_is_setup_error(tmp_path: Path) -> None:
    code = main(
        [
            "baseline",
            "update",
            "--from",
            str(tmp_path / "nope.json"),
            "--to",
            str(tmp_path / "b.json"),
        ]
    )
    assert code == 2


def test_baseline_update_invalid_from_is_setup_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not a runrecord", encoding="utf-8")
    code = main(["baseline", "update", "--from", str(bad), "--to", str(tmp_path / "b.json")])
    assert code == 2


# --- EG-NR-4: promotion verifies run integrity (manifest + marker + digests) -----------------


def test_baseline_update_refuses_unverified_copy(tmp_path: Path) -> None:
    # A structurally-valid runrecord.json copied OUT of its run directory has no manifest/marker,
    # so it cannot be promoted — a hand-assembled "baseline" must be refused (fail-closed).
    cfg = _config_with_run(tmp_path)
    assert main(["run", "--config", str(cfg)]) == 0
    runrecord = tmp_path / "reports" / "demo" / "runrecord.json"
    bare = tmp_path / "loose"
    bare.mkdir()
    (bare / "runrecord.json").write_text(runrecord.read_text(encoding="utf-8"), encoding="utf-8")
    code = main(
        [
            "baseline",
            "update",
            "--from",
            str(bare / "runrecord.json"),
            "--to",
            str(tmp_path / "b.json"),
        ]
    )
    assert code == 2
    assert not (tmp_path / "b.json").exists()  # nothing was promoted


def test_baseline_update_refuses_forged_sibling(tmp_path: Path) -> None:
    # A modified copy named something else, dropped INSIDE a genuine verified run directory, must
    # not be promotable: verify_run digests the manifest-listed runrecord.json, and promotion must
    # adopt exactly that file — not an unlisted sibling the manifest never covered.
    cfg = _config_with_run(tmp_path)
    assert main(["run", "--config", str(cfg)]) == 0
    run_dir = tmp_path / "reports" / "demo"
    forged = run_dir / "forged.json"
    data = json.loads((run_dir / "runrecord.json").read_text(encoding="utf-8"))
    data["run_id"] = "forged"
    forged.write_text(json.dumps(data) + "\n", encoding="utf-8")
    code = main(["baseline", "update", "--from", str(forged), "--to", str(tmp_path / "b.json")])
    assert code == 2
    assert not (tmp_path / "b.json").exists()


def test_baseline_update_malformed_manifest_is_setup_error(tmp_path: Path) -> None:
    # A run dir with a marker + manifest whose ``files`` is the wrong shape must fail closed at
    # exit 2, not raise a raw traceback out of verify_run.
    cfg = _config_with_run(tmp_path)
    assert main(["run", "--config", str(cfg)]) == 0
    run_dir = tmp_path / "reports" / "demo"
    (run_dir / "manifest.json").write_text(
        json.dumps({"schema": "evalglass.run-manifest/1", "files": []}), encoding="utf-8"
    )
    code = main(
        [
            "baseline",
            "update",
            "--from",
            str(run_dir / "runrecord.json"),
            "--to",
            str(tmp_path / "b.json"),
        ]
    )
    assert code == 2
    assert not (tmp_path / "b.json").exists()


def test_baseline_update_refuses_tampered_run(tmp_path: Path) -> None:
    # Editing a persisted runrecord in place breaks its manifest digest — promotion must refuse it,
    # so a downstream tool can never adopt a doctored baseline.
    cfg = _config_with_run(tmp_path)
    assert main(["run", "--config", str(cfg)]) == 0
    runrecord = tmp_path / "reports" / "demo" / "runrecord.json"
    data = json.loads(runrecord.read_text(encoding="utf-8"))
    data["run_id"] = "tampered"
    runrecord.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    code = main(["baseline", "update", "--from", str(runrecord), "--to", str(tmp_path / "b.json")])
    assert code == 2
    assert not (tmp_path / "b.json").exists()
