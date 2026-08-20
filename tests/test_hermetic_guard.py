"""The hermetic test tier blocks real network egress (CLAUDE.md §15/§17).

EvalGlass required-tier tests must run without network. EGTS depends on this:
``test_architecture_build_contract.md §2`` ("required tier is hermetic") and §8
("required tests block network and credential access"). The guard is installed
as an autouse fixture in ``tests/conftest.py``; these tests prove it actually
fires (sensitivity) and does not interfere with legitimate loopback use
(specificity).
"""

from __future__ import annotations

import socket

import pytest

from tests.hermetic import NetworkBlockedError


def test_external_connect_is_blocked() -> None:
    """A connect() to a non-loopback address raises NetworkBlockedError."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkBlockedError):
            sock.connect(("example.com", 80))
    finally:
        sock.close()


def test_creating_a_socket_is_allowed() -> None:
    """Constructing a socket (no egress) is not blocked — the guard scopes to connect."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.close()


def test_loopback_connect_is_allowed() -> None:
    """Loopback connections are permitted so local fixtures/servers still work."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((host, port))  # loopback — must not raise
    finally:
        client.close()
        server.close()


def test_external_dns_resolution_is_blocked() -> None:
    """getaddrinfo on an external host raises — high-level clients resolve before connect."""
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 80)


def test_loopback_dns_resolution_is_allowed() -> None:
    """Resolving loopback hosts is permitted (no external egress)."""
    assert socket.getaddrinfo("127.0.0.1", 0)


def test_external_udp_sendto_is_blocked() -> None:
    """Datagram egress to an external address raises (no connect() involved)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(NetworkBlockedError):
            sock.sendto(b"ping", ("8.8.8.8", 53))
    finally:
        sock.close()
