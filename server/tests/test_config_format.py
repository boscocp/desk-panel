"""Unit tests for server.config_format and the one-line notice that points a
JSON config at its TOML replacement.

Everything under test here is pure, so nothing in this file touches a
filesystem: the parsers are handed text and the notice is handed a path that
need not exist. That is the split T3.12 was for -- `load_config` owns the
single read, these functions own what the bytes mean.
"""
import unittest
from pathlib import Path

from server.config_format import JSON, TOML, ConfigError, format_for_path, merge, parse
from server.server import EXAMPLE_CONFIG_PATH as EXAMPLE, legacy_format_notice


class FormatForPathTests(unittest.TestCase):
    def test_toml_suffix_selects_toml(self):
        self.assertEqual(format_for_path("/etc/desk-panel/config.toml"), TOML)

    def test_suffix_match_is_case_insensitive(self):
        # Windows hands back whatever casing the filesystem stored, and NTFS
        # is case-preserving; a Config.TOML must not be parsed as JSON.
        self.assertEqual(format_for_path(Path("C:/desk-panel/Config.TOML")), TOML)

    def test_json_suffix_selects_json(self):
        self.assertEqual(format_for_path("server/config.json"), JSON)

    def test_no_suffix_falls_back_to_json(self):
        # DESK_PANEL_CONFIG=/etc/desk-panel/config is a reasonable thing for a
        # packager to have written, and it worked before this task existed.
        self.assertEqual(format_for_path("/etc/desk-panel/config"), JSON)


class ParseTests(unittest.TestCase):
    def test_toml_parses_to_a_dict(self):
        data = parse('city = "Sao Paulo"\nquotes = ["PETR4"]\n', TOML)
        self.assertEqual(data, {"city": "Sao Paulo", "quotes": ["PETR4"]})

    def test_json_parses_to_a_dict(self):
        self.assertEqual(parse('{"port": 9000}', JSON), {"port": 9000})

    def test_malformed_toml_raises_config_error_naming_the_file(self):
        with self.assertRaises(ConfigError) as ctx:
            parse("quotes = [", TOML, name="config.toml")
        self.assertIn("config.toml", str(ctx.exception))
        self.assertIn("not valid TOML", str(ctx.exception))

    def test_malformed_json_raises_config_error(self):
        with self.assertRaises(ConfigError) as ctx:
            parse("{not valid json", JSON, name="config.json")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_json_array_is_rejected_even_though_it_parses(self):
        with self.assertRaises(ConfigError) as ctx:
            parse('["PETR4", "VALE3"]', JSON)
        self.assertIn("must contain a JSON object", str(ctx.exception))

    def test_a_trailing_comma_is_fatal_in_json_and_fine_in_toml(self):
        # The ergonomics claim this whole task rests on, asserted rather than
        # asserted-in-prose: the JSON below is a syntax error a page away from
        # where it was typed, and the TOML below is simply a two-item list.
        with self.assertRaises(ConfigError):
            parse('{"quotes": ["PETR4", "VALE3",]}', JSON)
        self.assertEqual(
            parse('quotes = ["PETR4", "VALE3",]\n', TOML), {"quotes": ["PETR4", "VALE3"]}
        )

    def test_neither_parser_echoes_the_text_it_choked_on(self):
        # Not a hypothetical: the config being parsed is the file holding the
        # brapi token, and this message is printed to stderr and, on Windows,
        # appended to a log file. A parser that quoted the offending line
        # would leak the token on the owner's first typo.
        secret = "super-secret-token"
        for text, fmt in (
            (f"brapi_token = {secret}\n", TOML),
            (f'brapi_token = "{secret}\n', TOML),
            (f'{{not valid json, token={secret}', JSON),
        ):
            with self.subTest(fmt=fmt, text=text):
                with self.assertRaises(ConfigError) as ctx:
                    parse(text, fmt)
                self.assertNotIn(secret, str(ctx.exception))


class MergeTests(unittest.TestCase):
    def test_defaults_fill_what_the_config_omits(self):
        self.assertEqual(
            merge({"quotes": ["PETR4"]}, {"quotes": [], "city": "Sao Paulo"}),
            {"quotes": ["PETR4"], "city": "Sao Paulo"},
        )

    def test_neither_input_is_mutated(self):
        data, defaults = {"port": 9000}, {"port": 8777, "city": "Sao Paulo"}
        merge(data, defaults)
        self.assertEqual(data, {"port": 9000})
        self.assertEqual(defaults, {"port": 8777, "city": "Sao Paulo"})

    def test_a_nested_value_is_replaced_and_not_deep_merged(self):
        # `actions` is a closed allowlist (ADR 0015). A config that sets it
        # means to replace the default, and a deep merge would silently
        # reopen the list with whatever the default happened to hold.
        merged = merge({"actions": ["mute-mic"]}, {"actions": ["mute-audio"]})
        self.assertEqual(merged["actions"], ["mute-mic"])


class LegacyFormatNoticeTests(unittest.TestCase):
    def test_a_json_config_is_told_where_the_replacement_is(self):
        notice = legacy_format_notice(Path("/home/me/desk-panel/server/config.json"))
        self.assertIsNotNone(notice)
        self.assertIn("config.json", notice)
        self.assertIn("config.toml", notice)
        # It still works. This is a pointer, not a deprecation warning.
        self.assertIn("still works", notice)

    def test_the_notice_names_the_destination_beside_the_file_it_found(self):
        notice = legacy_format_notice(Path("/etc/desk-panel/config.json"))
        self.assertIn(str(Path("/etc/desk-panel/config.toml")), notice)

    def test_an_explicit_path_is_told_that_dropping_a_file_in_is_not_enough(self):
        # The advice for the fallback is a silent no-op for a launcher-passed
        # path: config_search_paths never upgrades one, and install_task.ps1
        # bakes an absolute --config into the Scheduled Task. An owner who
        # followed it would move their tickers and their token into a file
        # nothing reads and see the old panel with nothing to explain it.
        notice = legacy_format_notice(Path("/etc/desk-panel/config.json"), explicit=True)
        self.assertIn("--config", notice)
        self.assertIn("install_task.ps1", notice)
        # And it must not repeat the fallback's instruction, which is the
        # part that would not work.
        self.assertNotIn(
            f"Copy {EXAMPLE} to {Path('/etc/desk-panel/config.toml')}", notice
        )

    def test_an_explicit_toml_path_still_gets_no_notice(self):
        self.assertIsNone(
            legacy_format_notice(Path("/etc/desk-panel/config.toml"), explicit=True)
        )

    def test_a_toml_config_gets_no_notice(self):
        self.assertIsNone(legacy_format_notice(Path("/etc/desk-panel/config.toml")))

    def test_the_committed_example_is_silent(self):
        # T3.11's acceptance loads config.example.json on every run. A line
        # nagging about a file nobody edited is how people learn to skim the
        # output -- the same argument config_permission_warning makes about
        # the mode bits on that same file.
        self.assertIsNone(legacy_format_notice(Path("server/config.example.json")))


if __name__ == "__main__":
    unittest.main()
