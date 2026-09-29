"""T9.1 -- the two calendar APIs, asked for their shape with the owner's own grant.

Opt-in twice, unlike `contract_upstream.py`. It needs RUN_CONTRACT_TESTS, like
every contract file, **and** a connected account: the config the server would
load names the accounts, and `calendar-tokens.json` beside it holds their
refresh tokens. An account that is not connected is skipped, not failed, so
`make contract` stays green on a clone with no calendar.

    RUN_CONTRACT_TESTS=1 python -m unittest discover -s server/tests -t . \\
        -p "contract_calendar*.py"

What is asserted is what `normalise_google` and `normalise_graph` read, and
that the grant is still the read-only one (ADR 0017). **Nothing is printed
from an event**, not even on failure: a title is personal data, and a test log
is the kind of file that gets pasted into an issue.
"""
import datetime
import os
import unittest

from server import oauth, providers_calendar
from server.server import SCRIPT_DIR, config_search_paths, load_config, tokens_path_for
from server.tests.contract_upstream import LIVE, ContractCase


def _connected():
    """`[(provider, name, Credentials)]` for every account with a stored token."""
    config_path = config_search_paths([], os.environ, SCRIPT_DIR, exists=os.path.exists)[0]
    try:
        config = load_config(config_path)
    except Exception:  # noqa: BLE001 - no config is simply nothing to test
        return []
    store = oauth.TokenStore(tokens_path_for(config_path))
    found = []
    for provider, name in providers_calendar.accounts_from_config(config.get("calendar_accounts")):
        account = f"{provider}/{name}"
        if store.refresh_token(account):
            found.append((provider, name,
                          oauth.Credentials(account, provider, config, store)))
    return found


@LIVE
class CalendarContract(ContractCase):
    def setUp(self):
        self.accounts = _connected()
        if not self.accounts:
            self.skipTest("no calendar account is connected; run server/calendar_login.py")
        self.now = datetime.datetime.now(datetime.timezone.utc)
        self.until = self.now + datetime.timedelta(days=7)

    def test_each_account_answers_in_the_shape_the_normaliser_reads(self):
        for provider, name, creds in self.accounts:
            with self.subTest(account=f"{provider}/{name}"):
                token = creds.access_token()  # also re-checks the scope
                if provider == "google":
                    raw = providers_calendar.fetch_google(token, self.now, self.until)
                    self.assertIsInstance(raw.get("items"), list,
                                          "events.list has no `items` list; re-record "
                                          "fixtures/google_events.json")
                    rows = providers_calendar.normalise_google(raw, "x")
                    for item in raw["items"]:
                        # assertTrue, never assertIn: assertIn's message
                        # prints the container, and the container is an event.
                        self.assertTrue("start" in item, "an event has no `start`")
                        self.assertTrue({"date", "dateTime"} & set(item["start"]),
                                        "`start` has neither `date` nor `dateTime`")
                    kept = [i for i in raw["items"] if i.get("status") != "cancelled"
                            and i.get("eventType") not in providers_calendar.SKIPPED_GOOGLE_TYPES
                            and not any(a.get("self") and a.get("responseStatus") == "declined"
                                        for a in i.get("attendees", []))]
                else:
                    raw = providers_calendar.fetch_graph(token, self.now, self.until)
                    self.assertIsInstance(raw.get("value"), list,
                                          "calendarView has no `value` list; re-record "
                                          "fixtures/graph_calendarview.json")
                    rows = providers_calendar.normalise_graph(raw, "x")
                    for item in raw["value"]:
                        self.assertTrue(str(item["start"].get("timeZone")).upper()
                                        in providers_calendar.UTC_LABELS,
                                        "Prefer: outlook.timezone=\"UTC\" was not honoured")
                        self.assertTrue("isAllDay" in item, "an event has no `isAllDay`")
                    kept = [i for i in raw["value"] if not i.get("isCancelled")
                            and (i.get("responseStatus") or {}).get("response") != "declined"]
                # Every event the filters keep must come out of the normaliser.
                # A normaliser that silently read nothing would pass every
                # check above; this is the one it fails. Counts only, never
                # the events, in the message.
                self.assertEqual(len(rows), len(kept),
                                 f"{len(kept)} events should survive and {len(rows)} did")
