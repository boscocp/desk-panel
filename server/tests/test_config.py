"""Unit tests for server.load_config -- no network, no real config.json.

Every fixture here is a throwaway temp file; server/config.json (the real,
gitignored one holding the brapi token) is never read or written by these
tests -- see server/CLAUDE.md.
"""
import json
import tempfile
import unittest
from pathlib import Path

from server.server import ConfigError, DEFAULT_CONFIG, load_config


class LoadConfigTests(unittest.TestCase):
    def test_missing_file_raises_config_error_pointing_at_example(self):
        missing = Path(tempfile.gettempdir()) / "desk-panel-test-missing-config.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(ConfigError) as ctx:
            load_config(missing)
        self.assertIn("config.example.json", str(ctx.exception))

    def test_malformed_json_raises_config_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not valid json")
            path = Path(fh.name)
        try:
            with self.assertRaises(ConfigError):
                load_config(path)
        finally:
            path.unlink()

    def test_partial_config_is_filled_with_defaults(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"quotes": ["PETR4"]}, fh)
            path = Path(fh.name)
        try:
            config = load_config(path)
            self.assertEqual(config["quotes"], ["PETR4"])
            self.assertEqual(config["city"], DEFAULT_CONFIG["city"])
            self.assertEqual(config["brapi_token"], DEFAULT_CONFIG["brapi_token"])
        finally:
            path.unlink()

    def test_full_config_values_override_defaults(self):
        example = Path(__file__).resolve().parent.parent / "config.example.json"
        config = load_config(example)
        self.assertEqual(config["quotes"], ["PETR4", "VALE3", "ITUB4"])
        self.assertEqual(config["fx"], ["USD-BRL", "EUR-BRL"])
        self.assertEqual(config["timezone"], "America/Sao_Paulo")

    def test_json_array_is_rejected_even_though_it_parses(self):
        # Valid JSON, but not an object -- config.update(data) would raise
        # a confusing ValueError deep inside load_config if this guard
        # were removed.
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(["PETR4", "VALE3"], fh)
            path = Path(fh.name)
        try:
            with self.assertRaises(ConfigError) as ctx:
                load_config(path)
            self.assertIn("must contain a JSON object", str(ctx.exception))
        finally:
            path.unlink()

    def test_secret_never_appears_in_a_config_error_message(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not valid json, token=super-secret-token")
            path = Path(fh.name)
        try:
            with self.assertRaises(ConfigError) as ctx:
                load_config(path)
            self.assertNotIn("super-secret-token", str(ctx.exception))
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
