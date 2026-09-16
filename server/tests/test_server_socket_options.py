"""Unit tests for server._allow_reuse_address and Server.allow_reuse_address
-- the platform-correct SO_REUSEADDR decision (see the class's docstring in
server/server.py: Windows must refuse a second bind instead of silently
letting a fast-user-switch instance steal the port).

`_allow_reuse_address` takes os_name as a parameter precisely so both
branches are reachable from a single POSIX test runner -- reloading the
whole module under a patched `os.name` is not an option, since the
module-level `Path(__file__).resolve()` picks WindowsPath/PosixPath from
the live os.name at import time and blows up under the patch.
"""
import os
import unittest

from server.server import Server, _allow_reuse_address


class AllowReuseAddressTests(unittest.TestCase):
    def test_windows_does_not_reuse_address(self):
        self.assertFalse(_allow_reuse_address("nt"))

    def test_posix_reuses_address(self):
        self.assertTrue(_allow_reuse_address("posix"))

    def test_server_class_is_wired_to_the_real_os_name(self):
        self.assertEqual(Server.allow_reuse_address, _allow_reuse_address(os.name))


if __name__ == "__main__":
    unittest.main()
