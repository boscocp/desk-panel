"""T6.13: the moon's phase, and which of the two answers gave it.

The fixture is a real recorded response --
`GET aa.usno.navy.mil/api/moon/phases/date?date=2026-08-18&nump=9`, the exact
request `fetch_phases` builds for a late-September evening -- so the window's
two constants are exercised rather than described. The first cut of them asked
for six phases from 45 days back, which spans 44 days: the window could end
before now, `phase_at` correctly refused to answer, and every panel would have
quietly fallen back to the arithmetic. That is what
`test_the_shipped_window_brackets_the_moment_it_is_asked_about` is for, and it
is the most valuable assertion in the file -- a fallback that fires always is
indistinguishable from a fallback that works.

The phase numbers are checked against sources **outside this repository**,
which the task file asks for in a sentence and which matters more here than
usual: a fixture invented from the same formula it is testing asserts nothing.
For 2026-09-22T00:27Z:

  - the USNO's own New Moon of 2026-09-11 03:27 UTC puts the true age at
    10.875 days,
  - moongiant.com, consulted independently, says 10.77 days and 83% lit,
  - this module, deriving from the fixture's lunation, says 10.88 and 84%,
  - the mean-synodic fallback says 10.16 and 78%.

That last line is the reason the API is the plan and the arithmetic is the net.
The fallback is a **naming** model: it was checked against the USNO's 2026 and
2027 tables -- 99 primary phases, every one named correctly, worst error 0.87
days against a bucket half-width of 1.85 -- and its age is most of a day out,
which is a visibly different moon on the nights either side of a quarter.
"""
import datetime
import json
import pathlib
import unittest

from server import providers_usno
from server.upstream import UpstreamError

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# The evening the task came from, as the chair saw it: 21:20 in Sao Paulo on
# 2026-09-21 is 2026-09-22T00:27Z once the panel's own clock is allowed for.
WHEN = datetime.datetime(2026, 9, 22, 0, 27, tzinfo=datetime.timezone.utc)


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def recorded(name):
    """A `get` that returns a fixture and records the URL it was asked for."""
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return fixture(name)

    get.calls = calls
    return get


class WindowTests(unittest.TestCase):
    def test_fetch_builds_the_window_from_the_moment_asked_about(self):
        get = recorded("usno_phases.json")
        providers_usno.fetch_phases(WHEN, get=get)
        self.assertEqual(len(get.calls), 1)
        # The date is five weeks before the moment, not today: a panel asking
        # about an instant must not get a window centred on the wall clock of
        # whatever machine it runs on.
        self.assertIn("date=2026-08-18", get.calls[0])
        self.assertIn("nump=9", get.calls[0])

    def test_the_shipped_window_brackets_the_moment_it_is_asked_about(self):
        # The assertion the first implementation failed. A window that does not
        # bracket `when` with a New Moon on each side makes `phase_at` return
        # None for ever, and the panel then runs on the fallback while looking
        # exactly as if it were running on the API.
        phases = providers_usno.normalise_phases(fixture("usno_phases.json"))
        news = [p["when"] for p in phases if p["phase"] == "new"]
        self.assertTrue(any(t <= WHEN for t in news),
                        "no New Moon before the moment asked about")
        self.assertTrue(any(t > WHEN for t in news),
                        "no New Moon after the moment asked about")
        self.assertIsNotNone(providers_usno.phase_at(phases, WHEN))


class PhaseTests(unittest.TestCase):
    def test_the_fixture_gives_the_age_two_outside_sources_agree_on(self):
        phases = providers_usno.normalise_phases(fixture("usno_phases.json"))
        answer = providers_usno.phase_at(phases, WHEN)
        self.assertEqual(answer["phase"], "waxing-gibbous")
        self.assertEqual(answer["source"], "usno")
        # 10.875 from the USNO's own New Moon, 10.77 from moongiant: a tenth of
        # a day of tolerance covers the difference between two published
        # models and nothing like a bug.
        self.assertAlmostEqual(answer["ageDays"], 10.88, delta=0.15)
        self.assertAlmostEqual(answer["illum"], 83, delta=2)
        # The real lunation, not the mean one. If this ever equals
        # SYNODIC_DAYS, the derivation has stopped using the table.
        self.assertNotAlmostEqual(answer["lunationDays"],
                                  providers_usno.SYNODIC_DAYS, places=3)

    def test_the_fallback_names_the_same_phase_and_is_a_day_out(self):
        # Both halves matter. The name is what the panel draws, so the fallback
        # has to get it right; the age is what it cannot get right, and saying
        # so here is what stops somebody "simplifying" the API away.
        mean = providers_usno.synodic_phase(WHEN)
        self.assertEqual(mean["phase"], "waxing-gibbous")
        self.assertEqual(mean["source"], "mean")
        self.assertAlmostEqual(mean["ageDays"], 10.16, delta=0.05)
        phases = providers_usno.normalise_phases(fixture("usno_phases.json"))
        truth = providers_usno.phase_at(phases, WHEN)
        self.assertGreater(abs(truth["ageDays"] - mean["ageDays"]), 0.5,
                           "the fallback has stopped being the approximation "
                           "this module documents")

    def test_the_buckets_are_centred_on_the_phases(self):
        # The day of the full moon is `full`, not `waxing-gibbous` by a few
        # hours. Checked at the instant itself and an hour either side, off the
        # fixture's own Full Moon of 2026-09-26 16:49 UTC.
        phases = providers_usno.normalise_phases(fixture("usno_phases.json"))
        full = datetime.datetime(2026, 9, 26, 16, 49,
                                 tzinfo=datetime.timezone.utc)
        for offset in (-1, 0, 1):
            moment = full + datetime.timedelta(hours=offset)
            self.assertEqual(
                providers_usno.phase_at(phases, moment)["phase"], "full",
                "%+dh from the full moon is not `full`" % offset)

    def test_every_name_in_the_cycle_is_reachable_and_in_order(self):
        # Walk one lunation and assert the eight names come round once, in the
        # table's order. A waxing crescent drawn as a waning one is wrong in
        # the one way somebody can check by looking out of the window.
        phases = providers_usno.normalise_phases(fixture("usno_phases.json"))
        start = datetime.datetime(2026, 9, 11, 3, 27,
                                  tzinfo=datetime.timezone.utc)
        seen = []
        for hour in range(0, 709):  # 29.5 days
            name = providers_usno.phase_at(
                phases, start + datetime.timedelta(hours=hour))["phase"]
            if not seen or seen[-1] != name:
                seen.append(name)
        # It starts and ends on `new`, so the first and last are the same name.
        self.assertEqual(seen[0], "new")
        self.assertEqual(seen[-1], "new")
        self.assertEqual(tuple(seen[:-1]), providers_usno.PHASE_NAMES)


class CrossFileTests(unittest.TestCase):
    """The server names the phase; format.js says what the name is called."""

    def test_the_two_phase_lists_have_not_drifted(self):
        # Both files carry the eight names in the order a lunation visits them,
        # and the comments in both promise the other agrees. A promise with no
        # check behind it is how this repository has already shipped four wrong
        # claims, so this reads the JavaScript.
        #
        # Drift here is the worst kind of wrong: the panel would draw a waxing
        # crescent and label it waning, and both halves would look correct on
        # their own. It is also the one error a reader can catch by looking out
        # of a window, which is the whole reason the phase is drawn at all.
        import pathlib
        import re

        source = (pathlib.Path(__file__).parents[2] / "web" / "js" / "format.js"
                  ).read_text(encoding="utf-8")
        match = re.search(r"const MOON_PHASES = \[(.*?)\];", source, re.S)
        self.assertIsNotNone(match, "format.js no longer declares MOON_PHASES")
        names = tuple(re.findall(r"'([a-z-]+)'", match.group(1)))
        self.assertEqual(names, providers_usno.PHASE_NAMES)

    def test_the_glyph_names_the_night_sky_uses_are_not_phase_names(self):
        # `stars` and `cloudy-night` are sky glyphs, not moon phases, and a
        # code that returned one where the other was expected would draw a
        # cloud for a full moon. Cheap to keep the two sets disjoint.
        import pathlib
        import re

        source = (pathlib.Path(__file__).parents[2] / "web" / "js" / "format.js"
                  ).read_text(encoding="utf-8")
        match = re.search(r"const NIGHT_GLYPHS = \{(.*?)\};", source, re.S)
        self.assertIsNotNone(match, "format.js no longer declares NIGHT_GLYPHS")
        glyphs = set(re.findall(r"'([a-z-]+)'", match.group(1)))
        self.assertTrue(glyphs)
        self.assertEqual(glyphs & set(providers_usno.PHASE_NAMES), set())


class DegradingTests(unittest.TestCase):
    """It raises, and the caller owns the fallback. That split is the point.

    `moon_phase` used to swallow everything and return `synodic_phase` itself.
    The review of this wave caught what that cost: `server.py` caches it through
    `TimedCache`, a function that never fails is always a success, so the
    arithmetic answer was recorded with `stale = False` and held for the full
    six-hour interval -- and the `or synodic_phase()` at the call site was dead
    code, because a producer that cannot fail cannot leave the cache empty.

    A PC that boots before its router is all it takes, which is the same case
    `TimedCache.fresh_at`'s own docstring was written for.
    """

    def test_a_dead_upstream_raises_so_the_cache_can_retry(self):
        def boom(url, **kwargs):
            raise UpstreamError("no network")

        with self.assertRaises(UpstreamError):
            providers_usno.moon_phase(WHEN, get=boom)

    def test_a_junk_body_raises_rather_than_answering(self):
        for junk in ([1, 2], None, {}, {"phasedata": "nope"},
                     {"phasedata": [{"phase": "New Moon"}]}):
            with self.subTest(body=junk):
                with self.assertRaises(UpstreamError):
                    providers_usno.moon_phase(WHEN, get=lambda u, **k: junk)

    def test_a_window_that_misses_raises_rather_than_guessing(self):
        # A body that parsed and does not bracket the moment. Not an outage and
        # not an answer: `phase_at` refuses to invent a lunation length, and
        # this refuses to dress that up as a success the cache would keep.
        stale = {"phasedata": [
            {"day": 12, "month": 8, "phase": "New Moon", "time": "17:37",
             "year": 2026},
        ]}
        with self.assertRaises(UpstreamError):
            providers_usno.moon_phase(WHEN, get=lambda u, **k: stale)

    def test_the_fallback_is_still_available_to_the_caller(self):
        # The other half: whoever catches the raise has something to draw, and
        # it says which model answered.
        mean = providers_usno.synodic_phase(WHEN)
        self.assertEqual(mean["source"], "mean")
        self.assertEqual(mean["phase"], "waxing-gibbous")

    def test_a_good_body_is_marked_usno_so_the_two_are_told_apart(self):
        answer = providers_usno.moon_phase(
            WHEN, get=recorded("usno_phases.json"))
        self.assertEqual(answer["source"], "usno")


class NothingRunsTests(unittest.TestCase):
    """No test above may touch the network."""

    def test_every_call_in_this_file_passes_its_own_get(self):
        # The rule server/CLAUDE.md sets for the whole unit suite: no test may
        # touch the network. The two functions here that can are the ones with
        # a `get` default, so this walks this file's syntax tree and fails any
        # call to either that leaves the default in place.
        #
        # An earlier version of this test searched its own source text for the
        # string "moon_phase()" -- and found it, inside its own assertion. A
        # check that cannot pass is no better than one that cannot fail.
        import ast
        import pathlib

        reaches_network = {"moon_phase", "fetch_phases"}
        tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
        missing = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name not in reaches_network:
                continue
            if not any(kw.arg == "get" for kw in node.keywords):
                missing.append("%s at line %d" % (name, node.lineno))
        self.assertEqual(missing, [],
                         "these calls would reach the real API: "
                         + ", ".join(missing))
        # And the sweep is worth something only if it found the calls at all.
        self.assertGreaterEqual(
            sum(1 for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and (getattr(node.func, "attr", None) in reaches_network)), 4,
            "the sweep found almost no calls, so it is not checking anything")


if __name__ == "__main__":
    unittest.main()
