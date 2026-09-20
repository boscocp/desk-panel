"""Unit tests for server.config_search_paths -- pure, no filesystem access.

Two properties, and the second arrived with T3.12.

Discovery is cwd-independent (see the function's docstring in
server/server.py): --config beats DESK_PANEL_CONFIG beats the script_dir
fallback, and the fallback must always be present so the caller can blindly
take paths[0].

And the fallback is the only candidate that gets to choose between the two
config formats, because it is the only source that names a file rather than
being handed one. `exists` is injected, so every case below is decided
without touching a disk.
"""
import unittest
from pathlib import Path

from server.server import config_search_paths

SCRIPT_DIR = "/opt/desk-panel/server"
TOML = Path(SCRIPT_DIR) / "config.toml"
JSON = Path(SCRIPT_DIR) / "config.json"


def only(*present):
    """An `exists` predicate answering True for exactly these paths."""
    wanted = {Path(p) for p in present}
    return lambda path: Path(path) in wanted


class ConfigSearchPathsTests(unittest.TestCase):
    def test_fallback_only_when_nothing_else_set(self):
        paths = config_search_paths([], {}, SCRIPT_DIR)
        self.assertEqual(paths, [TOML])

    def test_argv_space_form_takes_priority(self):
        paths = config_search_paths(
            ["--config", "/tmp/a.toml"], {"DESK_PANEL_CONFIG": "/tmp/b.toml"}, SCRIPT_DIR
        )
        self.assertEqual(paths, [Path("/tmp/a.toml"), Path("/tmp/b.toml"), TOML])

    def test_argv_equals_form_is_also_recognised(self):
        paths = config_search_paths(["--config=/tmp/c.toml"], {}, SCRIPT_DIR)
        self.assertEqual(paths[0], Path("/tmp/c.toml"))

    def test_env_used_when_argv_absent(self):
        paths = config_search_paths([], {"DESK_PANEL_CONFIG": "/tmp/b.json"}, SCRIPT_DIR)
        self.assertEqual(paths, [Path("/tmp/b.json"), TOML])

    def test_empty_env_value_is_ignored(self):
        paths = config_search_paths([], {"DESK_PANEL_CONFIG": ""}, SCRIPT_DIR)
        self.assertEqual(paths, [TOML])

    def test_trailing_config_flag_with_no_value_is_ignored(self):
        # "--config" as the very last token has no following value; must not
        # crash and must not be picked up as a path candidate.
        paths = config_search_paths(["--config"], {}, SCRIPT_DIR)
        self.assertEqual(paths, [TOML])

    def test_none_argv_and_env_behave_like_empty(self):
        paths = config_search_paths(None, None, SCRIPT_DIR)
        self.assertEqual(paths, [TOML])

    def test_last_config_flag_wins_when_repeated(self):
        paths = config_search_paths(
            ["--config", "/tmp/first.toml", "--config", "/tmp/second.toml"], {}, SCRIPT_DIR
        )
        self.assertEqual(paths[0], Path("/tmp/second.toml"))


class FallbackFormatTests(unittest.TestCase):
    def test_toml_wins_where_both_exist(self):
        paths = config_search_paths([], {}, SCRIPT_DIR, exists=only(TOML, JSON))
        self.assertEqual(paths, [TOML])

    def test_a_lone_json_is_still_found(self):
        # T3.12 step 3, and the whole reason the transition is not a rename:
        # an owner who upgrades the server and touches nothing else keeps a
        # working panel.
        paths = config_search_paths([], {}, SCRIPT_DIR, exists=only(JSON))
        self.assertEqual(paths, [JSON])

    def test_with_neither_present_the_candidate_is_the_toml(self):
        # So the "not found" message names the file the owner should write,
        # not the one being retired.
        paths = config_search_paths([], {}, SCRIPT_DIR, exists=only())
        self.assertEqual(paths, [TOML])

    def test_an_explicit_path_is_never_upgraded_to_a_neighbouring_toml(self):
        # The launchers all pass an absolute --config. If that file has been
        # deleted, the server must still fail loudly rather than start on
        # whatever config happens to sit in the repository -- a silent switch
        # to somebody else's tickers and somebody else's token.
        paths = config_search_paths(
            ["--config", "/etc/desk-panel/config.json"], {}, SCRIPT_DIR,
            exists=only(TOML, JSON),
        )
        self.assertEqual(paths[0], Path("/etc/desk-panel/config.json"))

    def test_an_explicit_path_that_exists_is_left_exactly_as_written(self):
        explicit = Path("/etc/desk-panel/config.json")
        paths = config_search_paths(
            [], {"DESK_PANEL_CONFIG": str(explicit)}, SCRIPT_DIR, exists=only(explicit, TOML)
        )
        self.assertEqual(paths[0], explicit)


if __name__ == "__main__":
    unittest.main()
