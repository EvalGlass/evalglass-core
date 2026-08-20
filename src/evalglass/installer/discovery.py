"""Conservative, read-only host discovery (EG-M3-1).

``discover`` inspects a host repo and returns a :class:`HostDiscoveryReport`. It is
strictly **read-only** (the EGTS proof snapshots the tree before/after), parses
Python with the stdlib ``ast`` module over *source text* — it never imports or
executes host code or any LLM SDK — and honors the repo's ignore files. Unknown
data boundaries (recorded traces/logs with no declared policy) are surfaced as
:class:`DataPolicyPrompt`\\ s, never silently assumed permitted. Stdlib-only.
"""

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path

from evalglass.installer.contracts import DataPolicyPrompt, HostDiscoveryReport

# Attribute-chain fragments that strongly suggest a direct-SDK LLM call (provider-neutral).
_LLM_CALL_HINTS = (
    "chat.completions.create",
    "completions.create",
    "messages.create",
    "responses.create",
)
_LLM_SDK_NAMES = ("openai", "anthropic")

# Mainstream agentic frameworks. Their idiom is not `x.create(...)` but a chat-model object
# invoked via `.invoke`/`.ainvoke`/`with_structured_output(...)`. A bare `.invoke` is too generic
# to flag on its own (files, HTTP clients, graphs all have one), so the invoke-verbs are only
# treated as LLM sites when the file also imports a framework or constructs a chat model — that
# framework *context* is what keeps precision high. Generic to any app on these stacks; no domain.
_FRAMEWORK_IMPORT_ROOTS = (
    "langchain",
    "langgraph",
    "langchain_core",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_litellm",
    "langchain_community",
    "litellm",
    "llama_index",
    "llama_cpp",
    "dspy",
    "crewai",
    "autogen",
    "semantic_kernel",
    "pydantic_ai",
    "haystack",
    "instructor",
)
#: Chat-model constructor names across the common frameworks (last dotted segment).
_CHAT_MODEL_CTORS = frozenset(
    {
        "ChatOpenAI",
        "ChatAnthropic",
        "ChatLiteLLM",
        "AzureChatOpenAI",
        "ChatBedrock",
        "ChatBedrockConverse",
        "ChatVertexAI",
        "ChatGoogleGenerativeAI",
        "ChatMistralAI",
        "ChatCohere",
        "ChatOllama",
        "ChatGroq",
        "ChatFireworks",
        "ChatTogether",
        "init_chat_model",
    }
)
#: Invocation verbs that mark an LLM call *when framework context is present*.
_INVOKE_VERBS = (".invoke", ".ainvoke", ".stream", ".astream", ".batch", ".abatch")
#: The structured-output binder — a very strong, framework-neutral signal on its own.
_STRUCTURED_OUTPUT = "with_structured_output"
_ALWAYS_IGNORE = {".git", ".hg", ".svn"}
_TRACE_DIR_NAMES = {"logs", "traces", "trace"}
#: The managed runtime dir under a host's evals/ — framework-managed, never host truth.
_MANAGED_DIR = "_evalglass"


def _read_ignores(root: Path) -> tuple[set[str], list[str], list[str]]:
    """Return (ignored dir names, ignore globs, ignore-file relpaths found)."""
    ignore_dirs = set(_ALWAYS_IGNORE)
    ignore_globs: list[str] = []
    found: list[str] = []
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        found.append(".gitignore")
        for raw in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("/"):
                ignore_dirs.add(line.rstrip("/").lstrip("/"))
            else:
                ignore_globs.append(line.lstrip("/"))
    return ignore_dirs, ignore_globs, found


def _is_ignored(rel: Path, ignore_dirs: set[str], ignore_globs: list[str]) -> bool:
    rel_posix = rel.as_posix()
    for d in ignore_dirs:
        if "/" in d:
            # A path-qualified dir pattern (e.g. "src/generated") matches that subtree.
            if rel_posix == d or rel_posix.startswith(f"{d}/"):
                return True
        elif d in rel.parts:
            # A bare name (e.g. ".venv") matches any path component.
            return True
    return any(fnmatch.fnmatch(rel.name, g) or fnmatch.fnmatch(rel_posix, g) for g in ignore_globs)


def _dotted(node: ast.expr) -> str:
    """Flatten an attribute/name chain (``a.b.c``) to a dotted string; '' if not a chain."""
    parts: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    elif isinstance(cur, ast.Call):
        inner = _dotted(cur.func)
        if inner:
            parts.append(inner)
    return ".".join(reversed(parts))


def _looks_like_direct_sdk_call(callee: str) -> bool:
    """A direct OpenAI/Anthropic-style SDK call — flagged regardless of framework context."""
    if any(hint in callee for hint in _LLM_CALL_HINTS):
        return True
    head = callee.split(".", 1)[0]
    return head in _LLM_SDK_NAMES and callee.endswith((".create", ".generate", ".complete"))


def _file_framework_context(tree: ast.Module) -> bool:
    """True if the module imports an agentic framework or constructs a chat model.

    This context is what lets us treat an otherwise-generic ``.invoke``/``.ainvoke`` as an LLM
    call site without over-flagging plain-Python ``.invoke`` calls.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".", 1)[0]
            if root in _FRAMEWORK_IMPORT_ROOTS:
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in _FRAMEWORK_IMPORT_ROOTS:
                    return True
        elif isinstance(node, ast.Call):
            tail = _dotted(node.func).rsplit(".", 1)[-1]
            if tail in _CHAT_MODEL_CTORS:
                return True
    return False


def _classify_call(callee: str, *, framework_context: bool) -> str | None:
    """Return a short 'kind' for an LLM call site, or None if it is not one."""
    if _looks_like_direct_sdk_call(callee):
        return "sdk"
    if _STRUCTURED_OUTPUT in callee:
        return "structured_output"
    if _dotted_tail(callee) in _CHAT_MODEL_CTORS:
        return "model_construction"
    if framework_context and callee.endswith(_INVOKE_VERBS):
        return "invoke"
    return None


def _dotted_tail(callee: str) -> str:
    return callee.rsplit(".", 1)[-1]


def _scan_call_sites(path: Path, rel: str) -> tuple[list[dict[str, object]], bool]:
    """Return (call sites, framework_seen) for one Python file.

    ``framework_seen`` lets the caller avoid a dead-end "0 call sites" when a repo clearly uses a
    framework but nothing matched (a safety net for idioms this scanner does not yet know).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (SyntaxError, ValueError):
        # Host source we cannot parse is the host's concern, not a discovery failure.
        return [], False
    framework_context = _file_framework_context(tree)
    sites: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if not callee:
                continue
            kind = _classify_call(callee, framework_context=framework_context)
            if kind is not None:
                sites.append({"file": rel, "line": node.lineno, "callee": callee, "kind": kind})
    return sites, framework_context


def discover(root: Path) -> HostDiscoveryReport:
    """Inspect ``root`` read-only and return a reviewable discovery report."""
    root = Path(root)
    ignore_dirs, ignore_globs, ignore_files = _read_ignores(root)

    has_python = (root / "pyproject.toml").is_file() or (root / "setup.py").is_file()
    call_sites: list[dict[str, object]] = []
    trace_candidates: list[str] = []
    ci_configs: list[str] = []
    framework_seen = False

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_ignored(rel, ignore_dirs, ignore_globs):
            continue
        rel_str = rel.as_posix()
        if path.suffix == ".py":
            has_python = True
            sites, fw = _scan_call_sites(path, rel_str)
            call_sites.extend(sites)
            framework_seen = framework_seen or fw
        elif path.suffix == ".jsonl" and (
            rel.parent.name in _TRACE_DIR_NAMES or "trace" in path.stem.lower()
        ):
            trace_candidates.append(rel_str)
        if rel.parts[:2] == (".github", "workflows") and path.suffix in (".yml", ".yaml"):
            ci_configs.append(rel_str)

    has_evals = (root / "evals").is_dir()
    eval_assets: list[str] = []
    if has_evals:
        # Every existing host-owned file under evals/ is host truth to be preserved —
        # top-level config/docs (evalglass.yaml, README.md, ...) and subdir assets alike —
        # except the framework-managed runtime dir (evals/_evalglass/**).
        for p in sorted((root / "evals").rglob("*")):
            rel = p.relative_to(root)
            # Skip the managed runtime and compiled/cache artifacts — they are not host truth
            # and only add noise to the asset inventory.
            if (
                p.is_file()
                and _MANAGED_DIR not in rel.parts
                and "__pycache__" not in rel.parts
                and p.suffix != ".pyc"
            ):
                eval_assets.append(rel.as_posix())

    # Each recorded data source with no declared policy is an open question, never assumed.
    prompts = [
        DataPolicyPrompt(
            subject=tc,
            question=(
                f"{tc!r} is a recorded data source with no declared data policy. "
                "May its contents leave the process (e.g. to a replay subprocess)?"
            ),
            choices=["permitted", "redacted", "forbidden"],
        )
        for tc in trace_candidates
    ]

    open_questions: list[str] = []
    if not eval_assets:
        open_questions.append(
            "No validated gold dataset found; reference metrics stay informational until the "
            "host supplies and validates gold."
        )
    if framework_seen and not call_sites:
        # Never dead-end on a bare "0": the repo clearly uses an agentic framework, so point the
        # host at authoring metrics directly rather than implying there is nothing to evaluate.
        open_questions.append(
            "An agentic framework is imported but no LLM call site matched the scanner's known "
            "idioms; tell the agent which checks this app needs and author them directly against "
            "its output schemas and prompts (see the authoring-a-metric skill)."
        )

    return HostDiscoveryReport(
        root=str(root),
        language="python" if has_python else "unknown",
        has_evals_dir=has_evals,
        llm_call_sites=call_sites,
        trace_candidates=trace_candidates,
        eval_assets=eval_assets,
        ci_configs=ci_configs,
        ignore_files=ignore_files,
        data_policy_prompts=prompts,
        open_questions=open_questions,
    )
