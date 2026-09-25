"""TT.4 -- the contract file's own assertions, and its own guard, offline.

`contract_upstream.py` is the alarm that says the recorded fixtures have gone
stale. An alarm that cannot go off is worse than no alarm, and this repository
has shipped four acceptance criteria that could not fail -- wave 22 built
`--expect-header` and tested it four ways before trusting it, for exactly this
reason. `ContractCase`'s helpers are a new assertion mechanism, so they get the
same treatment here: proved to pass on a good body, proved to fail on a bad
one, and proved to name the field in the message.

Nothing in this file touches the network. It never calls a provider; it feeds
the helpers dictionaries.

The two structural facts it also pins:

- **the filename.** `contract_upstream.py` does not match `test*.py`, which is
  the only reason `make check` and CI stay offline. Rename it to
  `test_contract.py` and every build starts calling five APIs, with no test
  going red to say so.
- **the guard.** `RUN_CONTRACT_TESTS` unset means skipped, set means run. A
  guard that silently stopped skipping would reach CI as flakiness blamed on
  the network.
"""
import fnmatch
import os
import unittest
from pathlib import Path

from server.tests import contract_upstream


FIXTURE = "server/tests/fixtures/example.json"


def probe():
    """A ContractCase to call helpers on, built inside a function.

    Not declared at module level, and the reason is unittest's loader: it
    collects **every** TestCase subclass it finds in a module, so a
    module-level probe class is itself run as a test -- with `runTest` as its
    one method, because that is the default method name `TestCase()` binds to
    when constructed without one. Declared here, the loader never sees it.
    """

    class Probe(contract_upstream.ContractCase):
        fixture = FIXTURE

        def runTest(self):  # pragma: no cover - bound, never run
            pass

    return Probe()


class HelpersPassOnAGoodBody(unittest.TestCase):
    def setUp(self):
        self.probe = probe()

    def test_numeric_accepts_a_json_number_and_a_string(self):
        # brapi sends numbers, Binance and AwesomeAPI send the same
        # quantities as strings. Both are the contract.
        self.assertEqual(self.probe.numeric({"bid": 5.42}, "bid", "USDBRL"), 5.42)
        self.assertEqual(self.probe.numeric({"bid": "5.42"}, "bid", "USDBRL"), 5.42)

    def test_numeric_accepts_zero(self):
        # 0.0 is falsy and is a real reading: a change of exactly zero on a
        # flat day must not be read as a missing field.
        self.assertEqual(self.probe.numeric({"pctChange": "0.00"}, "pctChange", "x"), 0.0)

    def test_text_returns_the_string(self):
        self.assertEqual(self.probe.text({"symbol": "PETR4"}, "symbol", "r[0]"), "PETR4")

    def test_seq_and_obj_return_what_they_checked(self):
        self.assertEqual(self.probe.seq([1], "results"), [1])
        self.assertEqual(self.probe.obj({"a": 1}, "current"), {"a": 1})

    def test_key_returns_a_value_that_is_present_and_false(self):
        # is_day arrives as 0 at night, and `key` must not confuse "present
        # and falsy" with "gone" -- the open-meteo case checks presence only
        # because 0 is the answer that matters.
        self.assertEqual(self.probe.key({"is_day": 0}, "is_day", "current"), 0)


class HelpersFailAndSayWhere(unittest.TestCase):
    """Every helper, given the failure it exists to catch."""

    def setUp(self):
        self.probe = probe()

    def assertFailsNaming(self, path, call, *args):
        with self.assertRaises(AssertionError) as caught:
            call(*args)
        message = str(caught.exception)
        self.assertIn(path, message, f"the message does not name {path}: {message}")
        return message

    def test_missing_key_names_the_path(self):
        self.assertFailsNaming("USDBRL.bid", self.probe.numeric, {}, "bid", "USDBRL")

    def test_missing_key_points_at_the_fixture_to_re_record(self):
        message = self.assertFailsNaming(
            "results[0].symbol", self.probe.text, {}, "symbol", "results[0]")
        self.assertIn(FIXTURE, message)
        self.assertIn("TT.4", message)

    def test_a_number_that_became_a_word_is_caught(self):
        self.assertFailsNaming(
            "USDBRL.bid", self.probe.numeric, {"bid": "unavailable"}, "bid", "USDBRL")

    def test_a_number_that_became_an_object_is_caught(self):
        # The realistic schema change: a scalar wrapped in an envelope.
        # `float({"value": 1})` raises TypeError, which `numeric` turns into a
        # named failure rather than an error with no path in it.
        self.assertFailsNaming(
            "USDBRL.bid", self.probe.numeric, {"bid": {"value": 1}}, "bid", "USDBRL")

    def test_null_is_not_a_number(self):
        self.assertFailsNaming(
            "current.temperature_2m", self.probe.numeric,
            {"temperature_2m": None}, "temperature_2m", "current")

    def test_true_is_not_a_number(self):
        # float(True) is 1.0, so without the bool guard a field that turned
        # into a flag would sail through as a price of one.
        self.assertFailsNaming(
            "x.price", self.probe.numeric, {"price": True}, "price", "x")

    def test_an_empty_array_is_a_failure_not_an_index_error(self):
        # brapi answering `{"results": []}` for a delisted ticker is the live
        # case: `seq` has to fail with a message rather than let the caller
        # raise IndexError on [0], which names no field at all.
        self.assertFailsNaming("results", self.probe.seq, [], "results")

    def test_an_object_where_an_array_was_expected_is_caught(self):
        self.assertFailsNaming("daily.time", self.probe.seq, {"0": "x"}, "daily.time")

    def test_an_array_where_an_object_was_expected_is_caught(self):
        # A captive portal or a changed error envelope answering with a JSON
        # array is the case providers_brapi.normalise already guards against.
        self.assertFailsNaming("current", self.probe.obj, [], "current")

    def test_a_string_field_that_went_empty_is_caught(self):
        self.assertFailsNaming(
            "results[0].name", self.probe.text, {"name": "   "}, "name", "results[0]")

    def test_a_string_field_that_became_a_number_is_caught(self):
        self.assertFailsNaming(
            "results[0].symbol", self.probe.text, {"symbol": 4}, "symbol", "results[0]")

    def test_reading_a_key_out_of_a_non_object_names_the_path(self):
        self.assertFailsNaming("results[0]", self.probe.key, ["a"], "symbol", "results[0]")


class TheGuardAndTheFilename(unittest.TestCase):
    def test_the_filename_is_invisible_to_default_discovery(self):
        # `python -m unittest discover -s server/tests -t .` uses test*.py.
        # This is the whole reason `make check` never opens a socket.
        self.assertFalse(
            fnmatch.fnmatch("contract_upstream.py", "test*.py"),
            "contract_upstream.py now matches the default discovery pattern - "
            "every offline run would start calling five live APIs")

    def test_the_file_is_where_the_makefile_looks_for_it(self):
        # `make contract` passes -p "contract_*.py"; a file that stopped
        # matching would be skipped by being absent, and report OK.
        path = Path(contract_upstream.__file__)
        self.assertTrue(fnmatch.fnmatch(path.name, "contract_*.py"))
        self.assertTrue(path.is_file())

    def test_the_guard_follows_the_environment_variable(self):
        # Asserted against the live env rather than pinned to "skipped", so
        # this passes in both directions: `make test-server` skips,
        # `RUN_CONTRACT_TESTS=1 make test-server` does not.
        expected = bool(os.environ.get("RUN_CONTRACT_TESTS"))

        @contract_upstream.LIVE
        class Guarded(unittest.TestCase):
            pass

        self.assertEqual(getattr(Guarded, "__unittest_skip__", False), not expected)

    def test_every_contract_class_carries_the_guard(self):
        # A case added without @LIVE would hit the network from `make check`.
        # Found by walking the module rather than by review -- which is why
        # LIVE sets `needs_network` itself instead of leaving the check to
        # `__unittest_skip__`: skipUnless is the identity function once
        # RUN_CONTRACT_TESTS is set, and this test would then call every
        # class unguarded.
        unguarded = [
            name for name, obj in vars(contract_upstream).items()
            if isinstance(obj, type) and issubclass(obj, unittest.TestCase)
            and obj is not contract_upstream.ContractCase
            and not getattr(obj, "needs_network", False)
        ]
        self.assertEqual(
            unguarded, [],
            f"contract cases without @LIVE, which would run offline: {unguarded}")


if __name__ == "__main__":
    unittest.main()
