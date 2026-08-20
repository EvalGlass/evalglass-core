"""Imports/effects detector (SG-P1-2) — the core trust check.

Catches, on the diff's changed Python files:
  * vendor/LLM SDK imports and effects in required-tier code (by *reusing* the
    repo's tools/check_core_isolation.py, so the forbidden surface stays in one
    place);
  * optional-lane imports in required-tier code;
  * verdict-literal logic (pass/fail/blocked/informational) in harness/adapters,
    i.e. duplicating the Verdict Engine.

Stdlib `ast` only (no-network, no extra dependency). Fails closed: a missing
core-isolation tool or an unparseable required file becomes BLOCKED, never a
silent miss.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from scripts.contracts import Finding, Severity, ToolLedgerEntry
from scripts.detectors.base import DetectorResult
from scripts.detectors.path_classifier import classify
from scripts.diffpack import DiffPack
from scripts.policy import Policy

VERSION = "0.1.0"

VERDICT_LITERALS = frozenset({"pass", "fail", "blocked", "informational"})
_VERDICT_FUNC_HINTS = ("verdict", "decide", "gate")
_OPTIONAL_SEGMENTS = frozenset({"optional", "extensions"})
# The no-effects rule targets the effect-free core source only, not the
# core-isolation *tests* (which legitimately use I/O) that also live in required_tier.
_CORE_SOURCE_PREFIX = "src/evalglass/core/"
_HELPER_PATH = "tools/check_core_isolation.py"

# Network / LLM-provider clients a hermetic, offline-by-contract gate skill must
# not import. First-segment match for third-party clients and raw-socket stdlib
# modules; dotted-prefix match for the network corners of otherwise-fine stdlib
# packages (urllib.parse, http.cookies etc. stay allowed). subprocess/open are
# deliberately absent: gate skills legitimately shell out (git) and read files.
_NETWORK_ROOTS = frozenset(
    {
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "websocket",
        "websockets",
        "socket",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "openai",
        "anthropic",
        "cohere",
        "mistralai",
        "litellm",
        "groq",
        "langchain",
        "langchain_core",
        "langchain_community",
        "boto3",
        "botocore",
        "paramiko",
    }
)
_NETWORK_DOTTED = ("urllib.request", "urllib.error", "http.client", "xmlrpc.client")

_RECOMMENDATIONS = {
    "required.no_live_model_imports": (
        "Move vendor/LLM SDK usage to an adapter outside the Evaluation Core."
    ),
    "core.no_effects": (
        "Remove the effect; the Evaluation Core must be deterministic and effect-free."
    ),
    "required.no_optional_lane_imports": (
        "Required-tier code must not import optional-lane packages."
    ),
    "verdict.single_engine": "Only the Verdict Engine may produce pass/fail/blocked/informational.",
    "skills.no_network_imports": (
        "Gate skills are hermetic/offline; remove the network/provider import or move it behind an "
        "opt-in adapter outside the required scan path."
    ),
}


def _load_core_isolation(repo_root: Path) -> ModuleType | None:
    tool = repo_root / "tools" / "check_core_isolation.py"
    if not tool.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_eg_core_isolation", tool)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses in the tool can resolve their module.
    sys.modules[spec.name] = module
    # Never write a .pyc into the scanned repo: the scanner must not mutate the
    # subject it measures (and it would make the diff pack nondeterministic).
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _violation_rule(category: str) -> str:
    low = category.lower()
    if any(k in low for k in ("vendor", "sdk", "llm", "framework")):
        return "required.no_live_model_imports"
    return "core.no_effects"


def _is_verdict_const(node: ast.expr | None) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in VERDICT_LITERALS
    )


def _target_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _verdict_hits(tree: ast.AST) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_verdict_const(node.value):
            for target in node.targets:
                name = _target_name(target)
                if name and "verdict" in name.lower():
                    hits.append((node.lineno, node.value.value))  # type: ignore[attr-defined]
        elif isinstance(node, ast.AnnAssign) and _is_verdict_const(node.value):
            name = _target_name(node.target)
            if name and "verdict" in name.lower():
                hits.append((node.lineno, node.value.value))  # type: ignore[union-attr]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(
            h in node.name.lower() for h in _VERDICT_FUNC_HINTS
        ):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and _is_verdict_const(sub.value):
                    hits.append((sub.lineno, sub.value.value))  # type: ignore[union-attr]
    return hits


def _optional_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Flag optional-lane imports, including relative and `from evalglass import optional` forms."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                segs = alias.name.split(".")
                if "evalglass" in segs and any(s in _OPTIONAL_SEGMENTS for s in segs):
                    hits.append((node.lineno, alias.name))
                    break
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            relative = node.level > 0
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                segs = full.split(".")
                if any(s in _OPTIONAL_SEGMENTS for s in segs) and (relative or "evalglass" in segs):
                    hits.append((node.lineno, ("." * node.level) + full))
                    break
    return hits


def _is_network_module(name: str) -> bool:
    if not name:
        return False
    if name.split(".", 1)[0] in _NETWORK_ROOTS:
        return True
    return any(name == d or name.startswith(d + ".") for d in _NETWORK_DOTTED)


def _network_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Flag imports of network/LLM-provider clients (for hermetic gate skills)."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_network_module(alias.name):
                    hits.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base and _is_network_module(base):
                hits.append((node.lineno, base))
                continue
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                if _is_network_module(full):
                    hits.append((node.lineno, full))
                    break
    return hits


def run(diff_pack: DiffPack, policy: Policy, repo_root: Path | str) -> DetectorResult:
    repo_root = Path(repo_root)
    table = classify(diff_pack, policy)
    core_iso = _load_core_isolation(repo_root)
    helper_changed = any(f.path == _HELPER_PATH for f in diff_pack.files)

    findings: list[Finding] = []
    blocked: list[str] = []
    core_iso_blocked_reported = False

    def add(
        rule_id: str,
        surface: str,
        evidence: str,
        file: str,
        line: int,
        tool: str,
        tool_version: str,
    ) -> None:
        findings.append(
            Finding(
                id=f"SG-IMP-{len(findings) + 1:04d}",
                rule_id=rule_id,
                severity=Severity.FAIL,
                surface=surface,
                evidence=evidence,
                tool=tool,
                tool_version=tool_version,
                policy_version=policy.version,
                recommendation=_RECOMMENDATIONS[rule_id],
                file=file,
                line=line,
            )
        )

    for f in diff_pack.files:
        if f.change_type == "deleted" or not f.path.endswith(".py"):
            continue
        groups = table[f.path]
        in_required = "required_tier" in groups
        in_harness_adapters = "harness" in groups or "adapters" in groups
        in_skills = "skills" in groups
        if not (in_required or in_harness_adapters or in_skills):
            continue
        abs_path = repo_root / f.path
        if not abs_path.is_file():
            continue
        try:
            tree = ast.parse(abs_path.read_text(encoding="utf-8"), filename=f.path)
        except (OSError, SyntaxError) as exc:
            blocked.append(f"imports_effects: cannot analyze {f.path}: {exc.__class__.__name__}")
            continue

        if in_required:
            # Effects/vendor scan applies to the effect-free core source only
            # (tests/core_isolation/** are required_tier for routing but may use I/O).
            if f.path.startswith(_CORE_SOURCE_PREFIX):
                if helper_changed:
                    if not core_iso_blocked_reported:
                        blocked.append(
                            "imports_effects: tools/check_core_isolation.py is modified in "
                            "this diff; cannot trust it to verify core isolation"
                        )
                        core_iso_blocked_reported = True
                elif core_iso is None:
                    if not core_iso_blocked_reported:
                        blocked.append(
                            "imports_effects: tools/check_core_isolation.py not found; "
                            "cannot verify core isolation"
                        )
                        core_iso_blocked_reported = True
                else:
                    try:
                        violations = core_iso.scan([abs_path])
                    except SyntaxError:
                        blocked.append(f"imports_effects: cannot analyze {f.path}: SyntaxError")
                        violations = []
                    for v in violations:
                        add(
                            _violation_rule(v.category),
                            "required_tier",
                            f"{v.kind} {v.name!r} ({v.category})",
                            f.path,
                            v.line,
                            "check_core_isolation",
                            "vendored",
                        )
            for line, mod in _optional_imports(tree):
                add(
                    "required.no_optional_lane_imports",
                    "required_tier",
                    f"imports optional-lane module {mod!r}",
                    f.path,
                    line,
                    "imports_effects",
                    VERSION,
                )

        if in_harness_adapters:
            surface = "harness" if "harness" in groups else "adapters"
            for line, literal in _verdict_hits(tree):
                add(
                    "verdict.single_engine",
                    surface,
                    f"verdict literal {literal!r} decided outside the Verdict Engine",
                    f.path,
                    line,
                    "imports_effects",
                    VERSION,
                )

        if in_skills:
            for line, mod in _network_imports(tree):
                add(
                    "skills.no_network_imports",
                    "skills",
                    f"hermetic gate skill imports network/provider client {mod!r}",
                    f.path,
                    line,
                    "imports_effects",
                    VERSION,
                )

    ledger = [
        ToolLedgerEntry(
            tool="imports_effects",
            version=VERSION,
            network="disabled",
            adapter_status="completed",
            findings_count=len(findings),
        )
    ]
    return DetectorResult(findings=findings, ledger=ledger, blocked_reasons=blocked)
