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

    def test_a_broad_google_grant_is_not_kept_at_login(self):
        post = Recorder(dict(GOOGLE_GRANT, scope="https://www.googleapis.com/auth/calendar"))
        with self.assertRaises(oauth.ScopeError):
            oauth.google_exchange_code("cid", "sec", "code", "ver", "http://127.0.0.1:1", post=post)


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

    def test_a_graph_zone_that_is_not_utc_is_skipped_rather_than_guessed(self):
        raw = {"value": [{"subject": "x", "isAllDay": False,
                          "start": {"dateTime": "2026-09-22T10:00:00", "timeZone": "Pacific Standard Time"},
                          "end": {"dateTime": "2026-09-22T11:00:00", "timeZone": "Pacific Standard Time"}}]}
        self.assertEqual(providers_calendar.normalise_graph(raw, "microsoft/x"), [])

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
            [("google", "personal"), ("microsoft", "work"), ("microsoft", "home")],
            {"google/personal": Creds(),
             "microsoft/work": Creds(oauth.OAuthError("invalid_grant", "microsoft refresh: invalid_grant")),
             "microsoft/home": Creds()},
            NOW, 24, True,
            google=lambda *a: GOOGLE,
            graph=lambda *a: (_ for _ in ()).throw(UpstreamError("HTTP 503 from graph")),
            log=logged.append)
        self.assertEqual(result["accounts"], 3)
        self.assertEqual(result["failed"], ["microsoft/work", "microsoft/home"])
        self.assertEqual({e["source"] for e in result["events"]}, {"google/personal"})
        self.assertEqual(len(logged), 2)
        self.assertIn("microsoft/work", logged[0])
        self.assertFalse(any("Standup" in line for line in logged))

    def test_the_requests_ask_for_the_window_and_only_the_fields_read(self):
        seen = []

        def get(url, headers=None):
            seen.append((url, headers))
            return {}

        providers_calendar.fetch_google("tok", NOW, NOW + datetime.timedelta(hours=24), get=get)
        providers_calendar.fetch_graph("tok", NOW, NOW + datetime.timedelta(hours=24), get=get)
        google, graph = seen
        gq = urllib.parse.parse_qs(urllib.parse.urlsplit(google[0]).query)
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


class ConfigTests(unittest.TestCase):
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

    def test_a_provider_in_use_needs_its_client_id(self):
        accounts = [("google", "a"), ("microsoft", "b")]
        self.assertEqual(providers_calendar.missing_client_ids(accounts, {}),
                         ["google_client_id", "microsoft_client_id"])
        self.assertEqual(providers_calendar.missing_client_ids(
            accounts, {"google_client_id": "g", "microsoft_client_id": "m"}), [])

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
                for path in ("/favicon.ico", "/?" + urllib.parse.urlencode(params)):
                    try:
                        urllib.request.urlopen(redirect + path, timeout=5).read()
                    except Exception:  # noqa: BLE001 - 404 and 400 are expected here
                        pass

            threading.Thread(target=hit, daemon=True).start()
            return True

        def fake_exchange(client_id, secret, code, verifier, redirect_uri):
            exchanged.update(code=code, verifier=verifier)
            return dict(GOOGLE_GRANT)

        with mock.patch.object(calendar_login.webbrowser, "open", fake_browser), \
                mock.patch.object(calendar_login.oauth, "google_exchange_code", fake_exchange), \
                contextlib.redirect_stdout(io.StringIO()):
            grant = calendar_login.google_login({"google_client_id": "cid"})
        return grant, exchanged

    def test_the_redirect_is_exchanged_with_the_verifier(self):
        grant, exchanged = self._login()
        self.assertEqual(grant["refresh_token"], "rt-google")
        self.assertEqual(exchanged["code"], "the-code")
        self.assertEqual(len(exchanged["verifier"]), 43)

    def test_a_forged_state_stores_nothing(self):
        with self.assertRaises(oauth.OAuthError) as ctx:
            self._login(lambda p: dict(p, state="forged"))
        self.assertEqual(ctx.exception.code, "state")

    def test_a_refused_consent_is_an_error(self):
        with self.assertRaises(oauth.OAuthError) as ctx:
            self._login(lambda p: {"state": p["state"], "error": "access_denied"})
        self.assertEqual(ctx.exception.code, "access_denied")


class ReadOnlyGuardTests(unittest.TestCase):
    """The build fails if the server could ever ask for, or do, a write (ADR 0017)."""

    FILES = ("oauth.py", "providers_calendar.py", "calendar_login.py")

    def _sources(self):
        for name in self.FILES:
            path = SERVER_DIR / name
            if path.exists():
                yield name, path.read_text(encoding="utf-8")

    def test_no_write_scope_is_named(self):
        # `auth/calendar` or `auth/calendar.events` with nothing after them is
        # full or read-write access; every read-only scope continues with a dot.
        write = re.compile(r"auth/calendar(\.events)?(?![.\w])|ReadWrite|Read\.Shared|Mail\.")
        for name, source in self._sources():
            with self.subTest(file=name):
                self.assertIsNone(write.search(source), f"{name} names a write or broad scope")

    def test_the_calendar_calls_are_gets(self):
        source = (SERVER_DIR / "providers_calendar.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"method\s*=\s*['\"](?!GET)")
        self.assertNotIn("post_form", source)
        self.assertNotIn("urlopen", source)

    def test_the_only_scopes_requested_are_the_read_only_ones(self):
        self.assertEqual(oauth.GOOGLE_SCOPE,
                         "https://www.googleapis.com/auth/calendar.events.owned.readonly")
        self.assertEqual(oauth.MICROSOFT_SCOPE, "Calendars.ReadBasic offline_access")


if __name__ == "__main__":
    unittest.main()
