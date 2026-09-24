"""Unit tests for probe.py's pure assertion helpers.

`--expect-header` was added for T3.6, whose acceptance rests entirely on it:
the task file's own note says the criterion it replaced -- `curl -sI | grep -i
content-type` -- succeeded whenever *any* content-type came back. An assertion
that cannot fail is the failure mode this repository has paid for repeatedly
(T0.5, T6.6, `scripts/check_acceptance.py`), so the half that decides lives in
a pure function and is tested here rather than only exercised.

probe.py is deliberately importable from anywhere: it has no dependency on
server.py and must be able to probe a machine with no checkout at all.
"""
import unittest

from server.probe import mismatched_headers


class MismatchedHeaderTests(unittest.TestCase):
    APK = [
        ("Content-Type", "application/vnd.android.package-archive"),
        ("Content-Length", "1679711"),
        ("Content-Disposition", 'attachment; filename="desk-panel-release.apk"'),
    ]

    def test_an_exact_match_is_no_complaint(self):
        self.assertEqual(
            mismatched_headers(
                self.APK, ["content-type=application/vnd.android.package-archive"]
            ),
            [],
        )

    def test_the_name_is_case_insensitive(self):
        # RFC 9110. http.server sends "Content-Type"; the acceptance line in
        # the task file writes it lower case, and both must work.
        self.assertEqual(
            mismatched_headers(
                self.APK, ["CONTENT-TYPE=application/vnd.android.package-archive"]
            ),
            [],
        )

    def test_a_prefix_does_not_match(self):
        # The point of the whole option. `text/html` contains `text/htm`, and
        # a substring test would pass for the wrong server.
        problems = mismatched_headers(self.APK, ["content-type=application/vnd.android.package"])
        self.assertEqual(len(problems), 1)
        self.assertIn("wanted", problems[0])

    def test_a_wrong_value_names_both_sides(self):
        problems = mismatched_headers(self.APK, ["content-type=text/html"])
        self.assertEqual(len(problems), 1)
        self.assertIn("application/vnd.android.package-archive", problems[0])
        self.assertIn("text/html", problems[0])

    def test_an_absent_header_is_reported_as_absent(self):
        problems = mismatched_headers([("Content-Type", "application/json")], ["etag=abc"])
        self.assertEqual(problems, ["no etag header"])

    def test_every_expectation_is_checked_not_just_the_first(self):
        problems = mismatched_headers(self.APK, ["content-type=text/html", "etag=abc"])
        self.assertEqual(len(problems), 2)

    def test_surrounding_whitespace_is_not_the_assertion(self):
        self.assertEqual(mismatched_headers([("ETag", " abc ")], ["etag= abc "]), [])

    def test_a_repeated_header_matches_on_any_of_its_values(self):
        # http.client keeps duplicates; folding them into one string would
        # make an exact comparison fail against a perfectly good response.
        headers = [("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")]
        self.assertEqual(mismatched_headers(headers, ["set-cookie=b=2"]), [])

    def test_a_value_containing_an_equals_sign_survives_the_split(self):
        # partition, not split: the first `=` separates name from value and
        # every later one belongs to the value.
        self.assertEqual(
            mismatched_headers(
                [("Content-Type", "text/html; charset=utf-8")],
                ["content-type=text/html; charset=utf-8"],
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
