"""Provider-SDK import boundary stays hermetic after the connector extras land (EG-R0-5; ADR 0033).

EG-R0-2 added the optional ``langfuse`` / ``arize-phoenix-client`` / ``langsmith`` extras. This
guard hardens the import boundary so those SDKs can never enter the required import closure:

- a **static** provider import anywhere in ``core``/``harness``/``adapters`` is detected;
- the sanctioned **lazy** pattern (``lazy_import("langfuse", …)`` → ``importlib.import_module``),
  which the connectors use inside the lane path, is not a static import and stays clean.

The connectors are deliberately **not** allow-listed: a static SDK import even inside a connector
is a leak (they must import lazily), so leaving them un-allow-listed keeps the boundary honest. The
only allow-listed network clients stay the stdlib-``urllib`` egress lanes (live-judge, openai-judge,
dashboard).
Per-connector *deletion* invariance is proven once each adapter exists (EG-R1-5/R2-5/R3-5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import evalglass
from tests.egts.checkers import _FORBIDDEN_IMPORTS, CheckerError, check_no_provider_sdk

#: The installed ``evalglass`` package root (``src/evalglass``) — the real closure the connector
#: SDKs must stay out of. Pointing at ``src`` would scan zero files and pass vacuously.
_SRC = Path(evalglass.__file__).resolve().parent

#: The top-level import name each connector SDK exposes (``arize-phoenix-client`` → ``phoenix``).
_PROVIDER_IMPORT_NAMES = ("langfuse", "phoenix", "langsmith")


def test_provider_sdk_top_level_names_are_forbidden() -> None:
    """Guard-on-the-guard: the three connector SDK import names are in the forbidden set."""
    for name in _PROVIDER_IMPORT_NAMES:
        assert name in _FORBIDDEN_IMPORTS, f"{name!r} missing from the required-tier forbidden set"


def test_required_closure_imports_no_provider_sdk() -> None:
    """core + harness + adapters import no provider SDK (the lazy-urllib egress lanes excepted).

    When the connectors land (EG-R1..R3) un-allow-listed, this same scan catches any *static* SDK
    import in them — they pass only because they import their SDK lazily.
    """
    check_no_provider_sdk(
        _SRC,
        ["core", "harness", "adapters"],
        allow=[
            "adapters/judge_live.py",
            "adapters/judge_openai.py",
            "adapters/score_sink_dashboard.py",
        ],
    )


@pytest.mark.parametrize("name", _PROVIDER_IMPORT_NAMES)
def test_static_provider_import_is_detected(tmp_path: Path, name: str) -> None:
    """Negative control: a static ``import <sdk>`` in a required module is detected."""
    pkg = tmp_path / "fakemod"
    pkg.mkdir()
    (pkg / "leak.py").write_text(f"import {name}\n", encoding="utf-8")
    with pytest.raises(CheckerError):
        check_no_provider_sdk(tmp_path, ["fakemod"])


@pytest.mark.parametrize("name", _PROVIDER_IMPORT_NAMES)
def test_from_provider_import_is_detected(tmp_path: Path, name: str) -> None:
    """Negative control: a ``from <sdk> import X`` in a required module is detected."""
    pkg = tmp_path / "fakemod"
    pkg.mkdir()
    (pkg / "leak.py").write_text(f"from {name} import Thing\n", encoding="utf-8")
    with pytest.raises(CheckerError):
        check_no_provider_sdk(tmp_path, ["fakemod"])


def test_lazy_dynamic_import_is_not_flagged(tmp_path: Path) -> None:
    """The connector pattern — import the SDK by name at runtime — is not a static import, so it
    does not trip the boundary (the SDK is absent from the static required closure)."""
    pkg = tmp_path / "fakemod"
    pkg.mkdir()
    (pkg / "lane.py").write_text(
        "import importlib\n\n\ndef read():\n    return importlib.import_module('langfuse')\n",
        encoding="utf-8",
    )
    check_no_provider_sdk(tmp_path, ["fakemod"])  # no raise — dynamic import stays clean
