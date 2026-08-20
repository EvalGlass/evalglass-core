"""EG-MDU-1 — discovery recall for mainstream agentic-framework idioms.

v0.1.0 discovery recognised only direct OpenAI/Anthropic SDK calls, so a LangChain/LangGraph/
LiteLLM app (the mainstream stack) surfaced 0 call sites. These tests pin the broadened recall
with matched sensitivity (framework idioms are found) and specificity (plain-Python `.invoke`
without any framework import is NOT flagged).
"""

from __future__ import annotations

from pathlib import Path

from evalglass.installer.contracts import HostDiscoveryReport
from evalglass.installer.discovery import discover


def _host(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "host"
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname='h'\n", encoding="utf-8")
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def _callees(report: HostDiscoveryReport) -> list[str]:
    return [str(s["callee"]) for s in report.llm_call_sites]


def test_langchain_structured_output_invoke_is_found(tmp_path: Path) -> None:
    root = _host(
        tmp_path,
        {
            "src/agent.py": (
                "from langchain_litellm import ChatLiteLLM\n"
                "from pydantic import BaseModel\n"
                "class Out(BaseModel):\n    answer: str\n"
                "def run(model, q):\n"
                "    return model.with_structured_output(Out).invoke(q)\n"
            )
        },
    )
    report = discover(root)
    assert report.llm_call_sites, "a with_structured_output().invoke() chain must be discovered"
    assert any("with_structured_output" in c for c in _callees(report))


def test_chat_model_construction_is_found(tmp_path: Path) -> None:
    root = _host(
        tmp_path,
        {"src/m.py": "from langchain_openai import ChatOpenAI\nllm = ChatOpenAI(model='gpt-4o')\n"},
    )
    report = discover(root)
    assert any(c.rsplit(".", 1)[-1] == "ChatOpenAI" for c in _callees(report))


def test_framework_gated_invoke_is_found(tmp_path: Path) -> None:
    root = _host(
        tmp_path,
        {
            "src/g.py": (
                "from langgraph.graph import StateGraph\n"
                "def go(graph, s):\n    return graph.invoke(s)\n"
            )
        },
    )
    report = discover(root)
    assert any(c.endswith(".invoke") for c in _callees(report))


def test_plain_invoke_without_framework_is_not_flagged(tmp_path: Path) -> None:
    # Specificity: a generic `.invoke` with no framework import must NOT be a false positive.
    root = _host(
        tmp_path,
        {"src/plain.py": "def go(runner, x):\n    return runner.invoke(x)\n"},
    )
    report = discover(root)
    assert report.llm_call_sites == [], "plain-Python .invoke must not be flagged as an LLM call"


def test_direct_sdk_still_detected(tmp_path: Path) -> None:
    # Regression: the original direct-SDK path is unchanged, framework or not.
    root = _host(
        tmp_path,
        {
            "src/o.py": (
                "import openai\n"
                "c = openai.OpenAI()\n"
                "def ask(q):\n    return c.chat.completions.create(model='gpt', messages=[])\n"
            )
        },
    )
    report = discover(root)
    assert any("chat.completions.create" in c for c in _callees(report))


def test_no_dead_end_when_framework_imported_but_no_call(tmp_path: Path) -> None:
    # framework imported, but no invoke/construct/structured-output → an actionable open question,
    # never a bare "0 call sites" dead-end.
    root = _host(
        tmp_path,
        {"src/x.py": "from langchain_core.messages import SystemMessage\nX = SystemMessage\n"},
    )
    report = discover(root)
    assert report.llm_call_sites == []
    # Never dead-end on a bare "0": point the host at authoring metrics directly.
    assert any("author them" in q for q in report.open_questions)


def test_eval_assets_excludes_pycache_and_pyc(tmp_path: Path) -> None:
    root = _host(tmp_path, {})
    (root / "evals" / "evaluators" / "__pycache__").mkdir(parents=True)
    (root / "evals" / "evaluators" / "__pycache__" / "m.cpython-312.pyc").write_text("x")
    (root / "evals" / "evaluators" / "scorer.py").write_text("# host scorer\n")
    report = discover(root)
    assert "evals/evaluators/scorer.py" in report.eval_assets
    assert not any(".pyc" in a or "__pycache__" in a for a in report.eval_assets)
