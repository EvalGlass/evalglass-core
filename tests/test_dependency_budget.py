"""Dependency budget — provider SDKs are opt-in connector extras only (EG-R0-2; ADR 0033).

The hermetic tranche (EG-H5-2) banned *every* provider SDK from the dependency surface. The
live-connector tranche (EG-R0) relaxes that in exactly one way: the three sanctioned connector
extras — ``langfuse-trace``, ``phoenix-trace``, ``langsmith-trace`` — may each pin their own
provider SDK (ADR 0034/0035/0036). The budget stays tight everywhere else:

- ``project.dependencies`` is still PyYAML-only (a provider SDK in the *required* deps fails);
- only a connector extra may pin a provider SDK, and only its **own** sanctioned one;
- the full ``arize-phoenix`` *server* package stays banned — the Phoenix connector uses the
  lightweight ``arize-phoenix-client`` (ADR 0035), so the server (which transitively pulls
  openai/anthropic/fastapi) must never enter the lock;
- no *other* provider/observability SDK (openai, anthropic, …) may enter the lock.

The runtime *import* closure is separately proven SDK-free by ``check_no_provider_sdk`` (EG-R0-5);
this guard pins the declared dependencies, the optional extras, and the lock. ``requests`` /
``httpx`` are not banned in the lock — they are legitimate dev/runtime transitives, never a
provider SDK.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_UVLOCK = _ROOT / "uv.lock"

#: The sanctioned opt-in connector extras and the single provider SDK each may pin (EG-R0-2;
#: ADR 0033/0034/0035/0036). These are the only provider SDKs allowed anywhere in the budget, and
#: only inside their own optional extra — never in ``project.dependencies``.
_CONNECTOR_EXTRAS = {
    "langfuse-trace": "langfuse",
    "phoenix-trace": "arize-phoenix-client",
    "langsmith-trace": "langsmith",
}
_CONNECTOR_SDKS = frozenset(_CONNECTOR_EXTRAS.values())

#: Provider / LLM / observability SDK distribution names that must NEVER enter the dependency
#: budget — not runtime deps, not any optional extra, not the lock. The full ``arize-phoenix``
#: server package is kept here on purpose (the connector uses ``arize-phoenix-client``).
_BANNED_PROVIDER_SDKS = frozenset(
    {
        "phoenix",
        "arize-phoenix",
        "openai",
        "anthropic",
        "cohere",
        "ragas",
        "deepeval",
        "promptfoo",
        "garak",
        "mlflow",
        "ollama",
    }
)

#: Every provider SDK name this guard recognizes (sanctioned + banned) — the lens it scans extras
#: through. A name outside this set is not a provider SDK as far as the budget is concerned.
_ALL_PROVIDER_SDKS = _CONNECTOR_SDKS | _BANNED_PROVIDER_SDKS


def _pkg_name(spec: str) -> str:
    """The PEP 503-canonical distribution name from a PEP 508 requirement string.

    Lower-cases, strips the version/extras, and collapses runs of ``[-_.]`` to a single ``-`` so a
    spelling like ``arize_phoenix`` / ``arize.phoenix`` cannot slip past the ``arize-phoenix`` ban.
    """
    raw = re.split(r"[<>=!~;\[ ]", spec.strip(), maxsplit=1)[0].strip().lower()
    return re.sub(r"[-_.]+", "-", raw)


def _has_version_bound(spec: str) -> bool:
    """True if a PEP 508 requirement carries an explicit version specifier (it is *pinned*).

    Checks only the *specifier* portion: the environment marker (after ``;``) and any
    ``[extras]`` are stripped first, so a marker's own operator — e.g.
    ``langfuse; python_version >= "3.12"`` — can never masquerade as a version pin.
    """
    requirement = spec.split(";", 1)[0]  # drop the environment marker
    requirement = re.sub(r"\[[^\]]*\]", "", requirement)  # drop extras
    return bool(re.search(r"[<>=~!]=?|===", requirement))


def _pyproject() -> dict[str, object]:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def _optional_extras() -> dict[str, list[str]]:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    extras = project.get("optional-dependencies", {})
    assert isinstance(extras, dict)
    return {name: [str(p) for p in pkgs] for name, pkgs in extras.items()}


def test_runtime_dependencies_are_only_pyyaml() -> None:
    """The required dependency surface stays PyYAML-only — a provider SDK in it is an audit fail."""
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    names = {_pkg_name(str(dep)) for dep in project["dependencies"]}
    assert names == {"pyyaml"}, f"runtime dependencies drifted beyond PyYAML: {sorted(names)}"


def test_connector_extras_are_present_and_pinned() -> None:
    """Each sanctioned connector extra exists and pins exactly its own SDK with a version bound."""
    extras = _optional_extras()
    for extra_name, sdk in _CONNECTOR_EXTRAS.items():
        pins = extras.get(extra_name)
        assert pins, f"connector extra {extra_name!r} is missing or empty"
        specs = {_pkg_name(p): p for p in pins}
        assert sdk in specs, f"connector extra {extra_name!r} does not pin {sdk!r}: {pins}"
        assert _has_version_bound(specs[sdk]), (
            f"connector extra {extra_name!r} pins {sdk!r} without a version bound: {specs[sdk]!r}"
        )


def test_each_optional_extra_pins_only_its_sanctioned_connector_sdk() -> None:
    """No extra may pin a provider SDK except its own sanctioned connector SDK (EG-R0-2)."""
    for extra_name, pkgs in _optional_extras().items():
        provider_pkgs = {_pkg_name(p) for p in pkgs} & _ALL_PROVIDER_SDKS
        sanctioned = _CONNECTOR_EXTRAS.get(extra_name)
        allowed = {sanctioned} if sanctioned is not None else set()
        illegal = provider_pkgs - allowed
        assert illegal == set(), (
            f"optional extra {extra_name!r} pins a non-sanctioned provider SDK: {sorted(illegal)}"
        )


def test_uv_lock_introduces_no_banned_provider_sdk() -> None:
    """The lock may carry the three sanctioned connector SDKs; no *other* provider SDK may enter."""
    if not _UVLOCK.exists():
        pytest.skip("no uv.lock present")
    locked = {
        _pkg_name(m.group(1))
        for m in re.finditer(
            r'^name = "([^"]+)"', _UVLOCK.read_text(encoding="utf-8"), re.MULTILINE
        )
    }
    leaked = sorted(locked & _BANNED_PROVIDER_SDKS)
    assert leaked == [], f"uv.lock introduced a banned provider SDK: {leaked}"


def test_sensitivity_a_provider_sdk_runtime_dep_is_detected() -> None:
    """Negative control: the required-dependency guard fires for any SDK in runtime deps."""
    # A sanctioned connector SDK belongs in its extra, never in runtime deps — still caught.
    doctored = {"pyyaml>=6.0", "langfuse>=4"}
    assert {_pkg_name(dep) for dep in doctored} != {"pyyaml"}
    # An always-banned SDK in runtime deps is likewise caught.
    assert {_pkg_name(dep) for dep in {"pyyaml>=6.0", "openai>=1"}} != {"pyyaml"}


def test_sensitivity_banned_sdk_and_misplaced_connector_sdk_are_detected() -> None:
    """Negative control: the full Phoenix server, a foreign SDK in an extra, and a banned SDK in
    the lock are all detected — only the lightweight client is sanctioned."""
    # The full `arize-phoenix` server stays banned even though `arize-phoenix-client` is allowed.
    assert _pkg_name("arize-phoenix>=17") in _BANNED_PROVIDER_SDKS
    assert _pkg_name("arize-phoenix-client>=2") in _CONNECTOR_SDKS
    assert _pkg_name("arize-phoenix-client>=2") not in _BANNED_PROVIDER_SDKS
    # An extra pinning a SDK that is not its sanctioned one is illegal.
    foreign = {_pkg_name("openai>=1")} & _ALL_PROVIDER_SDKS
    allowed_for_langfuse = {_CONNECTOR_EXTRAS["langfuse-trace"]}
    assert foreign - allowed_for_langfuse == {"openai"}
    # PEP 503 canonicalization still catches a non-canonical spelling of a banned SDK.
    assert _pkg_name("arize_phoenix>=1.0") == "arize-phoenix"
    assert _pkg_name("arize.phoenix") in _BANNED_PROVIDER_SDKS


def test_sensitivity_unpinned_sdk_is_not_mistaken_for_pinned() -> None:
    """Negative control: an environment marker's own operator must not pass as a version pin."""
    assert not _has_version_bound("langfuse")
    assert not _has_version_bound('langfuse; python_version >= "3.12"')
    assert not _has_version_bound("arize-phoenix-client[grpc]")
    assert _has_version_bound("langfuse>=4,<5")
    assert _has_version_bound('langsmith>=0.4,<1; python_version >= "3.12"')
