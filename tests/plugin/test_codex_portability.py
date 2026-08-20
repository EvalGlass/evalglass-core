"""EGP-P3-1 / EGP-P3-2: the Codex runtime ships from one canonical, portable skills tree.

P3 packages EvalGlass for a second runtime (Codex) *without forking skill content* (plan §8;
ADR 0023). Three structural invariants are proven here:

* ``.codex-plugin/plugin.json`` is the Codex trigger/routing surface — its ``interface{}`` block
  and ``skills`` path — and its ``name``/``version``/``license`` are byte-identical to the Claude
  manifest (one repo, one identity, one version line).
* the canonical ``skills/`` tree is shared by both runtimes: skill frontmatter is runtime-neutral
  (``name``/``description``, plus optional Claude Code UX hints — ``user-invocable`` and
  ``argument-hint`` — that other runtimes ignore) and skill bodies carry no runtime-specific
  packaging internals;
  a skill that names a Claude-only ``*_PLUGIN_ROOT`` variable always also offers the portable
  direct CLI so a non-Claude runtime has a working path.
* the root ``AGENTS.md`` is the Codex-runtime entry: display-and-routing only, points at the
  umbrella skill and the build guide, and asserts no quality/capability claim.

These are the hermetic structural floor. The *live* Codex trigger is a maintainer acceptance
probe, proven by transcript — never assumed from a green unit test.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.plugin.conftest import REPO_ROOT, skill_files

_CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
_CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
_AGENTS_MD = REPO_ROOT / "AGENTS.md"

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

#: Portable skill frontmatter — runtime-neutral identity/trigger keys, plus optional Claude Code
#: UX-control keys that degrade gracefully on other runtimes. ``user-invocable: false`` keeps a
#: backing skill model-invocable (auto-triggered) while hiding it from the ``/`` menu, so the
#: umbrella ``evalglass`` skill is the single visible command; ``argument-hint`` shows the verb list
#: in autocomplete. A non-Claude runtime that does not recognise these keys simply ignores them —
#: they never fork skill content, name a packaging internal, or change a run (the packaging-token
#: guard below stays strict).
_PORTABLE_FRONTMATTER_KEYS = {"name", "description", "user-invocable", "argument-hint"}

#: Packaging internals that are runtime-specific and belong in manifests/bootstraps, not skills.
_RUNTIME_SPECIFIC_TOKENS = (
    ".claude-plugin",
    ".codex-plugin",
    "marketplace.json",
    "plugin.json",
    "hooks.json",
    "sessionstart",
    '"interface"',
)

#: A plugin-root env var is runtime-specific (``${CLAUDE_PLUGIN_ROOT}`` in Claude Code); a skill
#: naming one must also offer the always-portable direct CLI.
_PLUGIN_ROOT_TOKEN = re.compile(r"\$\{?[A-Z]+_PLUGIN_ROOT\}?")
_PORTABLE_CLI = "python -m evalglass.installer"

#: §9.9 authority verbs — the Codex entry, like every surface, ships none.
_AUTHORITY_VERB_RE = re.compile(
    r"/evalglass\s+(?:gate|approve|certify|verify|validate|score|pass)\b", re.IGNORECASE
)


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _frontmatter_keys(path: Path) -> set[str]:
    import yaml  # type: ignore[import-untyped]

    m = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    assert m, f"{path} is missing a YAML frontmatter block"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict), f"{path} frontmatter must be a mapping"
    return set(data.keys())


# --- Codex manifest -------------------------------------------------------------------


def test_codex_manifest_exists_and_is_valid_json() -> None:
    assert _CODEX_MANIFEST.is_file(), ".codex-plugin/plugin.json must exist (P3 second runtime)"
    _load(_CODEX_MANIFEST)  # raises on invalid JSON


def test_codex_identity_byte_identical_to_claude() -> None:
    """name/version/license must match the Claude manifest exactly — one repo, one identity."""
    codex = _load(_CODEX_MANIFEST)
    claude = _load(_CLAUDE_MANIFEST)
    for field in ("name", "version", "license"):
        assert codex.get(field) == claude.get(field), (
            f"codex plugin.json {field!r}={codex.get(field)!r} must equal "
            f"claude plugin.json {field!r}={claude.get(field)!r}"
        )


def test_codex_declares_skills_path() -> None:
    """Codex discovers the shared skills tree via the manifest ``skills`` path."""
    codex = _load(_CODEX_MANIFEST)
    assert codex.get("skills") == "./skills/", "codex manifest must point skills at ./skills/"


def test_codex_interface_block_is_present_and_complete() -> None:
    """The ``interface{}`` block is what Codex renders; require its honest core keys."""
    interface = _load(_CODEX_MANIFEST).get("interface")
    assert isinstance(interface, dict), "codex manifest must carry an interface{} block"
    for key in ("displayName", "shortDescription", "longDescription", "category", "defaultPrompt"):
        assert key in interface, f"interface{{}} missing {key!r}"
    prompts = interface["defaultPrompt"]
    assert isinstance(prompts, list), "interface.defaultPrompt must be a list"
    assert prompts, "interface.defaultPrompt must be a non-empty list of honest trigger phrases"


# --- canonical, portable skills tree -------------------------------------------------


def test_single_canonical_skills_tree() -> None:
    """There is one skills/ source at the repo root — no per-runtime fork inside a manifest dir."""
    assert (REPO_ROOT / "skills").is_dir()
    for manifest_dir in (".codex-plugin", ".claude-plugin"):
        assert not (REPO_ROOT / manifest_dir / "skills").exists(), (
            f"{manifest_dir}/skills/ would fork the canonical tree — keep one source"
        )


@pytest.mark.parametrize("skill", skill_files(), ids=lambda p: p.parent.name)
def test_skill_frontmatter_is_runtime_neutral(skill: Path) -> None:
    keys = _frontmatter_keys(skill)
    extra = keys - _PORTABLE_FRONTMATTER_KEYS
    assert not extra, f"{skill}: non-portable frontmatter keys {extra} (keep name/description only)"


@pytest.mark.parametrize("skill", skill_files(), ids=lambda p: p.parent.name)
def test_skill_body_has_no_runtime_specific_packaging_tokens(skill: Path) -> None:
    low = skill.read_text(encoding="utf-8").lower()
    leaked = [tok for tok in _RUNTIME_SPECIFIC_TOKENS if tok in low]
    assert not leaked, (
        f"{skill}: runtime-specific packaging token(s) {leaked} belong in a manifest/bootstrap, "
        "not in portable skill content"
    )


@pytest.mark.parametrize("skill", skill_files(), ids=lambda p: p.parent.name)
def test_plugin_root_reference_has_portable_fallback(skill: Path) -> None:
    text = skill.read_text(encoding="utf-8")
    if _PLUGIN_ROOT_TOKEN.search(text):
        assert _PORTABLE_CLI in text, (
            f"{skill}: names a runtime-specific *_PLUGIN_ROOT var but offers no portable "
            f"{_PORTABLE_CLI!r} path — a non-Claude runtime would have no working invocation"
        )


# --- AGENTS.md (Codex-runtime entry) -------------------------------------------------


def test_agents_md_exists() -> None:
    assert _AGENTS_MD.is_file(), "root AGENTS.md must exist as the Codex-runtime entry (P3-1)"


def test_agents_md_points_to_umbrella_and_build_guide() -> None:
    text = _AGENTS_MD.read_text(encoding="utf-8")
    assert "evalglass" in text.lower(), "AGENTS.md must point at the evalglass umbrella skill"
    assert "CLAUDE.md" in text, (
        "AGENTS.md must defer to CLAUDE.md for the build guide (no duplicate/conflicting guide)"
    )


def test_agents_md_asserts_no_authority_or_quality_claim() -> None:
    text = _AGENTS_MD.read_text(encoding="utf-8")
    hit = _AUTHORITY_VERB_RE.search(text)
    assert hit is None, f"AGENTS.md must ship no authority verb: {hit.group(0) if hit else ''!r}"
    # It must state its display/routing-only nature so it cannot be read as a capability claim.
    low = " ".join(text.lower().split())
    assert "informational" in low, "AGENTS.md must keep the informational-by-default framing"
    assert re.search(r"(routing|display)[^.\n]*only|reads? no", low), (
        "AGENTS.md must state it is display/routing-only and reads no run state"
    )
