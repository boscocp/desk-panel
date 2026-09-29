"""market_hours -- B3's window, both seasons, and the config that sets it.

Every instant is written in Sao Paulo time, because that is how B3 publishes
its schedule and how anybody checking these would read it.
"""
import datetime
import unittest

from server import market_hours
from server.market_hours import B3_TZ, exchange_open, hours_from_config, is_open


def at(text):
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=B3_TZ)


class UsSummerTimeTests(unittest.TestCase):
    def test_2026_starts_on_the_second_sunday_of_march(self):
        self.assertFalse(market_hours.us_summer_time(datetime.date(2026, 3, 7)))
        self.assertTrue(market_hours.us_summer_time(datetime.date(2026, 3, 8)))

    def test_2026_ends_on_the_first_sunday_of_november(self):
        self.assertTrue(market_hours.us_summer_time(datetime.date(2026, 10, 31)))
        self.assertFalse(market_hours.us_summer_time(datetime.date(2026, 11, 1)))

    def test_a_month_starting_on_sunday_counts_that_sunday(self):
        # March 2026 begins on a Sunday, so the second Sunday is the 8th and
        # not the 15th -- the off-by-a-week this arithmetic would get wrong.
        self.assertEqual(market_hours._nth_sunday(2026, 3, 2), datetime.date(2026, 3, 8))
        self.assertEqual(market_hours._nth_sunday(2027, 3, 2), datetime.date(2027, 3, 14))
        self.assertEqual(market_hours._nth_sunday(2027, 11, 1), datetime.date(2027, 11, 7))


class ExchangeOpenTests(unittest.TestCase):
    def test_b3_closes_at_17h_while_the_us_is_on_summer_time(self):
        # B3 moved to 10:00-17:00 on Monday 2026-03-09, the day after the US.
        self.assertTrue(exchange_open(at("2026-09-29 16:59")))
        self.assertFalse(exchange_open(at("2026-09-29 17:00")))
        self.assertFalse(exchange_open(at("2026-03-09 17:30")))

    def test_b3_closes_at_18h_the_rest_of_the_year(self):
        self.assertTrue(exchange_open(at("2026-03-06 17:30")))
        self.assertTrue(exchange_open(at("2026-11-02 17:59")))
        self.assertFalse(exchange_open(at("2026-11-02 18:00")))

    def test_it_opens_at_10h(self):
        self.assertFalse(exchange_open(at("2026-09-29 09:59")))
        self.assertTrue(exchange_open(at("2026-09-29 10:00")))

    def test_weekends_are_closed(self):
        self.assertFalse(exchange_open(at("2026-10-03 14:00")))
        self.assertFalse(exchange_open(at("2026-10-04 14:00")))

    def test_the_zone_of_the_instant_does_not_matter(self):
        # 20:30 UTC is 17:30 in Sao Paulo: after the close in September.
        utc = datetime.datetime(2026, 9, 29, 20, 30, tzinfo=datetime.timezone.utc)
        self.assertFalse(exchange_open(utc))
        self.assertTrue(exchange_open(utc - datetime.timedelta(hours=4)))


class IsOpenTests(unittest.TestCase):
    def test_auto_keeps_asking_for_brapis_delay_after_the_close(self):
        self.assertTrue(is_open(at("2026-09-29 17:44"), "auto"))
        self.assertFalse(is_open(at("2026-09-29 17:45"), "auto"))
        self.assertTrue(is_open(at("2026-11-02 18:44"), "auto"))
        self.assertFalse(is_open(at("2026-11-02 18:45"), "auto"))

    def test_a_fixed_window_ignores_the_season(self):
        hours = (10 * 60, 18 * 60 + 30)
        self.assertTrue(is_open(at("2026-09-29 18:29"), hours))
        self.assertFalse(is_open(at("2026-09-29 18:30"), hours))
        self.assertFalse(is_open(at("2026-10-03 12:00"), hours))

    def test_it_starts_asking_at_the_open(self):
        self.assertFalse(is_open(at("2026-09-29 09:59"), "auto"))
        self.assertTrue(is_open(at("2026-09-29 10:00"), "auto"))
        self.assertTrue(is_open(at("2026-09-29 10:00"), (600, 1110)))

    def test_none_is_always_open(self):
        self.assertTrue(is_open(at("2026-10-04 03:00"), None))


class LastCloseTests(unittest.TestCase):
    def test_the_close_itself_counts_as_closed(self):
        self.assertEqual(market_hours.last_close(at("2026-09-29 17:45"), "auto"),
                         at("2026-09-29 17:45"))

    def test_the_same_day_once_it_has_closed(self):
        self.assertEqual(market_hours.last_close(at("2026-09-29 22:00"), "auto"),
                         at("2026-09-29 17:45"))

    def test_the_previous_weekday_before_it_has(self):
        self.assertEqual(market_hours.last_close(at("2026-09-29 09:00"), "auto"),
                         at("2026-09-28 17:45"))

    def test_friday_over_the_weekend_and_on_monday_morning(self):
        self.assertEqual(market_hours.last_close(at("2026-10-04 14:00"), "auto"),
                         at("2026-10-02 17:45"))
        self.assertEqual(market_hours.last_close(at("2026-10-05 09:00"), "auto"),
                         at("2026-10-02 17:45"))

    def test_the_winter_close_and_a_fixed_window(self):
        self.assertEqual(market_hours.last_close(at("2026-11-02 20:00"), "auto"),
                         at("2026-11-02 18:45"))
        self.assertEqual(market_hours.last_close(at("2026-11-02 20:00"), (600, 1110)),
                         at("2026-11-02 18:30"))

    def test_no_gate_has_no_close(self):
        self.assertIsNone(market_hours.last_close(at("2026-11-02 20:00"), None))


class HoursFromConfigTests(unittest.TestCase):
    def test_absent_is_auto(self):
        self.assertEqual(hours_from_config({}), "auto")

    def test_the_three_legal_shapes(self):
        self.assertEqual(hours_from_config({"b3_hours": "auto"}), "auto")
        self.assertIsNone(hours_from_config({"b3_hours": []}))
        self.assertEqual(hours_from_config({"b3_hours": ["10:00", "24:00"]}), (600, 1440))

    def test_everything_else_raises(self):
        for bad in ("always", ["10:00"], ["18:00", "10:00"], ["10:00", "10:00"],
                    ["9:00", "18:00"], ["10:00", "18:60"], ["10:00", "24:01"],
                    ["10:000", "18:00"], ["10:00", "018:00"], ["１０:００", "18:00"],
                    ["²0:00", "18:00"],
                    [10, 18], {"open": "10:00"}, None, True):
            with self.subTest(b3_hours=bad):
                with self.assertRaises(ValueError):
                    hours_from_config({"b3_hours": bad})


if __name__ == "__main__":
    unittest.main()
