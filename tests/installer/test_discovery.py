"""S1 (EG-M3-1) — conservative, READ-ONLY host discovery.

Discovery inspects a host repo and proposes nothing yet; it must not mutate the
host (acceptance: "Discovery output is reviewable before mutation", "Skill does
not run runtime evaluation during planning"). It detects repo shape, likely LLM
call sites (via the `ast` module over source text — never importing/executing
host code), existing eval assets, CI, ignore files, and surfaces unknown data
boundaries as DataPolicyPrompts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from evalglass.installer.contracts import HostDiscoveryReport
from evalglass.installer.discovery import discover


def _snapshot(root: Path) -> dict[str, str]:
    """Map every file under root to a content hash (to prove read-only discovery)."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _python_host(tmp_path: Path) -> Path:
    root = tmp_path / "host"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "import openai\n"
        "client = openai.OpenAI()\n"
        "def ask(q):\n"
        "    return client.chat.completions.create(model='gpt', messages=[{'role':'user'}])\n",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(".venv/\n__pycache__/\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "junk.py").write_text("client.chat.completions.create()\n", encoding="utf-8")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    return root


def test_discovery_is_read_only(tmp_path: Path) -> None:
    root = _python_host(tmp_path)
    before = _snapshot(root)
    discover(root)
    after = _snapshot(root)
    assert before == after, "discovery mutated the host repo"


def test_discovery_detects_python_and_call_sites(tmp_path: Path) -> None:
    root = _python_host(tmp_path)
    report = discover(root)
    assert isinstance(report, HostDiscoveryReport)
    assert report.language == "python"
    # The real call site in src/app.py is found...
    files = {c["file"] for c in report.llm_call_sites}
    assert "src/app.py" in files
    # ...but the ignored .venv/ is NOT scanned (ignore-file handling).
    assert not any(".venv" in c["file"] for c in report.llm_call_sites)


def test_discovery_call_sites_carry_their_classification_kind(tmp_path: Path) -> None:
    """Each call site exposes the ``kind`` the scanner already classifies it as (sdk /
    structured_output / model_construction / invoke), so a reviewer/scaffolder can act on it
    instead of re-deriving it. The fixture's ``client.chat.completions.create`` is a direct SDK
    call."""
    root = _python_host(tmp_path)
    report = discover(root)
    app_sites = [c for c in report.llm_call_sites if c["file"] == "src/app.py"]
    assert app_sites, "expected the direct SDK call site to be found"
    assert all("kind" in c for c in report.llm_call_sites), "call sites must carry a 'kind'"
    assert app_sites[0]["kind"] == "sdk"


def test_discovery_detects_ci_and_ignore(tmp_path: Path) -> None:
    root = _python_host(tmp_path)
    report = discover(root)
    assert any("ci.yml" in c for c in report.ci_configs)
    assert ".gitignore" in report.ignore_files


def test_discovery_unknown_data_boundary_becomes_prompt(tmp_path: Path) -> None:
    """An existing trace/log with no declared policy is surfaced as a question, never assumed."""
    root = _python_host(tmp_path)
    (root / "logs").mkdir()
    (root / "logs" / "traces.jsonl").write_text('{"trace_id":"a"}\n', encoding="utf-8")
    report = discover(root)
    assert report.data_policy_prompts, "an unknown data boundary must surface a prompt"
    # The skill never silently answers the prompt to 'permitted'.
    for prompt in report.data_policy_prompts:
        assert "permitted" not in (prompt.choices[:1] or [""]) or len(prompt.choices) > 1


def test_discovery_empty_repo_has_no_call_sites(tmp_path: Path) -> None:
    """Specificity: a repo with no LLM calls reports none (no false positives)."""
    root = tmp_path / "empty"
    (root / "src").mkdir(parents=True)
    (root / "src" / "math.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    report = discover(root)
    assert report.llm_call_sites == []


def test_discovery_ignores_unparseable_python(tmp_path: Path) -> None:
    """A syntactically broken host file must not crash discovery (it is host code, not ours)."""
    root = tmp_path / "host"
    (root / "src").mkdir(parents=True)
    (root / "src" / "broken.py").write_text("def (:\n", encoding="utf-8")
    report = discover(root)  # must not raise
    assert report.language == "python"


def test_discovery_honors_path_qualified_ignore(tmp_path: Path) -> None:
    """A path-qualified .gitignore dir (``src/generated/``) is honored, not just bare names."""
    root = tmp_path / "host"
    (root / "src" / "generated").mkdir(parents=True)
    (root / "src" / "generated" / "client.py").write_text(
        "client.chat.completions.create()\n", encoding="utf-8"
    )
    (root / "src" / "app.py").write_text("client.chat.completions.create()\n", encoding="utf-8")
    (root / ".gitignore").write_text("src/generated/\n", encoding="utf-8")
    report = discover(root)
    files = {c["file"] for c in report.llm_call_sites}
    assert "src/app.py" in files
    assert not any("generated" in f for f in files), "path-qualified ignore not honored"


def test_discovery_reports_top_level_eval_config_as_host_truth(tmp_path: Path) -> None:
    """An existing top-level evals/ config is host-owned truth — discovery must surface it."""
    root = tmp_path / "host"
    (root / "evals").mkdir(parents=True)
    (root / "evals" / "evalglass.yaml").write_text("run:\n  id: x\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    report = discover(root)
    assert report.has_evals_dir
    assert "evals/evalglass.yaml" in report.eval_assets


def test_discovery_excludes_managed_dir_from_eval_assets(tmp_path: Path) -> None:
    """The managed runtime (evals/_evalglass/**) is framework-managed, not host truth."""
    root = tmp_path / "host"
    (root / "evals" / "_evalglass" / "core").mkdir(parents=True)
    (root / "evals" / "_evalglass" / "core" / "x.py").write_text("y = 1\n", encoding="utf-8")
    (root / "evals" / "datasets").mkdir()
    (root / "evals" / "datasets" / "gold.jsonl").write_text("{}\n", encoding="utf-8")
    report = discover(root)
    assert "evals/datasets/gold.jsonl" in report.eval_assets
    assert not any("_evalglass" in a for a in report.eval_assets)
