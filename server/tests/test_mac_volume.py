"""T8.8: the macOS helper reports the volume too.

What is pinned (the hub's side is in test_linux_volume): that the Swift
helper really carries the read -- on stderr, in the line
`read_volume` takes, from the default output, following that output when it
changes. The read itself needs Core Audio and a Mac; the manual check in
tasks/T8.8 is where it was measured.
"""
import re
import unittest

from server import spectrum

SOURCE = spectrum.HELPER_SOURCE.read_text(encoding="utf-8")


class MacHelperVolumeTests(unittest.TestCase):
    def test_the_line_goes_to_stderr_in_the_shape_read_volume_takes(self):
        self.assertRegex(SOURCE, r'FileHandle\.standardError\.write\("v=\\\(level\)\\n"')
        self.assertEqual(spectrum.read_volume("v=100"), 100)

    def test_the_level_is_clamped_to_what_read_volume_accepts(self):
        self.assertIn("max(0, min(100,", SOURCE)

    def test_it_reads_the_main_volume_the_osascript_read_reports(self):
        self.assertIn("kAudioHardwareServiceDeviceProperty_VirtualMainVolume", SOURCE)

    def test_it_reads_the_output_scope(self):
        self.assertRegex(SOURCE, r"VirtualMainVolume,\s*mScope: kAudioDevicePropertyScopeOutput")

    def test_it_follows_the_default_output_when_it_changes(self):
        self.assertIn("kAudioHardwarePropertyDefaultOutputDevice", SOURCE)
        self.assertRegex(SOURCE, r"AddPropertyListenerBlock\(AudioObjectID\(kAudioObjectSystemObject\),\s*&defaultOutputAddress")
        self.assertEqual(len(re.findall(r"AudioObjectAddPropertyListenerBlock\(", SOURCE)), 2)

    def test_stdout_still_carries_only_the_header_and_pcm(self):
        writes = re.findall(r"\bstdout\.write\(", SOURCE)
        self.assertEqual(len(writes), 2, "rate= line and PCM, nothing else")


if __name__ == "__main__":
    unittest.main()
