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

from server.server import (APK_CONTENT_TYPE, RELEASE_APK_NAME, apk_download,
                          apk_to_serve, attachment_filename, index_page, route)


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
        self.assertIsNone(apk_to_serve(self.directory / "does-not-exist"))
        status, _, _, _ = apk_download(self.directory / "does-not-exist")
        self.assertEqual(status, 404)

    def test_the_release_build_wins_however_old_it_is(self):
        # The rule that costs a trip to the phone if it is wrong. `make apk` is
        # assembleDebug and lands app-debug.apk in the same out/, so newest by
        # mtime would hand a debug-signed APK to a phone carrying a
        # release-signed one: INSTALL_FAILED_UPDATE_INCOMPATIBLE, whose only
        # way out is an uninstall, which drops the MIUI toggles.
        self._apk(RELEASE_APK_NAME, mtime=1_000)
        self._apk("app-debug.apk", mtime=9_000)
        self.assertEqual(apk_to_serve(self.directory).name, RELEASE_APK_NAME)

    def test_newest_by_mtime_among_the_rest(self):
        # With no release build -- a checkout where only `make apk` has ever
        # run -- newest is still the rule, and sorting by name is still wrong.
        self._apk("app-debug.apk", mtime=3_000)
        self._apk("zz-other.apk", mtime=2_000)
        self.assertEqual(apk_to_serve(self.directory).name, "app-debug.apk")
        self._apk("zz-other.apk", mtime=4_000)
        self.assertEqual(apk_to_serve(self.directory).name, "zz-other.apk")

    def test_a_release_directory_does_not_beat_a_real_debug_apk(self):
        # The preference is checked first, so it has to reject a non-file too.
        (self.directory / RELEASE_APK_NAME).mkdir()
        self._apk("app-debug.apk", mtime=1_000)
        self.assertEqual(apk_to_serve(self.directory).name, "app-debug.apk")

    def test_a_file_that_vanishes_before_the_read_is_a_404_not_a_500(self):
        # A build replacing the APK between the choice and the read. The
        # blanket except in the handler would turn it into a JSON 500 on a
        # route whose every other answer is plain text.
        apk = self._apk(RELEASE_APK_NAME, mtime=1_000)
        original = apk.read_bytes
        apk.unlink()
        del original
        status, body, _, _ = apk_download(self.directory)
        self.assertEqual(status, 404)
        self.assertIn(b"assembleRelease", body)

    def test_an_unsafe_filename_never_reaches_the_header(self):
        # send_header does no validation, and out/ is build output on a good
        # day and whatever landed there on a bad one.
        self.assertEqual(attachment_filename("desk-panel-release.apk"), "desk-panel-release.apk")
        self.assertEqual(attachment_filename('ev"il.apk'), "app.apk")
        self.assertEqual(attachment_filename("evil\r\nX-Injected: 1.apk"), "app.apk")
        self.assertEqual(attachment_filename("a b.apk"), "app.apk")

    def test_non_apk_files_are_ignored(self):
        # `out/` also holds output-metadata.json and a baselineProfiles/ dir.
        (self.directory / "output-metadata.json").write_text("{}")
        (self.directory / "baselineProfiles").mkdir()
        self.assertIsNone(apk_to_serve(self.directory))
        self._apk("desk-panel-release.apk", mtime=1_000)
        self.assertEqual(apk_to_serve(self.directory).name, "desk-panel-release.apk")

    def test_a_directory_named_like_an_apk_is_not_one(self):
        # `out/` already contains a directory (baselineProfiles). One named
        # `x.apk` would otherwise be chosen and then read, which is an
        # IsADirectoryError surfacing as a 500 from a route whose entire job
        # is to hand over a file.
        (self.directory / "baselineProfiles.apk").mkdir()
        self.assertIsNone(apk_to_serve(self.directory))
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

    def test_index_warns_when_what_it_offers_is_not_the_release_build(self):
        self._apk("app-debug.apk", mtime=1_000)
        _, body, _, _ = index_page(self.directory)
        self.assertIn(b"not the release build", body)

    def test_index_does_not_warn_about_the_release_build(self):
        self._apk(RELEASE_APK_NAME, mtime=1_000)
        _, body, _, _ = index_page(self.directory)
        self.assertNotIn(b"not the release build", body)

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
