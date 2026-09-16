"""Unit tests for server.check_python_version -- pure, version_info passed
in directly so the floor can be exercised without needing an old
interpreter to run the test suite on.
"""
import sys
import unittest

from server.server import MIN_PYTHON, check_python_version


class CheckPythonVersionTests(unittest.TestCase):
    def test_too_old_major_minor_returns_message(self):
        message = check_python_version((3, 10, 0))
        self.assertIsNotNone(message)
        self.assertIn("3.11", message)
        self.assertIn("3.10", message)

    def test_exactly_the_floor_is_fine(self):
        self.assertIsNone(check_python_version(MIN_PYTHON + (0,)))

    def test_newer_than_floor_is_fine(self):
        self.assertIsNone(check_python_version((3, 14, 0)))

    def test_much_older_major_version_returns_message(self):
        self.assertIsNotNone(check_python_version((2, 7, 18)))

    def test_defaults_to_running_interpreter(self):
        # No fixture needed: whatever runs this suite must itself satisfy
        # the floor (server/CLAUDE.md: "Python 3.11 or newer").
        self.assertEqual(check_python_version(None), check_python_version(sys.version_info))
        self.assertIsNone(check_python_version(None))


if __name__ == "__main__":
    unittest.main()
