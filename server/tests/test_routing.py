"""Unit tests for server.route -- pure routing, no socket, no network.

route() is what the request handler defers to entirely (server/CLAUDE.md:
"keep the request handler dumb"), so every reachable (method, path) pair
belongs here rather than behind a live HTTPServer.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from server.server import APK_CONTENT_TYPE, apk_download, index_page, newest_apk, route


class RouteTests(unittest.TestCase):
    def test_get_ping_returns_200_ok_json(self):
        status, body, content_type, _ = route("GET", "/ping")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True})

    def test_unknown_path_returns_404(self):
        status, body, content_type, _ = route("GET", "/nope")
        self.assertEqual(status, 404)
        self.assertEqual(body, b"")
        self.assertEqual(content_type, "text/plain")

    def test_post_to_ping_returns_404(self):
        # /ping is documented and tested as a GET-only route; POST must not
        # silently match it.
        status, body, content_type, _ = route("POST", "/ping")
        self.assertEqual(status, 404)
        self.assertEqual(body, b"")
        self.assertEqual(content_type, "text/plain")

    def test_path_is_case_and_slash_sensitive(self):
        status, _, _, _ = route("GET", "/ping/")
        self.assertEqual(status, 404)
        status, _, _, _ = route("GET", "/Ping")
        self.assertEqual(status, 404)


class ApkRouteTests(unittest.TestCase):
    """T3.6. `/app` reads the filesystem, so these tests own a directory
    rather than patching one -- the bug worth catching is about mtimes and
    suffixes, and a mock of `iterdir` would assert the mock."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def _apk(self, name, mtime, payload=b"PK\x03\x04"):
        path = self.directory / name
        path.write_bytes(payload)
        os.utime(path, (mtime, mtime))
        return path

    def test_no_apk_is_a_404_that_says_what_to_do(self):
        status, body, content_type, headers = apk_download(self.directory)
        self.assertEqual(status, 404)
        self.assertEqual(headers, ())
        self.assertTrue(content_type.startswith("text/plain"))
        self.assertIn(b"assembleRelease", body)

    def test_a_missing_directory_is_not_an_error(self):
        # A fresh clone has no out/ at all. That is "build first", not a 500.
        self.assertIsNone(newest_apk(self.directory / "does-not-exist"))
        status, _, _, _ = apk_download(self.directory / "does-not-exist")
        self.assertEqual(status, 404)

    def test_newest_by_mtime_not_by_name(self):
        # out/ holds app-debug.apk and desk-panel-release.apk side by side and
        # the one to install is whichever was built last. Sorted by name,
        # app-debug wins forever.
        self._apk("desk-panel-release.apk", mtime=2_000)
        self._apk("app-debug.apk", mtime=3_000)
        self.assertEqual(newest_apk(self.directory).name, "app-debug.apk")
        self._apk("desk-panel-release.apk", mtime=4_000)
        self.assertEqual(newest_apk(self.directory).name, "desk-panel-release.apk")

    def test_non_apk_files_are_ignored(self):
        # `out/` also holds output-metadata.json and a baselineProfiles/ dir.
        (self.directory / "output-metadata.json").write_text("{}")
        (self.directory / "baselineProfiles").mkdir()
        self.assertIsNone(newest_apk(self.directory))
        self._apk("desk-panel-release.apk", mtime=1_000)
        self.assertEqual(newest_apk(self.directory).name, "desk-panel-release.apk")

    def test_a_directory_named_like_an_apk_is_not_one(self):
        # `out/` already contains a directory (baselineProfiles). One named
        # `x.apk` would otherwise be chosen and then read, which is an
        # IsADirectoryError surfacing as a 500 from a route whose entire job
        # is to hand over a file.
        (self.directory / "baselineProfiles.apk").mkdir()
        self.assertIsNone(newest_apk(self.directory))
        status, _, _, _ = apk_download(self.directory)
        self.assertEqual(status, 404)

    def test_served_apk_carries_the_type_and_the_filename(self):
        self._apk("desk-panel-release.apk", mtime=1_000, payload=b"PK\x03\x04body")
        status, body, content_type, headers = apk_download(self.directory)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"PK\x03\x04body")
        # The exact type, not a prefix of it: Chrome offers to install on this
        # value and saves the file on anything else.
        self.assertEqual(content_type, APK_CONTENT_TYPE)
        self.assertEqual(
            dict(headers)["Content-Disposition"],
            'attachment; filename="desk-panel-release.apk"',
        )

    def test_index_links_to_the_apk_when_there_is_one(self):
        self._apk("desk-panel-release.apk", mtime=1_000)
        status, body, content_type, _ = index_page(self.directory)
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/html"))
        self.assertIn(b'href="/app"', body)
        self.assertIn(b"desk-panel-release.apk", body)

    def test_index_says_so_when_there_is_none(self):
        status, body, _, _ = index_page(self.directory)
        self.assertEqual(status, 200)
        self.assertNotIn(b'href="/app"', body)
        self.assertIn(b"No APK built yet", body)


if __name__ == "__main__":
    unittest.main()
