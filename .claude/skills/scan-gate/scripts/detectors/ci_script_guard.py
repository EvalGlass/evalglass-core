"""CI/script guard detector (SG-P1-5) — built-in, no-network.

On the diff's changed CI workflows and shell scripts, catches high-confidence
verdict spoofing / failure suppression:
  * grep-based verdicts (`grep ... && exit 0`);
  * quality-gate failure suppression (`<gate> || true`, `<gate> || exit 0`);
  * `continue-on-error: true` (WARN — may legitimately apply to a non-gate step).

Pattern-based and scoped to changed lines of ci/scripts files to keep false
positives (and drag) low. actionlint/ShellCheck can attach later as main-profile
enhancements.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.contracts import Finding, Severity, ToolLedgerEntry
from scripts.detectors.base import DetectorResult
from scripts.detectors.path_classifier import classify
from scripts.diffpack import DiffPack
from scripts.policy import Policy

VERSION = "0.1.0"

# Tool names that indicate a quality gate; failure-suppression after these is a
# verdict bypass. Kept to concrete tools so ordinary `rm ... || true` is ignored.
_GATE = (
    r"(?:pytest|scan-?gate|ruff|mypy|bandit|gitleaks|semgrep|trivy|pip-audit|actionlint|shellcheck)"
)

_FAIL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"grep\b.*\bexit\s+0\b"),  # grep-based verdict
    re.compile(rf"(?i){_GATE}\b.*\|\|\s*true\b"),  # gate || true
    re.compile(rf"(?i){_GATE}\b.*\|\|\s*exit\s+0\b"),  # gate || exit 0
]
_WARN_CONTINUE_ON_ERROR = re.compile(r"(?i)continue-on-error\s*:\s*true")


_BLOCK_SCALARS = {"|", ">", "|-", ">-", "|+", ">+", ""}


def _added_linenos(added_lines: tuple[tuple[int, int], ...]) -> set[int]:
    nums: set[int] = set()
    for start, count in added_lines:
        nums.update(range(start, start + count))
    return nums


def _executable_shell_lines(lines: list[str]) -> set[int]:
    return {
        i for i, line in enumerate(lines, 1) if line.strip() and not line.lstrip().startswith("#")
    }


def _executable_yaml_lines(lines: list[str]) -> set[int]:
    """Line numbers that carry runnable shell: `run:` inline commands and the
    bodies of `run: |` / `run: >` block scalars (so comments / step names are excluded)."""
    executable: set[int] = set()
    block_indent: int | None = None
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            if stripped == "":
                continue
            if indent > block_indent:
                if not stripped.startswith("#"):
                    executable.add(i)
                continue
            block_indent = None  # block ended; process this line below
        match = re.match(r"^\s*(?:-\s*)?run:\s*(.*)$", line)
        if match:
            rest = match.group(1).strip()
            if rest in _BLOCK_SCALARS:
                block_indent = indent
            elif not rest.startswith("#"):
                executable.add(i)
    return executable


def run(diff_pack: DiffPack, policy: Policy, repo_root: Path | str) -> DetectorResult:
    repo_root = Path(repo_root)
    table = classify(diff_pack, policy)
    findings: list[Finding] = []
    blocked: list[str] = []

    def add(
        rule_id: str, severity: Severity, surface: str, evidence: str, file: str, line: int
    ) -> None:
        findings.append(
            Finding(
                id=f"SG-CI-{len(findings) + 1:04d}",
                rule_id=rule_id,
                severity=severity,
                surface=surface,
                evidence=evidence,
                tool="ci_script_guard",
                tool_version=VERSION,
                policy_version=policy.version,
                recommendation=(
                    "Let the gate's real exit code decide; do not suppress or grep-spoof "
                    "the verdict."
                ),
                file=file,
                line=line,
            )
        )

    for f in diff_pack.files:
        if f.change_type == "deleted" or f.is_binary:
            continue
        groups = table[f.path]
        in_ci = "ci" in groups
        in_scripts = "scripts" in groups
        if not (in_ci or in_scripts):
            continue
        abs_path = repo_root / f.path
        if abs_path.is_symlink() or not abs_path.is_file():
            continue
        try:
            lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            blocked.append(f"ci_script_guard: cannot read {f.path}: {exc.__class__.__name__}")
            continue

        surface = "ci" if in_ci else "scripts"
        is_yaml = f.path.endswith((".yml", ".yaml"))
        executable = _executable_yaml_lines(lines) if is_yaml else _executable_shell_lines(lines)
        # A rename into a guarded group has no added_lines (pure -M rename), but the
        # whole file is newly active here -> scan all lines.
        if f.change_type == "renamed":
            candidates = set(range(1, len(lines) + 1))
        else:
            candidates = _added_linenos(f.added_lines)

        for lineno in sorted(candidates):
            if not (1 <= lineno <= len(lines)):
                continue
            text = lines[lineno - 1]
            if lineno in executable and any(p.search(text) for p in _FAIL_PATTERNS):
                add(
                    "ci.no_verdict_spoof",
                    Severity.FAIL,
                    surface,
                    "verdict spoof / gate failure suppression",
                    f.path,
                    lineno,
                )
                continue
            if in_ci and not text.lstrip().startswith("#") and _WARN_CONTINUE_ON_ERROR.search(text):
                add(
                    "ci.continue_on_error",
                    Severity.WARN,
                    "ci",
                    "continue-on-error: true may bypass a gate",
                    f.path,
                    lineno,
                )

    ledger = [
        ToolLedgerEntry(
            tool="ci_script_guard",
            version=VERSION,
            network="disabled",
            adapter_status="completed",
            findings_count=len(findings),
        )
    ]
    return DetectorResult(findings=findings, ledger=ledger, blocked_reasons=blocked)
