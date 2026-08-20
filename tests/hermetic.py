"""Hermetic-tier network guard for the EvalGlass test suite.

The EvalGlass required test tier must be hermetic: no network, no credentials,
no hosted services (``CLAUDE.md §15/§17``; ``test_architecture_build_contract.md``
§2, §8). This module installs a guard that lets real *loopback* traffic through
(so local fixtures and future local servers keep working) but raises
:class:`NetworkBlockedError` on any attempt to reach an external address.

The guard covers the egress paths a test could realistically use: TCP
``connect``/``connect_ex``, datagram ``sendto``, and name resolution via
``getaddrinfo`` (high-level clients resolve before connecting, so blocking the
resolver closes that gap too). It is wired in as an autouse fixture in
``tests/conftest.py`` so every test runs under it. A test that legitimately
needs egress (e.g. an opt-in optional-lane integration in M5) should be marked
and run outside the required tier, never by weakening this guard.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class NetworkBlockedError(RuntimeError):
    """Raised when test code attempts external network egress in the hermetic tier."""


def _is_loopback_address(address: object) -> bool:
    """True for loopback ``(host, port)`` targets; non-INET targets (AF_UNIX) are local."""
    if isinstance(address, tuple) and address:
        host = address[0]
        return isinstance(host, str) and host in _LOOPBACK_HOSTS
    return True


def _is_loopback_host(host: object) -> bool:
    """True for ``getaddrinfo`` hosts that resolve locally (loopback or passive ``None``)."""
    return host is None or (isinstance(host, str) and host in _LOOPBACK_HOSTS)


def _blocked(detail: str) -> NetworkBlockedError:
    return NetworkBlockedError(
        f"network access blocked in the hermetic test tier ({detail}). "
        "EvalGlass required tests must be hermetic — see CLAUDE.md §15/§17."
    )


def install_network_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``socket`` so external connect/connect_ex/sendto/getaddrinfo raise.

    Loopback targets pass through to the real implementation so local fixtures
    and servers keep working.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if _is_loopback_address(address):
            real_connect(self, address)
            return
        raise _blocked(f"connect to {address!r}")

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        if _is_loopback_address(address):
            return real_connect_ex(self, address)
        raise _blocked(f"connect_ex to {address!r}")

    def guarded_sendto(self: socket.socket, *args: Any, **kwargs: Any) -> int:
        # sendto(data, address) or sendto(data, flags, address): address is last.
        address = args[-1] if args else None
        if _is_loopback_address(address):
            return real_sendto(self, *args, **kwargs)
        raise _blocked(f"sendto {address!r}")

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_loopback_host(host):
            return real_getaddrinfo(host, *args, **kwargs)
        raise _blocked(f"getaddrinfo for {host!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
