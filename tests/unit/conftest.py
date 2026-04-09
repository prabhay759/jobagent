"""Shared pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Prevent accidental real network calls in unit tests."""
    import socket

    def guard(*args, **kwargs):
        raise RuntimeError("Network access not allowed in unit tests")

    # Only block in unit tests (integration tests opt-out via marker)
    monkeypatch.setattr(socket, "getaddrinfo", guard)
