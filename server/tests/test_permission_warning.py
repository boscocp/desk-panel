"""Unit tests for server.config_permission_warning -- pure, no filesystem
or platform access; `mode` and `platform` are passed in directly so POSIX
permission logic can be exercised from any test machine, Windows included.
"""
import unittest

from server.server import config_permission_warning


class ConfigPermissionWarningTests(unittest.TestCase):
    def test_windows_never_warns_regardless_of_mode(self):
        # 0o777 would warn loudly on POSIX; st_mode is meaningless on
        # Windows, where NTFS ACLs are the real control.
        warning = config_permission_warning(0o777, "win32", path="config.json", token="secret")
        self.assertIsNone(warning)

    def test_no_token_never_warns(self):
        # config.example.json ships world-readable on purpose and carries
        # no token -- warning about it would teach people to ignore the
        # warning that matters (see the function's own docstring).
        warning = config_permission_warning(0o644, "linux", path="config.example.json", token="")
        self.assertIsNone(warning)

    def test_group_and_other_readable_with_token_warns(self):
        warning = config_permission_warning(0o644, "linux", path="config.json", token="secret")
        self.assertIsNotNone(warning)
        self.assertIn("config.json", warning)
        self.assertIn("0o644", warning)
        self.assertIn("chmod 600 config.json", warning)

    def test_owner_only_mode_with_token_does_not_warn(self):
        warning = config_permission_warning(0o600, "linux", path="config.json", token="secret")
        self.assertIsNone(warning)

    def test_group_readable_but_not_other_still_warns(self):
        warning = config_permission_warning(0o640, "darwin", path="config.json", token="secret")
        self.assertIsNotNone(warning)

    def test_missing_path_falls_back_to_generic_name(self):
        warning = config_permission_warning(0o644, "linux", path=None, token="secret")
        self.assertIn("config.json", warning)


if __name__ == "__main__":
    unittest.main()
