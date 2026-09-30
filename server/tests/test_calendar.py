"""T9.1 -- the calendars, their OAuth, and what ADR 0017 promises about both.

No network: every token endpoint is a fake `post`, every calendar call a fake
`get`, and the recorded bodies are in fixtures/. The token file is a real file
in a temporary directory, because its mode bits are the property under test.
"""
import datetime
import json
import os
import re
import stat
import tempfile
import unittest
import unittest.mock
import urllib.error
import urllib.parse
from pathlib import Path

from server import oauth, providers_calendar
from server.server import App, host_allowed, route
from server.upstream import UpstreamError

SERVER_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOOGLE = json.loads((FIXTURES / "google_events.json").read_text(encoding="utf-8"))
GRAPH = json.loads((FIXTURES / "graph_calendarview.json").read_text(encoding="utf-8"))
NOW = datetime.datetime(2026, 9, 22, 9, 0, tzinfo=datetime.timezone.utc)

GOOGLE_GRANT = {"access_token": "at", "expires_in": 3599, "token_type": "Bearer",
                "scope": oauth.GOOGLE_SCOPE, "refresh_token": "rt-google"}
MICROSOFT_GRANT = {"access_token": "at", "expires_in": 3599, "token_type": "Bearer",
                   "scope": "https://graph.microsoft.com/Calendars.ReadBasic",
                   "refresh_token": "rt-microsoft"}


class Recorder:
    """A fake `post` that answers from a list and remembers what it was sent."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, fields):
        self.calls.append((url, dict(fields)))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)


class TempStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "calendar-tokens.json"
        self.store = oauth.TokenStore(self.path)


class ScopeTests(unittest.TestCase):
    """The read-only rule, in code (ADR 0017)."""

    def test_the_read_only_grants_pass(self):
        oauth.check_scope("google", oauth.GOOGLE_SCOPE)
        oauth.check_scope("microsoft", "https://graph.microsoft.com/Calendars.ReadBasic "
                                       "https://graph.microsoft.com/User.Read openid profile")
        oauth.check_scope("microsoft", "Calendars.ReadBasic offline_access")

    def test_a_write_scope_is_refused(self):
        for provider, scope in (
            ("google", oauth.GOOGLE_SCOPE + " https://www.googleapis.com/auth/calendar"),
            ("google", oauth.GOOGLE_SCOPE + " https://www.googleapis.com/auth/calendar.events"),
            ("microsoft", "Calendars.ReadBasic Calendars.ReadWrite"),
            ("microsoft", "https://graph.microsoft.com/Calendars.ReadBasic "
                          "https://graph.microsoft.com/Mail.Read"),
        ):
            with self.subTest(provider=provider, scope=scope):
                with self.assertRaises(oauth.ScopeError):
                    oauth.check_scope(provider, scope)

    def test_a_grant_without_the_calendar_is_refused(self):
        # Google's consent screen lets the owner untick the scope and still
        # finish; the result is a token that can read nothing.
        with self.assertRaises(oauth.ScopeError):
            oauth.check_scope("google", "openid email")
        with self.assertRaises(oauth.ScopeError):
            oauth.check_scope("microsoft", "")

    def test_a_grant_from_before_adr_0019_asks_for_a_reconnect(self):
        # T9.1's token: calendars the owner owns, and nothing else. It cannot
        # list or read the others, so it fails the check -- and "scope" is in
        # AUTH_ERRORS, which the card shows as "reconectar".
        with self.assertRaises(oauth.ScopeError):
            oauth.check_scope("google", oauth.GOOGLE_OWNED_SCOPE)
        self.assertIn("scope", oauth.AUTH_ERRORS)

    def test_both_google_scopes_are_required(self):
        # Unticking either one on the consent screen leaves a token that
        # cannot do the job: no list, or no events.
        for scope in (oauth.GOOGLE_EVENTS_SCOPE, oauth.GOOGLE_CALENDAR_LIST_SCOPE):
            with self.subTest(scope=scope):
                with self.assertRaises(oauth.ScopeError):
                    oauth.check_scope("google", scope)

    def test_the_old_scope_beside_the_new_ones_is_kept(self):
        # Google may hand back what an account granted this client before.
        oauth.check_scope("google", f"{oauth.GOOGLE_SCOPE} {oauth.GOOGLE_OWNED_SCOPE}")

    def test_a_broad_google_grant_is_not_kept_at_login_and_is_revoked(self):
        post = Recorder(dict(GOOGLE_GRANT, scope="https://www.googleapis.com/auth/calendar"), {})
        with self.assertRaises(oauth.ScopeError):
            oauth.google_exchange_code("cid", "sec", "code", "ver", "http://127.0.0.1:1", post=post)
        self.assertEqual(post.calls[1], (oauth.GOOGLE_REVOKE_URL, {"token": "rt-google"}))

    def test_an_absent_scope_means_the_one_requested(self):
        # RFC 6749 section 5.1, and Microsoft's own docs: omitted = identical.
        oauth.check_scope("microsoft", None, oauth.MICROSOFT_SCOPE)
        oauth.check_scope("google", None, oauth.GOOGLE_SCOPE)
        grant = {k: v for k, v in MICROSOFT_GRANT.items() if k != "scope"}
        self.assertEqual(oauth.microsoft_refresh("c", "rt", post=Recorder(grant))["access_token"], "at")

    def test_a_percent_encoded_scope_is_read_as_the_scope(self):
        oauth.check_scope("microsoft", "https%3A%2F%2Fgraph.microsoft.com%2FCalendars.ReadBasic")
        with self.assertRaises(oauth.ScopeError):
            oauth.check_scope("microsoft", "https%3A%2F%2Fgraph.microsoft.com%2FMail.Read "
                                           "Calendars.ReadBasic")


class GoogleFlowTests(unittest.TestCase):
    def test_pkce_is_s256_of_the_verifier(self):
        import base64
        import hashlib

        verifier, challenge = oauth.pkce_pair(lambda n: bytes(range(n)))
        self.assertEqual(len(verifier), 43)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)

    def test_the_auth_url_asks_for_the_read_only_scope_with_pkce_and_state(self):
        url = oauth.google_auth_url("cid", "http://127.0.0.1:5000", "chal", "st")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(query["scope"], [oauth.GOOGLE_SCOPE])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["code_challenge"], ["chal"])
        self.assertEqual(query["state"], ["st"])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:5000"])

    def test_the_exchange_sends_the_verifier_and_returns_the_refresh_token(self):
        post = Recorder(GOOGLE_GRANT)
        body = oauth.google_exchange_code("cid", "sec", "code", "ver", "http://127.0.0.1:1",
                                          post=post)
        self.assertEqual(body["refresh_token"], "rt-google")
        url, fields = post.calls[0]
        self.assertEqual(url, oauth.GOOGLE_TOKEN_URL)
        self.assertEqual(fields["code_verifier"], "ver")
        self.assertEqual(fields["grant_type"], "authorization_code")

    def test_an_error_names_the_error_and_never_the_code(self):
        post = Recorder({"error": "invalid_grant", "error_description": "Bad Request"})
        with self.assertRaises(oauth.OAuthError) as ctx:
            oauth.google_exchange_code("cid", "sec", "the-code", "the-verifier",
                                       "http://127.0.0.1:1", post=post)
        self.assertEqual(ctx.exception.code, "invalid_grant")
        self.assertNotIn("the-code", str(ctx.exception))
        self.assertNotIn("the-verifier", str(ctx.exception))


class RevokeTests(unittest.TestCase):
    def test_a_refused_revocation_raises(self):
        with self.assertRaises(oauth.OAuthError) as ctx:
            oauth.google_revoke("rt", post=Recorder({"error": "invalid_token"}))
        self.assertEqual(ctx.exception.code, "invalid_token")

    def test_an_empty_200_is_success(self):
        self.assertEqual(oauth.google_revoke("rt", post=Recorder({})), {})


class PostFormTests(unittest.TestCase):
    """Every failure leaves the module as OAuthError, never as something else."""

    def _post(self, side_effect):
        from unittest import mock

        with mock.patch.object(oauth.urllib.request, "urlopen", side_effect=side_effect):
            return oauth.post_form("https://example.invalid/token", {"secret": "s3cr3t"})

    def test_a_truncated_body_is_an_oauth_error(self):
        import http.client

        with self.assertRaises(oauth.OAuthError) as ctx:
            self._post(http.client.IncompleteRead(b"par"))
        self.assertEqual(ctx.exception.code, "network")
        self.assertNotIn("s3cr3t", str(ctx.exception))

    def test_a_400_with_json_is_returned_for_the_caller_to_read(self):
        import io

        error = urllib.error.HTTPError("u", 400, "Bad", {}, io.BytesIO(b'{"error": "authorization_pending"}'))
        self.assertEqual(self._post(error), {"error": "authorization_pending"})


class MicrosoftFlowTests(unittest.TestCase):
    DEVICE = {"device_code": "dc", "user_code": "ABCD-EFGH", "interval": 5,
              "expires_in": 900, "verification_uri": "https://microsoft.com/devicelogin"}

    def _poll(self, *answers):
        slept = []
        now = [0.0]

        def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds

        post = Recorder(*answers)
        result = oauth.microsoft_poll("cid", self.DEVICE, post=post, sleep=sleep,
                                      clock=lambda: now[0])
        return result, slept, post

    def test_pending_then_granted(self):
        result, slept, post = self._poll({"error": "authorization_pending"}, MICROSOFT_GRANT)
        self.assertEqual(result["refresh_token"], "rt-microsoft")
        self.assertEqual(slept, [5, 5])
        self.assertEqual(post.calls[0][1]["grant_type"],
                         "urn:ietf:params:oauth:grant-type:device_code")

    def test_slow_down_adds_five_seconds_for_good(self):
        # RFC 8628 section 3.5: "for this and all subsequent requests".
        _, slept, _ = self._poll({"error": "slow_down"}, {"error": "authorization_pending"},
                                 MICROSOFT_GRANT)
        self.assertEqual(slept, [5, 10, 10])

    def test_declined_and_expired_stop_polling(self):
        for error in ("authorization_declined", "expired_token", "bad_verification_code"):
            with self.subTest(error=error):
                with self.assertRaises(oauth.OAuthError) as ctx:
                    self._poll({"error": error})
                self.assertEqual(ctx.exception.code, error)

    def test_a_network_blip_doubles_the_interval_and_keeps_polling(self):
        # RFC 8628 section 3.5.
        result, slept, _ = self._poll(oauth.OAuthError("network"), MICROSOFT_GRANT)
        self.assertEqual(result["refresh_token"], "rt-microsoft")
        self.assertEqual(slept, [5, 10])

    def test_the_code_expiring_locally_stops_polling(self):
        device = dict(self.DEVICE, expires_in=7)
        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        post = Recorder({"error": "authorization_pending"}, {"error": "authorization_pending"})
        with self.assertRaises(oauth.OAuthError) as ctx:
            oauth.microsoft_poll("cid", device, post=post, sleep=sleep, clock=lambda: now[0])
        self.assertEqual(ctx.exception.code, "expired_token")

    def test_a_grant_without_a_refresh_token_is_refused(self):
        grant = {k: v for k, v in MICROSOFT_GRANT.items() if k != "refresh_token"}
        with self.assertRaises(oauth.OAuthError):
            self._poll(grant)

    def test_the_device_code_request_asks_for_read_basic_and_offline_access(self):
        post = Recorder(self.DEVICE)
        oauth.microsoft_device_code("cid", post=post)
        url, fields = post.calls[0]
        self.assertEqual(url, "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode")
        self.assertEqual(fields["scope"], "Calendars.ReadBasic offline_access")


class TokenStoreTests(TempStore):
    def test_round_trip_and_delete(self):
        self.assertIsNone(self.store.refresh_token("google/personal"))
        self.store.put("google/personal", "rt")
        self.assertEqual(self.store.refresh_token("google/personal"), "rt")
        self.store.delete("google/personal")
        self.assertIsNone(self.store.refresh_token("google/personal"))

    @unittest.skipIf(os.name == "nt", "mode bits are the ACL's job on Windows")
    def test_the_file_is_0600_even_over_a_loose_one(self):
        self.path.write_text("{}", encoding="utf-8")
        os.chmod(self.path, 0o644)
        self.store.put("microsoft/work", "rt")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_no_temporary_file_is_left_behind(self):
        self.store.put("a/b", "rt")
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()],
                         ["calendar-tokens.json"])

    def test_a_corrupt_file_is_an_error_that_does_not_quote_it(self):
        self.path.write_text('{"google/personal": {"refresh_token": "1//secret"', encoding="utf-8")
        with self.assertRaises(oauth.OAuthError) as ctx:
            self.store.load()
        self.assertNotIn("1//secret", str(ctx.exception))

    def test_an_unreadable_file_is_an_oauth_error(self):
        self.path.write_bytes(b"\xff\xfe not utf-8")
        with self.assertRaises(oauth.OAuthError) as ctx:
            self.store.load()
        self.assertEqual(ctx.exception.code, "store")

    def test_a_failed_write_is_an_oauth_error_and_leaves_the_old_file(self):
        from unittest import mock

        self.store.put("a/b", "old")
        with mock.patch.object(oauth.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(oauth.OAuthError) as ctx:
                self.store.put("a/b", "new")
        self.assertEqual(ctx.exception.code, "store")
        self.assertEqual(self.store.refresh_token("a/b"), "old")
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ["calendar-tokens.json"])

    def test_replace_is_a_compare_and_swap(self):
        self.store.put("m/w", "old")
        self.store.replace("m/w", "old", "new")
        self.assertEqual(self.store.refresh_token("m/w"), "new")
        self.store.delete("m/w")
        self.store.replace("m/w", "new", "newer")
        self.assertIsNone(self.store.refresh_token("m/w"), "a disconnect was undone")

    def test_the_permission_warning(self):
        self.assertIsNone(oauth.tokens_permission_warning(0o100600, "linux", "p"))
        self.assertIn("chmod 600", oauth.tokens_permission_warning(0o100644, "linux", "p"))
        self.assertIsNone(oauth.tokens_permission_warning(0o100644, "win32", "p"))


class CredentialsTests(TempStore):
    def test_microsoft_rotation_replaces_the_stored_token(self):
        self.store.put("microsoft/work", "old")
        post = Recorder(dict(MICROSOFT_GRANT, refresh_token="new"))
        creds = oauth.Credentials("microsoft/work", "microsoft", {"microsoft_client_id": "c"},
                                  self.store, post=post, clock=lambda: 1000.0)
        self.assertEqual(creds.access_token(), "at")
        self.assertEqual(self.store.refresh_token("microsoft/work"), "new")
        self.assertEqual(post.calls[0][1]["refresh_token"], "old")

    def test_a_disconnect_during_the_refresh_is_not_undone_by_the_rotation(self):
        self.store.put("microsoft/work", "old")

        def post(url, fields):
            # The owner runs --disconnect while this refresh is in flight.
            self.store.delete("microsoft/work")
            return dict(MICROSOFT_GRANT, refresh_token="new")

        creds = oauth.Credentials("microsoft/work", "microsoft", {"microsoft_client_id": "c"},
                                  self.store, post=post)
        creds.access_token()
        self.assertIsNone(self.store.refresh_token("microsoft/work"))

    def test_the_access_token_is_reused_until_near_expiry(self):
        self.store.put("google/personal", "rt")
        now = [1000.0]
        post = Recorder(GOOGLE_GRANT, dict(GOOGLE_GRANT, access_token="at2"))
        creds = oauth.Credentials("google/personal", "google", {}, self.store,
                                  post=post, clock=lambda: now[0])
        self.assertEqual(creds.access_token(), "at")
        now[0] += 3000
        self.assertEqual(creds.access_token(), "at")
        self.assertEqual(len(post.calls), 1)
        now[0] += 600
        self.assertEqual(creds.access_token(), "at2")

    def test_the_access_token_is_never_written(self):
        self.store.put("google/personal", "rt")
        creds = oauth.Credentials("google/personal", "google", {}, self.store,
                                  post=Recorder(GOOGLE_GRANT))
        creds.access_token()
        self.assertNotIn('"at"', self.path.read_text(encoding="utf-8"))

    def test_the_access_token_is_refreshed_inside_the_margin(self):
        self.store.put("google/personal", "rt")
        now = [1000.0]
        post = Recorder(GOOGLE_GRANT, dict(GOOGLE_GRANT, access_token="at2"))
        creds = oauth.Credentials("google/personal", "google", {}, self.store,
                                  post=post, clock=lambda: now[0])
        creds.access_token()
        now[0] = 1000 + 3599 - 30   # 30 s before expiry: inside a 60 s margin
        self.assertEqual(creds.access_token(), "at2")

    def test_a_refused_token_is_not_sent_again_until_it_changes(self):
        self.store.put("google/personal", "rt")
        post = Recorder({"error": "invalid_grant"}, GOOGLE_GRANT)
        creds = oauth.Credentials("google/personal", "google", {}, self.store, post=post)
        for _ in range(3):
            with self.assertRaises(oauth.OAuthError):
                creds.access_token()
        self.assertEqual(len(post.calls), 1)
        self.store.put("google/personal", "rt-new")   # calendar_login ran
        self.assertEqual(creds.access_token(), "at")
        self.assertEqual(len(post.calls), 2)

    def test_a_provider_outage_is_retried_next_cycle(self):
        self.store.put("google/personal", "rt")
        post = Recorder(oauth.OAuthError("network"), GOOGLE_GRANT)
        creds = oauth.Credentials("google/personal", "google", {}, self.store, post=post)
        with self.assertRaises(oauth.OAuthError):
            creds.access_token()
        self.assertEqual(creds.access_token(), "at")

    def test_not_connected_says_what_to_run(self):
        creds = oauth.Credentials("google/personal", "google", {}, self.store, post=Recorder())
        with self.assertRaises(oauth.OAuthError) as ctx:
            creds.access_token()
        self.assertIn("calendar_login.py google --account personal", str(ctx.exception))

    def test_a_refresh_that_widened_the_scope_is_refused(self):
        self.store.put("google/personal", "rt")
        post = Recorder(dict(GOOGLE_GRANT,
                             scope=oauth.GOOGLE_SCOPE + " https://www.googleapis.com/auth/calendar"))
        creds = oauth.Credentials("google/personal", "google", {}, self.store, post=post)
        with self.assertRaises(oauth.ScopeError):
            creds.access_token()
        self.assertIsNone(self.store.refresh_token("google/personal"),
                          "a token that now grants more than read-only was kept")


class NormaliseTests(unittest.TestCase):
    def test_google_drops_declined_cancelled_and_working_location(self):
        events = providers_calendar.normalise_google(GOOGLE, "google/personal")
        self.assertEqual(events, [
            {"start": "2026-09-22T09:30:00-03:00", "end": "2026-09-22T09:45:00-03:00",
             "allDay": False, "source": "google/personal", "title": "Standup"},
            {"start": "2026-09-22", "end": "2026-09-23", "allDay": True,
             "source": "google/personal", "title": "Feriado"},
        ])

    def test_graph_drops_declined_and_cancelled_and_reads_utc(self):
        events = providers_calendar.normalise_graph(GRAPH, "microsoft/work")
        self.assertEqual(events, [
            {"start": "2026-09-22T14:00:00+00:00", "end": "2026-09-22T14:30:00+00:00",
             "allDay": False, "source": "microsoft/work", "title": "1:1 with the manager"},
            {"start": "2026-09-23", "end": "2026-09-24", "allDay": True,
             "source": "microsoft/work", "title": "Offsite"},
        ])

    def test_graph_all_day_dates_survive_positive_offsets(self):
        # Midnight in Tokyo is 15:00Z the day before; the date must not move.
        raw = {"value": [{"subject": "x", "isAllDay": True, "isCancelled": False,
                          "start": {"dateTime": "2026-09-22T15:00:00.0000000", "timeZone": "UTC"},
                          "end": {"dateTime": "2026-09-23T15:00:00.0000000", "timeZone": "UTC"}}]}
        event = providers_calendar.normalise_graph(raw, "microsoft/x")[0]
        self.assertEqual((event["start"], event["end"]), ("2026-09-23", "2026-09-24"))

    def test_a_graph_zone_that_is_not_utc_fails_the_account_rather_than_guessing(self):
        raw = {"value": [{"subject": "x", "isAllDay": False,
                          "start": {"dateTime": "2026-09-22T10:00:00", "timeZone": "Pacific Standard Time"},
                          "end": {"dateTime": "2026-09-22T11:00:00", "timeZone": "Pacific Standard Time"}}]}
        with self.assertRaises(UpstreamError):
            providers_calendar.normalise_graph(raw, "microsoft/x")

    def test_other_spellings_of_utc_are_utc(self):
        for label in ("Etc/GMT", "Coordinated Universal Time", "tzone://Microsoft/Utc"):
            raw = {"value": [{"subject": "x", "isAllDay": False,
                              "start": {"dateTime": "2026-09-22T10:00:00", "timeZone": label},
                              "end": {"dateTime": "2026-09-22T11:00:00", "timeZone": label}}]}
            with self.subTest(label=label):
                self.assertEqual(providers_calendar.normalise_graph(raw, "m/x")[0]["start"],
                                 "2026-09-22T10:00:00+00:00")

    def test_garbage_is_empty_not_an_exception(self):
        for raw in (None, [], {"items": "x"}, {"items": [None, 3, {"start": "x"}]}):
            with self.subTest(raw=raw):
                self.assertEqual(providers_calendar.normalise_google(raw, "g/x"), [])
                self.assertEqual(providers_calendar.normalise_graph(raw, "m/x"), [])

    def test_titles_are_trimmed_and_stripped_of_control_characters(self):
        raw = {"items": [{"summary": "a\x1b[31m\nb " + "x" * 200,
                          "start": {"dateTime": "2026-09-22T10:00:00Z"},
                          "end": {"dateTime": "2026-09-22T11:00:00Z"}}]}
        title = providers_calendar.normalise_google(raw, "g/x")[0]["title"]
        self.assertTrue(title.startswith("a [31m b "))
        self.assertLessEqual(len(title), providers_calendar.MAX_TITLE)
        self.assertNotRegex(title, r"[\x00-\x1f]")

    def test_a_long_title_is_cut_with_an_ellipsis(self):
        raw = {"items": [{"summary": "x" * 200, "start": {"dateTime": "2026-09-22T10:00:00Z"},
                          "end": {"dateTime": "2026-09-22T11:00:00Z"}}]}
        self.assertEqual(providers_calendar.normalise_google(raw, "g/x")[0]["title"],
                         "x" * (providers_calendar.MAX_TITLE - 1) + "…")

    def test_bidi_and_zero_width_characters_are_stripped(self):
        # A title is text from whoever sent the invitation (ADR 0017).
        raw = {"items": [{"summary": "pay\u202egnp.exe\u200b\u2066x\x85",
                          "start": {"dateTime": "2026-09-22T10:00:00Z"},
                          "end": {"dateTime": "2026-09-22T11:00:00Z"}}]}
        self.assertEqual(providers_calendar.normalise_google(raw, "g/x")[0]["title"],
                         "pay gnp.exe x")

    def test_graph_all_day_dates_survive_utc_plus_12(self):
        raw = {"value": [{"subject": "x", "isAllDay": True, "isCancelled": False,
                          "start": {"dateTime": "2026-06-22T12:00:00.0000000", "timeZone": "UTC"},
                          "end": {"dateTime": "2026-06-23T12:00:00.0000000", "timeZone": "UTC"}}]}
        event = providers_calendar.normalise_graph(raw, "microsoft/x")[0]
        self.assertEqual((event["start"], event["end"]), ("2026-06-23", "2026-06-24"))

    def test_an_event_without_a_title_has_no_title_key(self):
        raw = {"items": [{"start": {"dateTime": "2026-09-22T10:00:00Z"},
                          "end": {"dateTime": "2026-09-22T11:00:00Z"}}]}
        self.assertNotIn("title", providers_calendar.normalise_google(raw, "g/x")[0])


class SelectAndLoadTests(unittest.TestCase):
    def _timed(self, hour, source="g/x"):
        return {"start": f"2026-09-22T{hour:02d}:00:00+00:00",
                "end": f"2026-09-22T{hour:02d}:30:00+00:00", "allDay": False,
                "source": source, "title": f"t{hour}"}

    def _all_day(self, day):
        return {"start": f"2026-09-{day}", "end": f"2026-09-{day + 1}", "allDay": True,
                "source": "g/x", "title": f"d{day}"}

    def test_all_day_events_cannot_push_out_the_meetings(self):
        events = [self._all_day(22), self._all_day(23), self._all_day(24)] + \
                 [self._timed(h) for h in (15, 10, 12, 18)]
        chosen = providers_calendar.select(events, show_titles=True)
        self.assertEqual([e["title"] for e in chosen], ["d22", "t10", "t12", "t15", "d23"])

    def test_titles_off_removes_every_title_on_the_server(self):
        chosen = providers_calendar.select([self._timed(10), self._all_day(22)], show_titles=False)
        self.assertTrue(chosen)
        self.assertFalse(any("title" in e for e in chosen))

    def test_the_order_is_deterministic_for_a_tie(self):
        a, b = self._timed(10, "microsoft/w"), self._timed(10, "google/p")
        self.assertEqual(providers_calendar.select([a, b], True),
                         providers_calendar.select([b, a], True))

    def test_one_account_failing_costs_only_its_own_events(self):
        class Creds:
            def __init__(self, fail=None):
                self.fail = fail

            def access_token(self):
                if self.fail:
                    raise self.fail
                return "at"

        logged = []
        result = providers_calendar.load(
            [("google", "personal"), ("microsoft", "work"), ("microsoft", "home"),
             ("google", "broken")],
            {"google/personal": Creds(),
             "microsoft/work": Creds(oauth.OAuthError("invalid_grant", "microsoft refresh: invalid_grant")),
             "microsoft/home": Creds(),
             "google/broken": Creds(PermissionError("locked"))},
            NOW, 24, True,
            google=lambda *a, **k: GOOGLE,
            graph=lambda *a: (_ for _ in ()).throw(UpstreamError("HTTP 503 from graph")),
            log=logged.append)
        self.assertEqual(result["accounts"], 4)
        self.assertEqual(result["failed"], [
            {"source": "microsoft/work", "reason": "reconnect"},
            {"source": "microsoft/home", "reason": "unavailable"},
            {"source": "google/broken", "reason": "unavailable"},
        ])
        self.assertEqual({e["source"] for e in result["events"]}, {"google/personal"})
        self.assertEqual(len(logged), 3)
        self.assertNotIn("locked", logged[2])
        self.assertIn("microsoft/work", logged[0])
        self.assertFalse(any("Standup" in line for line in logged))

    def test_the_requests_ask_for_the_window_and_only_the_fields_read(self):
        seen = []

        def get(url, headers=None):
            seen.append((url, headers))
            return {}

        providers_calendar.fetch_google("tok", NOW, NOW + datetime.timedelta(hours=24), get=get)
        providers_calendar.fetch_graph("tok", NOW, NOW + datetime.timedelta(hours=24), get=get)
        # The calendar list first; it answered nothing, so the primary alone.
        listing, google, graph = seen
        self.assertTrue(listing[0].startswith(
            "https://www.googleapis.com/calendar/v3/users/me/calendarList?"))
        gq = urllib.parse.parse_qs(urllib.parse.urlsplit(google[0]).query)
        self.assertEqual(gq["eventTypes"], ["default", "fromGmail"])
        self.assertIn("nextPageToken", gq["fields"][0])
        self.assertTrue(google[0].startswith(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events?"))
        self.assertEqual(gq["timeMin"], ["2026-09-22T09:00:00Z"])
        self.assertEqual(gq["singleEvents"], ["true"])
        self.assertNotIn("description", gq["fields"][0])
        self.assertEqual(google[1], {"Authorization": "Bearer tok"})
        mq = urllib.parse.parse_qs(urllib.parse.urlsplit(graph[0]).query)
        self.assertTrue(graph[0].startswith("https://graph.microsoft.com/v1.0/me/calendar/calendarView?"))
        self.assertEqual(mq["endDateTime"], ["2026-09-23T09:00:00Z"])
        self.assertNotIn("body", mq["$select"][0])
        self.assertEqual(graph[1]["Prefer"], 'outlook.timezone="UTC"')


class PagingTests(unittest.TestCase):
    def test_google_follows_next_page_token_and_stops(self):
        pages = [{"items": [], "nextPageToken": "p2"}, {"items": [{"x": 1}], "nextPageToken": "p3"},
                 {"items": [{"x": 2}]}, {"items": [{"x": "never"}]}]
        urls = []

        def get(url, headers=None):
            urls.append(url)
            return pages[len(urls) - 1]

        raw = providers_calendar.fetch_google_events("t", "primary", NOW, NOW, get=get)
        self.assertEqual(raw, {"items": [{"x": 1}, {"x": 2}]})
        self.assertIn("pageToken=p3", urls[2])

    def test_google_follows_the_calendar_list_s_page_token_too(self):
        pages = [{"items": [{"id": "a", "selected": True}], "nextPageToken": "p2"},
                 {"items": [{"id": "b", "selected": True}]}]
        urls = []

        def get(url, headers=None):
            urls.append(url)
            return pages[len(urls) - 1]

        self.assertEqual(providers_calendar.fetch_google_calendars("t", get=get),
                         ["primary", "a", "b"])
        self.assertIn("pageToken=p2", urls[1])

    def test_graph_follows_next_link_only_to_graph(self):
        pages = [{"value": [{"a": 1}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"},
                 {"value": [{"a": 2}], "@odata.nextLink": "https://evil.example/steal"}]
        urls = []

        def get(url, headers=None):
            urls.append(url)
            return pages[len(urls) - 1]

        raw = providers_calendar.fetch_graph("t", NOW, NOW, get=get)
        self.assertEqual(raw, {"value": [{"a": 1}, {"a": 2}]})
        self.assertEqual(len(urls), 2, "a nextLink off Graph would carry the bearer token")


class ConfigTests(unittest.TestCase):
    def test_the_calendar_keys_are_type_checked(self):
        for key, bad in (("calendar_show_titles", "false"), ("calendar_show_titles", 0),
                         ("calendar_interval_s", "300"), ("calendar_interval_s", 0),
                         ("calendar_interval_s", True), ("calendar_lookahead_h", "24"),
                         ("calendar_lookahead_h", 0), ("allowed_hosts", "mypc.local"),
                         ("allowed_hosts", [""])):
            with self.subTest(key=key, bad=bad):
                with self.assertRaises(ValueError):
                    providers_calendar.check_config({key: bad})
        providers_calendar.check_config({})

    def test_a_quoted_false_never_reaches_the_payload_as_true(self):
        with self.assertRaises(ValueError):
            App({"calendar_show_titles": "false"})

    def test_accounts_are_validated(self):
        self.assertEqual(providers_calendar.accounts_from_config(
            [{"provider": "google", "name": "personal"}]), [("google", "personal")])
        for bad in ("x", [{"provider": "yahoo", "name": "a"}],
                    [{"provider": "google", "name": "Has Space"}],
                    [{"provider": "google", "name": "a"}, {"provider": "google", "name": "a"}],
                    ["google"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    providers_calendar.accounts_from_config(bad)

    def test_a_provider_in_use_needs_its_client_keys(self):
        accounts = [("google", "a"), ("microsoft", "b")]
        self.assertEqual(providers_calendar.missing_client_ids(accounts, {}),
                         ["google_client_id", "google_client_secret", "microsoft_client_id"])
        self.assertEqual(providers_calendar.missing_client_ids(
            accounts, {"google_client_id": None, "google_client_secret": "s",
                       "microsoft_client_id": "m"}), ["google_client_id"])
        self.assertEqual(providers_calendar.missing_client_ids(
            accounts, {"google_client_id": "g", "google_client_secret": "s",
                       "microsoft_client_id": "m"}), [])

    def test_a_name_with_a_trailing_newline_is_refused(self):
        with self.assertRaises(ValueError):
            providers_calendar.accounts_from_config([{"provider": "google", "name": "work\n"}])

    def test_a_bad_account_fails_at_construction(self):
        with self.assertRaises(ValueError):
            App({"calendar_accounts": [{"provider": "nope", "name": "a"}]})

    def test_no_accounts_is_an_empty_agenda_and_no_thread(self):
        app = App({})
        self.assertEqual(app.agenda(), {"accounts": 0, "events": [], "failed": []})
        self.assertFalse(app._agenda_refreshing)


class HostAllowlistTests(unittest.TestCase):
    """DNS rebinding (ADR 0017)."""

    def test_what_the_panel_and_the_tools_send_is_allowed(self):
        for host in ("192.168.1.100:8777", "192.168.1.100", "127.0.0.1:8777", "localhost:8777",
                     "[fe80::1]:8777", "[::1]", "LOCALHOST", None):
            with self.subTest(host=host):
                self.assertTrue(host_allowed(host))

    def test_a_name_is_refused_unless_listed(self):
        for host in ("evil.example:8777", "evil.example", "192.168.1.100.evil.example", "", ":8777"):
            with self.subTest(host=host):
                self.assertFalse(host_allowed(host))
        self.assertTrue(host_allowed("MyPC.local:8777", ["mypc.local"]))

    def test_route_answers_421_before_any_route_runs(self):
        status, body, _, _ = route("GET", "/quotes", App({}), {"Host": "evil.example:8777"})
        self.assertEqual(status, 421)
        self.assertEqual(json.loads(body), {"error": "unknown host"})
        status, _, _, _ = route("GET", "/ping", None, {"Host": "192.168.1.100:8777"})
        self.assertEqual(status, 200)


class GoogleLoopbackTests(unittest.TestCase):
    """The loopback listener, against a real socket on 127.0.0.1."""

    def _login(self, tamper=None):
        import contextlib
        import io
        import threading
        import urllib.request
        from unittest import mock

        from server import calendar_login

        exchanged = {}

        def fake_browser(url):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            redirect = query["redirect_uri"][0]
            self.assertTrue(redirect.startswith("http://127.0.0.1:"))
            params = {"state": query["state"][0], "code": "the-code"}
            if tamper:
                params = tamper(params)

            def hit():
                forged = "/?" + urllib.parse.urlencode({"state": "forged", "code": "evil"})
                for path in ("/favicon.ico", forged, "/?" + urllib.parse.urlencode(params)):
                    try:
                        urllib.request.urlopen(redirect + path, timeout=5).read()
                    except Exception:  # noqa: BLE001 - 404 and 400 are expected here
                        pass

            threading.Thread(target=hit, daemon=True).start()
            return True

        def fake_exchange(client_id, secret, code, verifier, redirect_uri):
            exchanged.update(code=code, verifier=verifier)
            return dict(GOOGLE_GRANT)

        with mock.patch.object(calendar_login, "LOGIN_TIMEOUT_S", 15), \
                mock.patch.object(calendar_login.webbrowser, "open", fake_browser), \
                mock.patch.object(calendar_login.oauth, "google_exchange_code", fake_exchange), \
                contextlib.redirect_stdout(io.StringIO()):
            grant = calendar_login.google_login({"google_client_id": "cid"})
        return grant, exchanged

    def test_the_redirect_is_exchanged_with_the_verifier(self):
        grant, exchanged = self._login()
        self.assertEqual(grant["refresh_token"], "rt-google")
        self.assertEqual(exchanged["code"], "the-code")
        self.assertEqual(len(exchanged["verifier"]), 43)

    def test_a_forged_state_neither_wins_nor_ends_the_wait(self):
        # Every run of `_login` sends a forged redirect before the real one.
        # It is answered 404, and the real one is exchanged afterwards.
        grant, exchanged = self._login()
        self.assertEqual(exchanged["code"], "the-code")

    def test_a_non_ascii_state_is_a_404_not_a_crash(self):
        grant, _ = self._login(lambda p: p)  # the forged one above is ASCII
        import urllib.request
        from server import calendar_login

        server = calendar_login._LoopbackServer("expected")
        self.addCleanup(server.server_close)
        import threading
        threading.Thread(target=server.handle_request, daemon=True).start()
        port = server.server_address[1]
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/?state=%C3%A9", timeout=5)
        self.assertEqual(ctx.exception.code, 404)
        self.assertIsNone(server.result)

    def test_a_silent_connection_does_not_block_the_listener_for_ever(self):
        import socket
        import threading
        from server import calendar_login

        server = calendar_login._LoopbackServer("s")
        self.addCleanup(server.server_close)
        done = threading.Event()

        def serve():
            server.handle_request()
            done.set()

        with unittest.mock.patch.object(calendar_login._Redirect, "timeout", 0.5):
            threading.Thread(target=serve, daemon=True).start()
            silent = socket.create_connection(server.server_address)
            self.addCleanup(silent.close)
            self.assertTrue(done.wait(5), "handle_request is still blocked on a silent socket")

    def test_a_refused_consent_is_an_error(self):
        with self.assertRaises(oauth.OAuthError) as ctx:
            self._login(lambda p: {"state": p["state"], "error": "access_denied"})
        self.assertEqual(ctx.exception.code, "access_denied")


class ReadOnlyGuardTests(unittest.TestCase):
    """The build fails if the server could ever ask for, or do, a write (ADR 0017).

    An allowlist, not a denylist: every Google scope URL and every Graph
    permission named anywhere in `server/*.py` must be one of the read-only
    ones. A denylist of write scopes was the first version, and it missed
    `calendar.events.owned`, `calendar.app.created` and `calendar.acls`.
    """

    # Every one "read" in Google's own words (developers.google.com/workspace/
    # calendar/api/auth): "View events on all your calendars", "See the list
    # of Google calendars you're subscribed to", "See the events on Google
    # calendars you own" (ADR 0019).
    GOOGLE_READ_ONLY = {"https://www.googleapis.com/auth/calendar.events.readonly",
                        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
                        "https://www.googleapis.com/auth/calendar.events.owned.readonly",
                        "https://www.googleapis.com/auth/userinfo.email",
                        "https://www.googleapis.com/auth/userinfo.profile"}
    GRAPH_READ_ONLY = {"Calendars.ReadBasic", "User.Read"}
    CALENDAR_MODULES = ("oauth.py", "providers_calendar.py", "calendar_login.py")

    def _sources(self):
        for path in sorted(SERVER_DIR.glob("*.py")):
            yield path.name, path.read_text(encoding="utf-8")

    def test_the_modules_it_guards_exist(self):
        for name in self.CALENDAR_MODULES:
            self.assertTrue((SERVER_DIR / name).is_file(), f"{name} moved; point the guard at it")

    def test_every_scope_named_in_the_server_is_read_only(self):
        google = re.compile(r"https://www\.googleapis\.com/auth/[A-Za-z0-9._/-]+")
        graph = re.compile(r"\b(?:Calendars|Mail|Contacts|Files|User|Directory|Sites|Tasks|Notes|People)"
                           r"\.[A-Za-z]+(?:\.[A-Za-z]+)*\b")
        for name, source in self._sources():
            with self.subTest(file=name):
                for scope in google.findall(source):
                    self.assertIn(scope, self.GOOGLE_READ_ONLY, f"{name} names {scope}")
                for scope in graph.findall(source):
                    self.assertIn(scope, self.GRAPH_READ_ONLY, f"{name} names {scope}")

    def test_the_guard_would_catch_a_write_scope(self):
        # The write twin of each read-only scope in the allowlist, and the
        # all-access one.
        for google in ("https://www.googleapis.com/auth/calendar.events.owned",
                       "https://www.googleapis.com/auth/calendar.events",
                       "https://www.googleapis.com/auth/calendar.calendarlist",
                       "https://www.googleapis.com/auth/calendar"):
            self.assertNotIn(google, self.GOOGLE_READ_ONLY)
            # And the code, not only this test's own set: the runtime check
            # would refuse it, and nothing asks for it.
            self.assertNotIn(google, oauth.ALLOWED_SCOPES["google"])
            self.assertNotIn(google, oauth.REQUESTED_SCOPES["google"].split())
        for scope in oauth.REQUESTED_SCOPES["google"].split():
            self.assertIn(scope, self.GOOGLE_READ_ONLY)
        self.assertNotIn("Calendars.ReadWrite", self.GRAPH_READ_ONLY)

    def test_the_calendar_calls_are_gets(self):
        source = (SERVER_DIR / "providers_calendar.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"method\s*=\s*['\"](?!GET)")
        self.assertNotIn("post_form", source)
        self.assertNotIn("urlopen", source)

    def test_the_only_scopes_requested_are_the_read_only_ones(self):
        self.assertEqual(oauth.GOOGLE_SCOPE,
                         "https://www.googleapis.com/auth/calendar.events.readonly "
                         "https://www.googleapis.com/auth/calendar.calendarlist.readonly")
        self.assertEqual(oauth.MICROSOFT_SCOPE, "Calendars.ReadBasic offline_access")


class OtherCalendarsTests(unittest.TestCase):
    """ADR 0019: every calendar the owner shows in Google Calendar, not only
    the primary -- shared and subscribed ones included."""

    LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"

    def _get(self, listing, events, fail=()):
        """A fake `get`: `listing` answers the calendar list, `events` maps a
        calendar id to its items, and an id in `fail` raises its message."""
        calls = []

        def get(url, headers=None):
            calls.append(url)
            if url.startswith(self.LIST_URL):
                return {"items": listing}
            calendar = urllib.parse.unquote(url.split("/calendars/", 1)[1].split("/events", 1)[0])
            if calendar in fail:
                raise UpstreamError(fail[calendar])
            return {"items": events.get(calendar, [])}
        return get, calls

    def test_the_shown_calendars_are_read_and_the_unticked_are_not(self):
        listing = [{"id": "me@example.com", "primary": True, "selected": True},
                   {"id": "family@group.calendar.google.com", "selected": True},
                   {"id": "pt.brazilian#holiday@group.v.calendar.google.com", "selected": True},
                   {"id": "unticked@group.calendar.google.com", "selected": False},
                   # Only a real true: a string is not the checkbox.
                   {"id": "stringy@group.calendar.google.com", "selected": "false"},
                   {"id": "no-flag@group.calendar.google.com"}]
        ids = providers_calendar.fetch_google_calendars("t", get=self._get(listing, {})[0])
        self.assertEqual(ids, ["primary", "family@group.calendar.google.com",
                               "pt.brazilian#holiday@group.v.calendar.google.com"])

    def test_the_primary_is_read_even_when_the_list_says_nothing(self):
        self.assertEqual(providers_calendar.fetch_google_calendars("t", get=lambda *a, **k: {}),
                         ["primary"])

    def test_no_more_than_max_calendars(self):
        listing = [{"id": f"c{i}", "selected": True} for i in range(30)]
        ids = providers_calendar.fetch_google_calendars("t", get=self._get(listing, {})[0])
        self.assertEqual(len(ids), providers_calendar.MAX_CALENDARS)
        self.assertEqual(ids[0], "primary")

    def test_events_from_every_calendar_are_merged_and_the_id_is_quoted(self):
        listing = [{"id": "pt.brazilian#holiday@group.v.calendar.google.com", "selected": True}]
        events = {"primary": [{"summary": "mine", "iCalUID": "1"}],
                  "pt.brazilian#holiday@group.v.calendar.google.com": [{"summary": "feriado"}]}
        get, calls = self._get(listing, events)
        raw = providers_calendar.fetch_google("t", NOW, NOW, get=get)
        self.assertEqual([i["summary"] for i in raw["items"]], ["mine", "feriado"])
        # '#' and '@' encoded: an unquoted '#' would end the path.
        self.assertIn("/calendars/pt.brazilian%23holiday%40group.v.calendar.google.com/events?",
                      calls[-1])

    def test_an_event_on_two_calendars_is_kept_once(self):
        listing = [{"id": "team", "selected": True}]
        same = {"summary": "Standup", "iCalUID": "u1", "start": {"dateTime": "2026-09-22T10:00:00Z"}}
        other_day = dict(same, start={"dateTime": "2026-09-23T10:00:00Z"})
        raw = providers_calendar.fetch_google(
            "t", NOW, NOW, get=self._get(listing, {"primary": [same], "team": [same, other_day]})[0])
        # The same instance once; the recurring one's next day is a different event.
        self.assertEqual(len(raw["items"]), 2)

    def test_a_shared_calendar_that_fails_is_skipped_and_named_nowhere(self):
        listing = [{"id": "friend@example.com", "selected": True},
                   {"id": "team", "selected": True}]
        logged = []
        get, _ = self._get(listing, {"primary": [{"summary": "a"}], "team": [{"summary": "b"}]},
                           fail={"friend@example.com": "HTTP 404 from https://...friend@example.com"})
        raw = providers_calendar.fetch_google("t", NOW, NOW, get=get, log=logged.append)
        self.assertEqual([i["summary"] for i in raw["items"]], ["a", "b"])
        self.assertEqual(len(logged), 1)
        self.assertNotIn("friend", logged[0])

    def test_the_primary_failing_fails_the_account(self):
        get, _ = self._get([], {}, fail={"primary": "HTTP 500 from google"})
        with self.assertRaises(UpstreamError):
            providers_calendar.fetch_google("t", NOW, NOW, get=get, log=lambda line: None)

    def test_a_401_on_any_calendar_is_the_token_and_fails_the_account(self):
        get, _ = self._get([{"id": "team", "selected": True}], {"primary": []},
                           fail={"team": "HTTP 401 from google"})
        with self.assertRaises(UpstreamError):
            providers_calendar.fetch_google("t", NOW, NOW, get=get, log=lambda line: None)


class OtherCalendarsReviewTests(unittest.TestCase):
    """What PR #64's review found, each pinned."""

    get_for = OtherCalendarsTests._get
    LIST_URL = OtherCalendarsTests.LIST_URL

    def test_the_same_instant_in_two_zones_is_one_event(self):
        # events.list writes each calendar's times in its own zone.
        listing = [{"id": "lisbon", "selected": True}]
        here = {"summary": "Standup", "iCalUID": "u1",
                "start": {"dateTime": "2026-09-22T07:00:00-03:00"}}
        there = dict(here, start={"dateTime": "2026-09-22T11:00:00+01:00"})
        raw = providers_calendar.fetch_google(
            "t", NOW, NOW, get=self.get_for(listing, {"primary": [here], "lisbon": [there]})[0])
        self.assertEqual(len(raw["items"]), 1)

    def test_a_copy_declined_on_the_primary_hides_the_other_copies(self):
        listing = [{"id": "colleague", "selected": True}]
        declined = {"summary": "Standup", "iCalUID": "u1",
                    "start": {"dateTime": "2026-09-22T07:00:00-03:00"},
                    "end": {"dateTime": "2026-09-22T07:30:00-03:00"},
                    "attendees": [{"self": True, "responseStatus": "declined"}]}
        theirs = dict(declined, start={"dateTime": "2026-09-22T11:00:00+01:00"},
                      end={"dateTime": "2026-09-22T11:30:00+01:00"},
                      attendees=[{"self": True, "responseStatus": "accepted"}])
        raw = providers_calendar.fetch_google(
            "t", NOW, NOW, get=self.get_for(listing, {"primary": [declined],
                                                      "colleague": [theirs]})[0])
        self.assertEqual(providers_calendar.normalise_google(raw, "google/me"), [])

    def test_a_401_on_a_shared_calendar_never_names_it(self):
        get, _ = self.get_for([{"id": "friend@example.com", "selected": True}], {"primary": []},
                              fail={"friend@example.com":
                                    "HTTP 401 from https://.../calendars/friend%40example.com/events"})
        with self.assertRaises(UpstreamError) as caught:
            providers_calendar.fetch_google("t", NOW, NOW, get=get, log=lambda line: None)
        self.assertNotIn("friend", str(caught.exception))
        self.assertIn(" 401 ", f" {caught.exception} ")

    def test_the_list_failing_still_reads_the_primary(self):
        logged = []

        def get(url, headers=None):
            if url.startswith(self.LIST_URL):
                raise UpstreamError("HTTP 503 from google")
            return {"items": [{"summary": "mine"}]}

        raw = providers_calendar.fetch_google("t", NOW, NOW, get=get, log=logged.append)
        self.assertEqual([i["summary"] for i in raw["items"]], ["mine"])
        self.assertEqual(len(logged), 1)

    def test_the_list_answering_401_fails_the_account(self):
        def get(url, headers=None):
            raise UpstreamError("HTTP 401 from google")

        with self.assertRaises(UpstreamError):
            providers_calendar.fetch_google("t", NOW, NOW, get=get, log=lambda line: None)

    def test_past_the_budget_the_rest_are_left_unread_and_counted(self):
        listing = [{"id": f"c{i}", "selected": True} for i in range(3)]
        # The deadline, then one tick per calendar after the primary.
        ticks = iter([0, 0, 100, 100])
        logged = []
        get, calls = self.get_for(listing, {"primary": [{"summary": "mine"}],
                                            "c0": [{"summary": "first"}]})
        raw = providers_calendar.fetch_google("t", NOW, NOW, get=get, log=logged.append,
                                              clock=lambda: next(ticks), budget_s=60)
        self.assertEqual([i["summary"] for i in raw["items"]], ["mine", "first"])
        self.assertTrue(any("2 calendars left unread" in line for line in logged))

    def test_the_cap_says_so(self):
        listing = [{"id": f"c{i}", "selected": True} for i in range(30)]
        logged = []
        providers_calendar.fetch_google_calendars("t", get=self.get_for(listing, {})[0],
                                                  log=logged.append)
        self.assertEqual(len(logged), 1)
        self.assertIn(str(providers_calendar.MAX_CALENDARS), logged[0])

    def test_load_hands_its_log_to_the_fetch(self):
        seen = {}

        def google(token, time_min, time_max, log=None):
            seen["log"] = log
            return {"items": []}

        def log(line):
            pass

        class Creds:
            def access_token(self):
                return "at"

        providers_calendar.load([("google", "me")], {"google/me": Creds()}, NOW, 24, True,
                                google=google, log=log)
        self.assertIs(seen["log"], log)

    def test_a_403_insufficient_permissions_asks_for_a_reconnect(self):
        class Creds:
            def access_token(self):
                return "at"

        def google(*a, **k):
            raise UpstreamError('HTTP 403 from google: {"reason": "insufficientPermissions"}')

        result = providers_calendar.load([("google", "me")], {"google/me": Creds()}, NOW, 24,
                                         True, google=google, log=lambda line: None)
        self.assertEqual(result["failed"], [{"source": "google/me", "reason": "reconnect"}])


if __name__ == "__main__":
    unittest.main()
