"""Slice 7 (SG-P1-3): secrets detector tests.

Built-in, no-network, redacted, scans only added lines (pre-existing secrets are
a baseline and not re-flagged). Sensitivity: high-confidence credential shapes
on changed lines FAIL. Specificity: placeholders/examples and unchanged lines do
not. Redaction: a finding never contains the secret value.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.detectors import secrets
from scripts.diffpack import ChangedFile, DiffPack
from scripts.policy import load_policy

SKILL_ROOT = Path(__file__).resolve().parent.parent
FAST_POLICY = SKILL_ROOT / "policies" / "evalglass.fast.yml"

# Fake, non-verifiable credential shapes (never real). Avoid placeholder words so
# the specificity filter does not suppress them.
FAKE_AWS = "AKIA1234567890ABCDEF"
FAKE_GH = "ghp_" + "ABCDefgh0123456789ABCDefgh0123456789AB"
FAKE_OPENAI = "sk-ABcd1234EFgh5678IJkl9012MNop"
FAKE_PRIVATE_KEY_HEADER = "-----BEGIN RSA PRIVATE KEY-----"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return tmp_path


def _write(ws: Path, rel: str, content: str) -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return rel


def _pack(
    rel: str, *, added: tuple[tuple[int, int], ...] | None = None, is_binary: bool = False
) -> DiffPack:
    return DiffPack(
        base_ref="b",
        head_ref="WORKTREE",
        files=(
            ChangedFile(
                path=rel,
                change_type="added",
                old_path=None,
                is_binary=is_binary,
                added_lines=added if added is not None else ((1, 10_000),),
                is_untracked=False,
            ),
        ),
    )


def _run(ws: Path, pack: DiffPack) -> secrets.DetectorResult:
    return secrets.run(pack, load_policy(FAST_POLICY), ws)


def _rules(result: secrets.DetectorResult) -> set[str]:
    return {f.rule_id for f in result.findings}


# ----- sensitivity -----------------------------------------------------------


def test_aws_key_fails(ws: Path) -> None:
    rel = _write(ws, "config.py", f'AWS = "{FAKE_AWS}"\n')
    result = _run(ws, _pack(rel))
    assert "secrets.no_new_secrets" in _rules(result)


def test_github_token_fails(ws: Path) -> None:
    rel = _write(ws, "deploy.py", f'token = "{FAKE_GH}"\n')
    assert "secrets.no_new_secrets" in _rules(_run(ws, _pack(rel)))


def test_openai_key_fails(ws: Path) -> None:
    rel = _write(ws, "client.py", f'key = "{FAKE_OPENAI}"\n')
    assert "secrets.no_new_secrets" in _rules(_run(ws, _pack(rel)))


def test_private_key_header_fails(ws: Path) -> None:
    rel = _write(
        ws, "id_rsa", FAKE_PRIVATE_KEY_HEADER + "\nQUJDREVG\n-----END RSA PRIVATE KEY-----\n"
    )
    assert "secrets.no_new_secrets" in _rules(_run(ws, _pack(rel)))


def test_generic_long_secret_assignment_fails(ws: Path) -> None:
    rel = _write(ws, "settings.py", 'API_KEY = "abcdef0123456789ghijklmnop"\n')
    assert "secrets.no_new_secrets" in _rules(_run(ws, _pack(rel)))


# ----- specificity (no false positives) --------------------------------------


def test_placeholder_values_pass(ws: Path) -> None:
    rel = _write(
        ws,
        "example.py",
        'API_KEY = "your-api-key-here"\n'
        'password = "changeme"\n'
        'token = "<YOUR_TOKEN>"\n'
        'demo = "sk-EXAMPLE-not-a-real-key-xxxx"\n',
    )
    assert _run(ws, _pack(rel)).findings == []


def test_short_value_not_flagged(ws: Path) -> None:
    rel = _write(ws, "s.py", 'password = "short"\n')
    assert _run(ws, _pack(rel)).findings == []


def test_secret_on_unchanged_line_not_flagged(ws: Path) -> None:
    # Secret is on line 1, but only line 3 is in the diff's added range.
    rel = _write(ws, "c.py", f'AWS = "{FAKE_AWS}"\n# line2\nx = 3\n')
    result = _run(ws, _pack(rel, added=((3, 1),)))
    assert result.findings == []


def test_binary_file_skipped(ws: Path) -> None:
    rel = _write(ws, "blob.bin", f'AWS="{FAKE_AWS}"\n')
    result = _run(ws, _pack(rel, is_binary=True))
    assert result.findings == []


# ----- redaction + ledger ----------------------------------------------------


def test_finding_redacts_secret_value(ws: Path) -> None:
    rel = _write(ws, "config.py", f'AWS = "{FAKE_AWS}"\n')
    result = _run(ws, _pack(rel))
    blob = " ".join(f.evidence for f in result.findings)
    assert FAKE_AWS not in blob


def test_detector_emits_ledger_entry(ws: Path) -> None:
    rel = _write(ws, "ok.py", "x = 1\n")
    result = _run(ws, _pack(rel))
    assert any(e.tool == "secrets" and e.network == "disabled" for e in result.ledger)


# ----- review hardening ------------------------------------------------------

FAKE_GH_PAT = "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz0123456789"


def test_unquoted_generic_secret_fails(ws: Path) -> None:
    rel = _write(ws, ".env", "API_KEY=abcdef0123456789ghijklmnop\n")
    assert "secrets.no_new_secrets" in _rules(_run(ws, _pack(rel)))


def test_github_pat_fails(ws: Path) -> None:
    rel = _write(ws, "d.py", f'token = "{FAKE_GH_PAT}"\n')
    assert "secrets.no_new_secrets" in _rules(_run(ws, _pack(rel)))


def test_unquoted_identifier_value_not_flagged(ws: Path) -> None:
    # No digits -> looks like an identifier/reference, not a credential.
    rel = _write(ws, "m.py", "token = get_token_from_environment_value\n")
    assert _run(ws, _pack(rel)).findings == []


def test_symlink_target_not_followed(ws: Path) -> None:
    (ws / "real_secret.txt").write_text(f'AWS="{FAKE_AWS}"\n')
    (ws / "link.txt").symlink_to("real_secret.txt")
    # The symlink blob is the target string ("real_secret.txt"), not the secret file.
    result = _run(ws, _pack("link.txt"))
    assert result.findings == []
