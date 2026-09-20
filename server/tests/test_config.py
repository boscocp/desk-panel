"""Unit tests for server.load_config and the two committed example files --
no network, no real config.

Every fixture here is a throwaway temp file; the real config (gitignored,
holding the brapi token, in either format) is never read or written by these
tests -- see server/CLAUDE.md.
"""
import json
import tempfile
import unittest
from pathlib import Path

from server.server import ConfigError, DEFAULT_CONFIG, load_config

SERVER_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_TOML = SERVER_DIR / "config.example.toml"
EXAMPLE_JSON = SERVER_DIR / "config.example.json"


def write_temp(text, suffix):
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as fh:
        fh.write(text)
        return Path(fh.name)


class LoadConfigTests(unittest.TestCase):
    def test_missing_file_raises_config_error_pointing_at_example(self):
        missing = Path(tempfile.gettempdir()) / "desk-panel-test-missing-config.toml"
        self.assertFalse(missing.exists())
        with self.assertRaises(ConfigError) as ctx:
            load_config(missing)
        self.assertIn("config.example.toml", str(ctx.exception))

    def test_the_suffix_picks_the_parser(self):
        # The same bytes, twice. Valid TOML is not valid JSON, so a file read
        # with the wrong parser raises rather than quietly producing something
        # plausible -- which is what makes the suffix a safe thing to dispatch
        # on.
        toml_text = 'city = "Recife"\n'
        path = write_temp(toml_text, ".toml")
        try:
            self.assertEqual(load_config(path)["city"], "Recife")
        finally:
            path.unlink()

        path = write_temp(toml_text, ".json")
        try:
            with self.assertRaises(ConfigError):
                load_config(path)
        finally:
            path.unlink()

    def test_malformed_toml_raises_config_error(self):
        path = write_temp("quotes = [\n", ".toml")
        try:
            with self.assertRaises(ConfigError):
                load_config(path)
        finally:
            path.unlink()

    def test_malformed_json_raises_config_error(self):
        path = write_temp("{not valid json", ".json")
        try:
            with self.assertRaises(ConfigError):
                load_config(path)
        finally:
            path.unlink()

    def test_partial_toml_is_filled_with_defaults(self):
        path = write_temp('quotes = ["PETR4"]\n', ".toml")
        try:
            config = load_config(path)
            self.assertEqual(config["quotes"], ["PETR4"])
            self.assertEqual(config["city"], DEFAULT_CONFIG["city"])
            self.assertEqual(config["brapi_token"], DEFAULT_CONFIG["brapi_token"])
        finally:
            path.unlink()

    def test_partial_json_is_filled_with_defaults(self):
        # The transition half (T3.12 step 3): an owner who never renames
        # anything keeps exactly the behaviour they had.
        path = write_temp(json.dumps({"quotes": ["PETR4"]}), ".json")
        try:
            config = load_config(path)
            self.assertEqual(config["quotes"], ["PETR4"])
            self.assertEqual(config["city"], DEFAULT_CONFIG["city"])
        finally:
            path.unlink()

    def test_utf8_survives_the_read(self):
        # Windows defaults a text read to cp1252, and "Sao Paulo" is spelled
        # without the tilde in the examples precisely because of it. A config
        # the owner typed with one must still load -- the read is explicitly
        # UTF-8 (T3.11).
        path = write_temp('city = "São Paulo"\n', ".toml")
        try:
            self.assertEqual(load_config(path)["city"], "São Paulo")
        finally:
            path.unlink()

    def test_json_array_is_rejected_even_though_it_parses(self):
        path = write_temp(json.dumps(["PETR4", "VALE3"]), ".json")
        try:
            with self.assertRaises(ConfigError) as ctx:
                load_config(path)
            self.assertIn("must contain a JSON object", str(ctx.exception))
        finally:
            path.unlink()

    def test_secret_never_appears_in_a_config_error_message(self):
        for text, suffix in (("{not valid json, token=super-secret-token", ".json"),
                             ("brapi_token = super-secret-token\n", ".toml")):
            with self.subTest(suffix=suffix):
                path = write_temp(text, suffix)
                try:
                    with self.assertRaises(ConfigError) as ctx:
                        load_config(path)
                    self.assertNotIn("super-secret-token", str(ctx.exception))
                finally:
                    path.unlink()


class ExampleFileTests(unittest.TestCase):
    """The examples are documentation, and documentation rots silently.

    The TOML one is where the catalogue of legal values lives, so a key
    added to DEFAULT_CONFIG and not to it is a key no owner ever finds out
    about. Both directions are checked, and both files, because they have
    to stay interchangeable for as long as the JSON one is read at all.
    """

    def test_both_examples_load(self):
        for example in (EXAMPLE_TOML, EXAMPLE_JSON):
            with self.subTest(example=example.name):
                self.assertEqual(load_config(example)["fx"], ["USD-BRL", "EUR-BRL"])
                self.assertEqual(load_config(example)["timezone"], "America/Sao_Paulo")

    def test_the_two_examples_agree_key_for_key_and_value_for_value(self):
        self.assertEqual(load_config(EXAMPLE_TOML), load_config(EXAMPLE_JSON))

    def test_the_toml_example_carries_every_default_key_and_no_others(self):
        import tomllib

        keys = set(tomllib.loads(EXAMPLE_TOML.read_text(encoding="utf-8")))
        self.assertEqual(keys, set(DEFAULT_CONFIG))

    def test_the_example_does_not_ship_an_interval_that_exhausts_the_free_plan(self):
        # It did. The example shipped 300 while the default was 600, and the
        # arithmetic beside DEFAULT_CONFIG says why 300 is wrong: three
        # tickers at one request each, every 300s, is 25,920 requests a month
        # against brapi's 15,000, so the B3 card goes permanently stale around
        # the 17th. Copying the example was the documented first step.
        for example in (EXAMPLE_TOML, EXAMPLE_JSON):
            with self.subTest(example=example.name):
                self.assertGreaterEqual(
                    load_config(example)["quotes_interval_s"],
                    DEFAULT_CONFIG["quotes_interval_s"],
                )

    def test_the_example_ships_no_token(self):
        for example in (EXAMPLE_TOML, EXAMPLE_JSON):
            with self.subTest(example=example.name):
                self.assertEqual(load_config(example)["brapi_token"], "")

    def test_the_toml_example_names_every_free_tier_ticker_it_recommends(self):
        # The catalogue is the deliverable, so it is checked against the
        # provider rather than trusted: a free-tier ticker that stops being
        # one, or a fifth that appears, must not leave the file claiming
        # otherwise.
        from server.providers_brapi import FREE_TIER_SYMBOLS

        text = EXAMPLE_TOML.read_text(encoding="utf-8")
        for symbol in FREE_TIER_SYMBOLS:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, text)
        # And every ticker it actually configures is one of them, since the
        # example ships no token.
        self.assertTrue(set(load_config(EXAMPLE_TOML)["quotes"]) <= set(FREE_TIER_SYMBOLS))


if __name__ == "__main__":
    unittest.main()
