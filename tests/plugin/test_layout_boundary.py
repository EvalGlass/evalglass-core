"""EGP-P0-3: root plugin layout exists and plugin surfaces are NEVER vendored into a host.

The runtime-independence boundary (ADR 0010/0011/0022): host vendoring copies only
``core``/``harness``/``adapters`` into ``evals/_evalglass/``. The plugin's delivery directories
(skills/, hooks/, .claude-plugin/, plugin-docs/, assets/, bin/, commands/) must never appear in the
managed runtime, or removing the plugin could change host behavior.
"""

from __future__ import annotations

from pathlib import Path

from evalglass.installer.vendor import MANAGED_PACKAGES, MANAGED_ROOT, managed_files
from tests.plugin.conftest import PLUGIN_DIRS, REPO_ROOT

_FRAMEWORK_PKG = REPO_ROOT / "src" / "evalglass"


def test_required_plugin_dirs_exist_at_root() -> None:
    for name in (".claude-plugin", "skills", "hooks"):
        assert (REPO_ROOT / name).is_dir(), f"plugin dir {name!r} must exist at the plugin root"
    # Reserved (populated in later slices) but present so the layout is real.
    for name in ("bin", "plugin-docs", "assets"):
        assert (REPO_ROOT / name).is_dir(), f"reserved plugin dir {name!r} must exist"


def test_manifests_only_in_claude_plugin_dir() -> None:
    """`.claude-plugin/` holds only the manifest files — no component dirs inside it."""
    entries = {p.name for p in (REPO_ROOT / ".claude-plugin").iterdir()}
    assert entries <= {"plugin.json", "marketplace.json"}, (
        f"unexpected files in .claude-plugin/: {entries}"
    )


def test_managed_packages_exclude_plugin_dirs() -> None:
    assert MANAGED_PACKAGES == ("core", "harness", "adapters")
    for name in PLUGIN_DIRS:
        assert name not in MANAGED_PACKAGES


def test_vendored_files_never_reference_plugin_dirs() -> None:
    """Every managed file lands under evals/_evalglass/ and no path segment is a plugin dir."""
    contents = managed_files(_FRAMEWORK_PKG, "0.0.0")
    assert contents, "expected a non-empty managed file set"
    plugin_dir_names = set(PLUGIN_DIRS)
    for mc in contents:
        assert mc.path.startswith(f"{MANAGED_ROOT}/"), (
            f"managed file escaped the managed root: {mc.path}"
        )
        segments = set(Path(mc.path).parts)
        leaked = segments & plugin_dir_names
        assert not leaked, f"plugin surface {leaked} leaked into the vendored runtime via {mc.path}"


def test_plugin_dirs_are_orthogonal_to_framework_package() -> None:
    """Plugin surfaces live at the repo root, not inside the framework package."""
    for name in PLUGIN_DIRS:
        assert not (_FRAMEWORK_PKG / name).exists(), f"{name!r} must not live under src/evalglass/"
