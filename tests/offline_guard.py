"""Network kill switch for the automated test suite.

Tests that need an HTTP result must inject a fake sender/opener. Any forgotten
real network call fails immediately before credentials or member IDs can leave
the test process.
"""

from contextlib import contextmanager
from unittest.mock import patch


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _host_from_address(address):
    if isinstance(address, tuple) and address:
        return str(address[0]).lower()
    return ""


@contextmanager
def offline_network_guard():
    original_create_connection = __import__("socket").create_connection
    original_socket_connect = __import__("socket").socket.connect
    original_socket_connect_ex = __import__("socket").socket.connect_ex

    def blocked_urlopen(*_args, **_kwargs):
        raise RuntimeError("offline test blocked network access")

    def guarded_create_connection(address, *args, **kwargs):
        if _host_from_address(address) in _LOOPBACK_HOSTS:
            return original_create_connection(address, *args, **kwargs)
        raise RuntimeError("offline test blocked network access")

    def guarded_socket_connect(sock, address):
        if _host_from_address(address) in _LOOPBACK_HOSTS:
            return original_socket_connect(sock, address)
        raise RuntimeError("offline test blocked network access")

    def guarded_socket_connect_ex(sock, address):
        if _host_from_address(address) in _LOOPBACK_HOSTS:
            return original_socket_connect_ex(sock, address)
        raise RuntimeError("offline test blocked network access")

    with (
        patch("urllib.request.urlopen", blocked_urlopen),
        patch("socket.create_connection", guarded_create_connection),
        patch("socket.socket.connect", guarded_socket_connect),
        patch("socket.socket.connect_ex", guarded_socket_connect_ex),
    ):
        yield
