"""S1 (EG-M3-1) — `evalglass-install discover|plan` CLI surface.

The CLI is a thin wrapper that prints the typed artifacts as JSON; it owns no
authority and (for discover/plan) mutates nothing in the host.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evalglass.installer.cli import main


def _host(tmp_path: Path) -> Path:
    root = tmp_path / "host"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("import openai\n", encoding="utf-8")
    return root


def _tree_hash(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_discover_prints_json_and_is_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _host(tmp_path)
    before = _tree_hash(root)
    rc = main(["discover", "--root", str(root)])
    after = _tree_hash(root)
    assert rc == 0
    assert before == after
    payload = json.loads(capsys.readouterr().out)
    assert payload["language"] == "python"


def test_plan_prints_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _host(tmp_path)
    rc = main(["plan", "--root", str(root)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["managed_root"] == "evals/_evalglass"


def test_unknown_command_errors(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["frobnicate", "--root", str(tmp_path)])


def test_install_vendors_runtime(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    host = tmp_path / "host"
    host.mkdir()
    rc = main(["install", "--root", str(host)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["managed_root"] == "evals/_evalglass"
    assert (host / "evals" / "_evalglass" / "core" / "engine.py").is_file()
    assert (host / "evals" / "_evalglass" / "vendor-manifest.json").is_file()
    assert (host / "evals" / "evalglass.lock").is_file()
    # install also scaffolds host-owned assets (informational defaults).
    assert (host / "evals" / "evalglass.yaml").is_file()
    assert (host / "evals" / "authority.json").is_file()
    assert "evals/evalglass.yaml" in payload["scaffolded"]


def test_revendor_dry_run_prints_plan_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = tmp_path / "host"
    host.mkdir()
    main(["install", "--root", str(host)])
    capsys.readouterr()
    rc = main(["revendor", "--root", str(host), "--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["replace"] == []
    assert payload["add"] == []


def test_revendor_refuses_clobber_without_confirm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = tmp_path / "host"
    host.mkdir()
    main(["install", "--root", str(host)])
    capsys.readouterr()
    # A same-version re-vendor does not replace engine.py, so a host edit to it is detected
    # but not clobbered: the command succeeds and the edit survives (the deep clobber-refusal
    # path is covered in test_revendor.py).
    engine = host / "evals" / "_evalglass" / "core" / "engine.py"
    engine.write_text(engine.read_text() + "\n# host edit\n", encoding="utf-8")
    rc = main(["revendor", "--root", str(host)])
    assert rc == 0
    assert "# host edit" in engine.read_text()


def test_module_invocation_works(tmp_path: Path) -> None:
    """The documented ``python -m evalglass.installer`` surface must run (needs __main__.py)."""
    import subprocess
    import sys

    root = _host(tmp_path)
    result = subprocess.run(  # noqa: S603 — fixed interpreter, no shell, test-only
        [sys.executable, "-m", "evalglass.installer", "discover", "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["language"] == "python"
