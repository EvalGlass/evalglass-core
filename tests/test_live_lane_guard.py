"""The live-lane env-var gate detector (alignment AT0, EG-AT0-1).

The ``live_lane`` tier is double-guarded: a collection hook skips it unless
``EVALGLASS_LIVE_LANES=1``, and the ``allow_egress``/``open_external_socket``
primitive refuses to run without that env var. These are the
**sensitivity / specificity** tests for that guard itself (a detector that gates
whether egress is allowed needs both, per CLAUDE.md §23).

``TE-LIVE-GUARD-sensitivity`` and ``TE-LIVE-GUARD-rearm`` are intentionally
*unmarked* — they assert the *refusal* / *armed* behavior hermetically, so they
belong in the required tier and prove the gate fires when the env is unset.
``TE-LIVE-GUARD-specificity`` is the only ``live_lane`` test here; it runs only
under the opt-in tier and connects over loopback (which is permitted), proving
the scoped bypass works without disabling the global guard.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator

import pytest

from tests.conftest import (
    LIVE_LANES_ENV,
    live_lanes_enabled,
    open_external_socket,
)
from tests.hermetic import NetworkBlockedError


def test_te_live_guard_sensitivity_env_gate_fires_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TE-LIVE-GUARD-sensitivity: with the env var unset, egress is refused.

    Runs in the required tier; asserts the gate raises *before* any socket is
    constructed, so no external egress can occur.
    """
    monkeypatch.delenv(LIVE_LANES_ENV, raising=False)
    assert live_lanes_enabled() is False
    with pytest.raises(RuntimeError, match=LIVE_LANES_ENV):
        open_external_socket("example.com", 443)


def test_te_live_guard_rearm_guard_blocks_external_in_required_tier() -> None:
    """TE-LIVE-GUARD-rearm: the autouse hermetic guard stays armed.

    A *normal* socket path (no bypass) must still fail closed on an external
    name resolution — so any future fixture that leaked a global un-patch would
    turn this red.
    """
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)


@pytest.fixture
def loopback_listener() -> Iterator[int]:
    """A throwaway TCP listener bound to 127.0.0.1; yields its ephemeral port.

    A daemon thread accepts one connection and immediately closes it — no
    protocol, so a raw client connect succeeds and nothing blocks on teardown.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def _accept_once() -> None:
        try:
            conn, _ = listener.accept()
            conn.close()
        except OSError:
            pass

    thread = threading.Thread(target=_accept_once, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        listener.close()
        thread.join(timeout=2)


@pytest.mark.live_lane
def test_te_live_guard_specificity_scoped_bypass_connects_loopback(
    allow_egress: Callable[[str, int], socket.socket],
    loopback_listener: int,
) -> None:
    """TE-LIVE-GUARD-specificity: opt-in egress connects through the DI primitive.

    Only collected when ``EVALGLASS_LIVE_LANES=1``. Connects over loopback (so no
    external egress occurs even here) to prove the per-socket bypass path works
    and that ``allow_egress`` yields a usable, connected socket.
    """
    sock = allow_egress("127.0.0.1", loopback_listener)
    assert sock.getpeername()[1] == loopback_listener
