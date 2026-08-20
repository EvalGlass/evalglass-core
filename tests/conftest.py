"""Shared pytest fixtures for EvalGlass tests.

Intentionally minimal in M0. Add fixtures here when they're shared across at
least two test families (CLAUDE.md §8: avoid speculative abstractions).

Alignment AT0 (EG-AT0-1) adds the **two-tier hermetic / live-lane split**: the
required tier stays hermetic for every test (the autouse network guard below),
while ``live_lane``-marked tests are *double-guarded* — they are skipped unless
``EVALGLASS_LIVE_LANES=1`` is set (the collection hook) **and** they must take
the explicit, per-socket ``allow_egress`` fixture (which refuses to run without
the env var). The global hermetic guard is **never** un-patched; the bypass is
dependency-injected one socket at a time, and ``allow_egress`` re-asserts the
guard is still armed on teardown.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable, Iterator

import pytest

from tests.hermetic import NetworkBlockedError, install_network_guard

#: The pristine ``socket.socket.connect`` captured at conftest import — *before*
#: any autouse guard patches it. ``allow_egress`` uses this to connect a single
#: explicitly-constructed socket without ever un-patching the class-level guard,
#: so external egress is permitted one socket at a time and never globally.
_PRISTINE_CONNECT = socket.socket.connect

#: Environment variable that opts a process into the live-lane tier.
LIVE_LANES_ENV = "EVALGLASS_LIVE_LANES"


def live_lanes_enabled() -> bool:
    """True only when the live-lane tier is explicitly opted into."""
    return os.environ.get(LIVE_LANES_ENV) == "1"


def open_external_socket(host: str, port: int) -> socket.socket:
    """Connect one freshly-constructed socket externally via the pristine ``connect``.

    Refuses unless the live-lane tier is opted into. This is the single egress
    primitive: it never un-patches the class-level guard, so only the one socket
    it returns can reach the network. Directly callable so the required-tier
    sensitivity test can assert the env-gate without fixture-setup error.
    """
    if not live_lanes_enabled():
        raise RuntimeError(
            f"external egress requires {LIVE_LANES_ENV}=1 — it is opt-in and never "
            "available in the required hermetic tier"
        )
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _PRISTINE_CONNECT(sock, (host, port))
    return sock


@pytest.fixture(autouse=True)
def _hermetic_network_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block external network egress for every test (hermetic required tier).

    See ``tests/hermetic.py`` and CLAUDE.md §15/§17.
    """
    install_network_guard(monkeypatch)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``live_lane`` tests unless the live-lane tier is opted into.

    The required tier runs with ``EVALGLASS_LIVE_LANES`` unset (and CI also
    passes ``-m "not live_lane"``); this hook is the second half of the
    double-guard so a live-egress test can never run by accident even if the
    ``-m`` filter is forgotten.
    """
    del config
    if live_lanes_enabled():
        return
    skip_live = pytest.mark.skip(
        reason=f"live_lane: set {LIVE_LANES_ENV}=1 to run the opt-in live-lane tier"
    )
    for item in items:
        if "live_lane" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def allow_egress() -> Iterator[Callable[[str, int], socket.socket]]:
    """Per-socket external-egress permit for a single ``live_lane`` test.

    Yields ``connect_external(host, port) -> socket`` which connects one freshly
    constructed socket via the pristine (pre-guard) ``connect`` — so the global
    hermetic guard is **never** un-patched. Refuses to run unless the live-lane
    tier is opted into, and re-asserts on teardown that the guard is still armed
    (a leaked bypass fails loudly, not silently).
    """
    if not live_lanes_enabled():
        raise RuntimeError(
            f"allow_egress requires {LIVE_LANES_ENV}=1 — external egress is opt-in "
            "and never available in the required hermetic tier"
        )

    opened: list[socket.socket] = []

    def connect_external(host: str, port: int) -> socket.socket:
        sock = open_external_socket(host, port)
        opened.append(sock)
        return sock

    try:
        yield connect_external
    finally:
        for sock in opened:
            sock.close()
        # The class-level guard must still be armed: an *external* name lookup
        # through the patched resolver must still fail closed. Proving this on
        # teardown means a leaked global un-patch can never pass silently.
        with pytest.raises(NetworkBlockedError):
            socket.getaddrinfo("example.com", 443)
