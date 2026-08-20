"""EGP-P2-6: the version-bearing files agree (the in-repo part of the five-way alignment).

`plugin.json` · `pyproject.toml [project].version` · `src/evalglass/__init__.py:__version__` ·
`CITATION.cff` (and, once P3 lands, `.codex-plugin/plugin.json`) must all carry the same version.
The release-time location — the git tag — is asserted by the release checklist
(`docs/plugin/RELEASE_CHECKLIST.md`), not in a unit test.

Versions are read from the repo-under-test's files (not the installed package), so this checks the
working tree, not whatever `evalglass` happens to be importable.
"""

from __future__ import annotations

import json
import re
import tomllib

import yaml  # type: ignore[import-untyped]

from tests.plugin.conftest import REPO_ROOT

_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def _plugin_json_version() -> str:
    data = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return str(data["version"])


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _dunder_version() -> str:
    src = (REPO_ROOT / "src" / "evalglass" / "__init__.py").read_text(encoding="utf-8")
    m = _VERSION_RE.search(src)
    assert m, "src/evalglass/__init__.py must declare __version__"
    return m.group(1)


def _citation_version() -> str:
    data = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    return str(data["version"])


def _codex_plugin_version() -> str | None:
    """The Codex manifest version (P3); ``None`` until ``.codex-plugin/plugin.json`` exists."""
    path = REPO_ROOT / ".codex-plugin" / "plugin.json"
    if not path.exists():
        return None
    return str(json.loads(path.read_text(encoding="utf-8"))["version"])


def test_in_repo_versions_agree() -> None:
    versions = {
        "plugin.json": _plugin_json_version(),
        "pyproject.toml": _pyproject_version(),
        "__init__.__version__": _dunder_version(),
        "CITATION.cff": _citation_version(),
    }
    # The Codex manifest joins the alignment set once it exists (P3); absent before then.
    codex = _codex_plugin_version()
    if codex is not None:
        versions[".codex-plugin/plugin.json"] = codex
    distinct = set(versions.values())
    assert len(distinct) == 1, f"version drift across {versions}"


def test_citation_identity_is_consistent() -> None:
    data = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert data["license"] == "Apache-2.0"
    assert any("EvalGlass" in str(a.get("name", "")) for a in data["authors"])
