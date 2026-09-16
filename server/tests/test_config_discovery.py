"""Unit tests for server.config_search_paths -- pure, no filesystem access.

This is what makes config discovery cwd-independent (see the function's
docstring in server/server.py): --config beats DESK_PANEL_CONFIG beats the
script_dir fallback, and the fallback must always be present so the caller
can blindly take paths[0].
"""
import unittest
from pathlib import Path

from server.server import config_search_paths

SCRIPT_DIR = "/opt/desk-panel/server"


class ConfigSearchPathsTests(unittest.TestCase):
    def test_fallback_only_when_nothing_else_set(self):
        paths = config_search_paths([], {}, SCRIPT_DIR)
        self.assertEqual(paths, [Path(SCRIPT_DIR) / "config.json"])

    def test_argv_space_form_takes_priority(self):
        paths = config_search_paths(
            ["--config", "/tmp/a.json"], {"DESK_PANEL_CONFIG": "/tmp/b.json"}, SCRIPT_DIR
        )
        self.assertEqual(
            paths,
            [Path("/tmp/a.json"), Path("/tmp/b.json"), Path(SCRIPT_DIR) / "config.json"],
        )

    def test_argv_equals_form_is_also_recognised(self):
        paths = config_search_paths(["--config=/tmp/c.json"], {}, SCRIPT_DIR)
        self.assertEqual(paths[0], Path("/tmp/c.json"))

    def test_env_used_when_argv_absent(self):
        paths = config_search_paths([], {"DESK_PANEL_CONFIG": "/tmp/b.json"}, SCRIPT_DIR)
        self.assertEqual(paths, [Path("/tmp/b.json"), Path(SCRIPT_DIR) / "config.json"])

    def test_empty_env_value_is_ignored(self):
        paths = config_search_paths([], {"DESK_PANEL_CONFIG": ""}, SCRIPT_DIR)
        self.assertEqual(paths, [Path(SCRIPT_DIR) / "config.json"])

    def test_trailing_config_flag_with_no_value_is_ignored(self):
        # "--config" as the very last token has no following value; must not
        # crash and must not be picked up as a path candidate.
        paths = config_search_paths(["--config"], {}, SCRIPT_DIR)
        self.assertEqual(paths, [Path(SCRIPT_DIR) / "config.json"])

    def test_none_argv_and_env_behave_like_empty(self):
        paths = config_search_paths(None, None, SCRIPT_DIR)
        self.assertEqual(paths, [Path(SCRIPT_DIR) / "config.json"])

    def test_last_config_flag_wins_when_repeated(self):
        paths = config_search_paths(
            ["--config", "/tmp/first.json", "--config", "/tmp/second.json"], {}, SCRIPT_DIR
        )
        self.assertEqual(paths[0], Path("/tmp/second.json"))


if __name__ == "__main__":
    unittest.main()
