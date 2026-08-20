"""EGP-P0-2 / EGP-P0-8: plugin.json and marketplace.json have safe, valid manifest semantics.

Structural validation of the manifests against the schema verified against
``code.claude.com/docs`` (PLUGIN_TRANSFORMATION_PLAN.md §3). The live ``claude plugin validate
. --strict`` gate runs in ``scripts/plugin_validate.sh`` / CI where the ``claude`` binary exists;
these tests are the hermetic structural floor.
"""

from __future__ import annotations

import re
from typing import Any

# Component keys that, if declared in plugin.json, would either disable auto-discovery or (with a
# marketplace entry that also declares components) trigger the "conflicting manifests" load failure.
_COMPONENT_KEYS = ("commands", "agents", "skills", "hooks", "mcpServers", "lspServers")

_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


def test_plugin_json_required_and_kebab_name(plugin_manifest: dict[str, Any]) -> None:
    assert plugin_manifest["name"] == "evalglass-core"
    assert _KEBAB.match(plugin_manifest["name"]), "plugin name must be kebab-case (namespace token)"


def test_plugin_json_version_is_semver(plugin_manifest: dict[str, Any]) -> None:
    assert _SEMVER.match(plugin_manifest["version"]), (
        "version must be semver for the alignment gate"
    )


def test_plugin_json_license_apache(plugin_manifest: dict[str, Any]) -> None:
    assert plugin_manifest["license"] == "Apache-2.0"


def test_plugin_json_author_contact(plugin_manifest: dict[str, Any]) -> None:
    assert plugin_manifest["author"]["email"] == "contact@evalglass.com"
    assert plugin_manifest["author"]["name"] == "EvalGlass"


def test_plugin_json_declares_no_components(plugin_manifest: dict[str, Any]) -> None:
    """Components are auto-discovered; declaring them risks the conflicting-manifests footgun."""
    for key in _COMPONENT_KEYS:
        assert key not in plugin_manifest, f"plugin.json must not declare {key!r} (auto-discovery)"
    assert "strict" not in plugin_manifest


def test_marketplace_json_single_self_plugin(marketplace_manifest: dict[str, Any]) -> None:
    assert _KEBAB.match(marketplace_manifest["name"])
    assert "owner" in marketplace_manifest
    assert marketplace_manifest["owner"]["name"]
    plugins = marketplace_manifest["plugins"]
    assert isinstance(plugins, list)
    assert len(plugins) == 1
    entry = plugins[0]
    assert entry["name"] == "evalglass-core"
    assert entry["source"] == "./", "repo is its own single-plugin marketplace (source ./)"


def test_marketplace_entry_inherits_version(marketplace_manifest: dict[str, Any]) -> None:
    """The entry omits version; it inherits from plugin.json (plan §4.3)."""
    assert "version" not in marketplace_manifest["plugins"][0]


def test_install_namespaces_are_plugin_at_publisher(
    plugin_manifest: dict[str, Any], marketplace_manifest: dict[str, Any]
) -> None:
    """Install is `/plugin install <plugin>@<marketplace>` → `evalglass-core@evalglass` (ADR 0062):
    the plugin names the product; the marketplace names the publisher; distinct by design."""
    assert plugin_manifest["name"] == "evalglass-core"
    assert marketplace_manifest["name"] == "evalglass"
    assert plugin_manifest["name"] != marketplace_manifest["name"]
