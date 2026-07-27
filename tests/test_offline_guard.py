import socket
import unittest
import urllib.request

from tests.offline_guard import offline_network_guard


class OfflineNetworkGuardTests(unittest.TestCase):
    def test_blocks_urllib_and_socket_connections(self):
        with offline_network_guard():
            with self.assertRaisesRegex(RuntimeError, "offline test blocked network"):
                urllib.request.urlopen("https://api.line.me/v2/bot/info")

            with self.assertRaisesRegex(RuntimeError, "offline test blocked network"):
                socket.create_connection(("api.line.me", 443))

    def test_restores_network_functions_after_context(self):
        original_urlopen = urllib.request.urlopen
        original_create_connection = socket.create_connection

        with offline_network_guard():
            self.assertIsNot(urllib.request.urlopen, original_urlopen)
            self.assertIsNot(socket.create_connection, original_create_connection)

        self.assertIs(urllib.request.urlopen, original_urlopen)
        self.assertIs(socket.create_connection, original_create_connection)


if __name__ == "__main__":
    unittest.main()
