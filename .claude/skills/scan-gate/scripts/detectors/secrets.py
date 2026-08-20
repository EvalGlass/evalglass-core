"""Secrets detector (SG-P1-3) — built-in, no-network, redacted.

Scans only the diff's added lines (pre-existing secrets are a baseline, not
re-flagged) for a small set of high-confidence credential shapes. Findings never
contain the secret value. A built-in regex engine keeps the required/fast lanes
hermetic and the test suite offline; Gitleaks may attach later as an optional
`main`-profile enhancement.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from scripts.contracts import Finding, Severity, ToolLedgerEntry
from scripts.detectors.base import DetectorResult
from scripts.diffpack import DiffPack
from scripts.policy import Policy

VERSION = "0.1.0"

# (name, regex, value_group, is_generic). value_group=1 captures the credential in
# group 1 (for placeholder/entropy filtering); 0 means the whole match. Generic
# (keyword-based) patterns additionally require a digit in the value to avoid
# flagging ordinary identifiers/passphrases.
_PATTERNS: list[tuple[str, re.Pattern[str], int, bool]] = [
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"), 0, False),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0, False),
    ("github-token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}\b"), 0, False),
    ("github-pat", re.compile(r"\bgithub_pat_[0-9A-Za-z_]{22,}\b"), 0, False),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"), 0, False),
    ("slack-token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"), 0, False),
    (
        "generic-secret-assignment",
        re.compile(
            r"(?i)(?:api[_-]?key|secret|token|password|passwd|access[_-]?key)\s*[:=]\s*"
            r"['\"]([^'\"]{16,})['\"]"
        ),
        1,
        True,
    ),
    (
        "generic-secret-assignment-unquoted",
        re.compile(
            r"(?i)(?:api[_-]?key|secret|token|password|passwd|access[_-]?key)\s*[:=]\s*"
            r"([A-Za-z0-9_\-/+.]{16,})\b"
        ),
        1,
        True,
    ),
]

# Values that look like documentation/placeholders rather than real credentials.
_PLACEHOLDER = re.compile(
    r"(?i)example|placeholder|change[_-]?me|your[_-]|x{4,}|redacted|dummy|<[^>]+>|\.\.\.|"
    r"fake|sample|sk-test|test[_-]?(?:key|token|secret)"
)


def _added_linenos(added_lines: tuple[tuple[int, int], ...]) -> set[int]:
    nums: set[int] = set()
    for start, count in added_lines:
        nums.update(range(start, start + count))
    return nums


def run(diff_pack: DiffPack, policy: Policy, repo_root: Path | str) -> DetectorResult:
    repo_root = Path(repo_root)
    findings: list[Finding] = []
    blocked: list[str] = []

    for f in diff_pack.files:
        if f.change_type == "deleted" or f.is_binary:
            continue
        abs_path = repo_root / f.path
        # A symlink's git blob is its target string; never follow it to scan the
        # target file (that would leave the diff and be nondeterministic).
        if abs_path.is_symlink():
            try:
                lines = [os.readlink(abs_path)]
            except OSError as exc:
                blocked.append(f"secrets: cannot read symlink {f.path}: {exc.__class__.__name__}")
                continue
        else:
            if not abs_path.is_file():
                continue
            try:
                lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                blocked.append(f"secrets: cannot read {f.path}: {exc.__class__.__name__}")
                continue

        wanted = _added_linenos(f.added_lines)
        for lineno in sorted(wanted):
            if not (1 <= lineno <= len(lines)):
                continue
            text = lines[lineno - 1]
            for name, pattern, group, is_generic in _PATTERNS:
                match = pattern.search(text)
                if not match:
                    continue
                candidate = match.group(group) if group else match.group(0)
                if _PLACEHOLDER.search(candidate):
                    continue
                if is_generic and not any(c.isdigit() for c in candidate):
                    continue  # ordinary identifier/passphrase, not a credential
                findings.append(
                    Finding(
                        id=f"SG-SEC-{len(findings) + 1:04d}",
                        rule_id="secrets.no_new_secrets",
                        severity=Severity.FAIL,
                        surface="secrets",
                        evidence=f"possible {name} on changed line {lineno} (value redacted)",
                        tool="secrets",
                        tool_version=VERSION,
                        policy_version=policy.version,
                        recommendation=(
                            "Remove the credential; use an environment variable or secret store."
                        ),
                        file=f.path,
                        line=lineno,
                    )
                )
                break  # one finding per line is enough

    ledger = [
        ToolLedgerEntry(
            tool="secrets",
            version=VERSION,
            network="disabled",
            adapter_status="completed",
            findings_count=len(findings),
        )
    ]
    return DetectorResult(findings=findings, ledger=ledger, blocked_reasons=blocked)
