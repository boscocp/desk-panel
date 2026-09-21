"""TT.10: every platform's login-scope check, on whichever machine you are on.

`verify_login_scope.py` decides whether this PC's autostart is scoped to a
graphical login session, which is the whole of invariant 2 and of
[ADR 0010](../../docs/adr/0010-login-signal-is-session-scoped.md). Two thirds
of it can never run here: the Windows half needs `schtasks`, the macOS half
needs a Mac, and nobody on this project has one. Left at that, T3.10 would be
unverifiable for ever and T3.8's checks would rot quietly between the rare
afternoons somebody boots the Windows box.

So the parsing and the running are separate, and this file exercises the
parsing against recorded output. Every fixture under
`server/fixtures/login_scope/` is real text a real command produced, captured
once and committed; nothing here shells out, reads a machine's state or
sleeps, and `NothingRunsTests` below proves it rather than promising it.

The single most valuable assertion in the file is that a
`WantedBy=default.target` unit comes back **not compliant**. That is what
`docs/SERVER-SETUP.md` used to recommend, it looks correct, it passes every
other check, and ADR 0010 rejects it: `default.target` is reached at boot
when lingering is on and by any SSH session, so the server would answer at
the greeter with nobody logged in.

The module ships its own `--self-test`, which is the same body of cases and
is what `python server/verify_login_scope.py --self-test` runs. It is
imported rather than duplicated here: two lists of expectations drift, and
the one thing worse than an unverifiable platform is two disagreeing accounts
of what its output means.
"""
import unittest
from unittest import mock

from server import verify_login_scope as vls


class SelfTestCaseTests(unittest.TestCase):
    """Every case the module's own --self-test runs, as one subTest each.

    The point of bringing them in here is the discovery command: this suite
    is what `make check` runs and what CI will run (TT.9), and a self-test
    nobody invokes is a self-test that goes stale. Reported per case rather
    than as one pass/fail line so a break names the platform it is on.
    """

    def test_every_recorded_case_matches(self):
        cases = vls.self_test_cases()
        # A floor rather than an exact count: the number grows whenever a
        # platform gains a check, and a test that had to be edited for that
        # would be edited without being read. Zero cases, on the other hand,
        # is how this file would pass if the fixtures went missing.
        self.assertGreater(len(cases), 80)
        for label, actual, expected in cases:
            with self.subTest(label):
                self.assertEqual(actual, expected)


class NothingRunsTests(unittest.TestCase):
    """The parsers are pure, and this is the assertion rather than the claim.

    TT.10's note says it plainly: if a test needs a real `systemctl`, the
    parsing and the execution have not been separated properly -- and the fix
    is to the verifier, not to the test. So the two doors out of this process
    are nailed shut and the whole case list is run through them again.
    """

    def test_no_case_shells_out_or_touches_the_filesystem(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("a self-test case reached the machine it is running on")

        with mock.patch.object(vls, "run_command", forbidden), \
                mock.patch.object(vls, "read_registry_autologin", forbidden), \
                mock.patch.object(vls, "read_file", forbidden), \
                mock.patch.object(vls, "file_present", forbidden):
            cases = vls.self_test_cases()
        self.assertTrue(cases)

    def test_the_doors_being_nailed_shut_would_actually_be_noticed(self):
        """The guard above is only worth having if the things it patches are
        the things that reach the machine. `run_command` is the one every
        platform's collector goes through, so a run of the real checks must
        trip it -- and if some future collector grows a second door, this is
        the assertion that stops the one above passing while meaning nothing.
        """
        def forbidden(*args, **kwargs):
            raise AssertionError("reached the machine")

        with mock.patch.object(vls, "run_command", forbidden):
            with self.assertRaises(AssertionError):
                vls.run_checks("linux", environ={})


class SystemdUserUnitTests(unittest.TestCase):
    """The Linux row of ADR 0010, and the trap it was written against."""

    def properties(self, name):
        return vls.parse_systemctl_show(vls.fixture(name))

    def test_the_documented_unit_passes_every_check(self):
        checks = vls.check_systemd_user_unit(
            self.properties("linux_systemctl_show_user_good.txt"))
        self.assertTrue(checks)
        for check in checks:
            with self.subTest(check.name):
                self.assertEqual(check.status, vls.PASS, check.detail)

    def test_a_wanted_by_default_target_unit_is_not_compliant(self):
        """The one that matters. A unit wanted by default.target is started by
        a lingering user manager at boot and by every SSH session, so it
        answers with nobody at the screen -- and it looks completely
        reasonable, which is why it was the documented advice until ADR 0010.
        """
        statuses = vls.statuses(vls.check_systemd_user_unit(
            self.properties("linux_systemctl_show_user_default_target.txt")))
        self.assertEqual(statuses["linux.unit.wanted-by"], vls.FAIL)
        # And the second half of the same mistake: PartOf is what stops the
        # unit at logout. Without it the unit survives, because logind
        # defaults to KillUserProcesses=no -- so a panel would keep reporting
        # "logged in" for as long as the machine stayed on.
        self.assertEqual(statuses["linux.unit.part-of"], vls.FAIL)

    def test_an_uninstalled_unit_fails_rather_than_passing_vacuously(self):
        statuses = vls.statuses(vls.check_systemd_user_unit(
            self.properties("linux_systemctl_show_user_absent.txt")))
        self.assertEqual(statuses["linux.unit.loaded"], vls.FAIL)

    def test_the_unit_must_not_be_in_the_default_target_closure(self):
        """The same property proved directly, and it is the stronger form:
        it holds whatever `Linger` says, which is why this project checks the
        closure instead of checking lingering. T3.9's acceptance requires it
        to pass with `Linger=yes`, which is this machine's state.
        """
        bad = vls.parse_list_dependencies(
            vls.fixture("linux_list_dependencies_default_bad.txt"))
        self.assertEqual(
            vls.check_not_in_default_closure(bad).status, vls.FAIL)

        good = vls.parse_list_dependencies(
            vls.fixture("linux_list_dependencies_default_good.txt"))
        self.assertEqual(
            vls.check_not_in_default_closure(good).status, vls.PASS)


class WindowsScheduledTaskTests(unittest.TestCase):
    """The Windows row, from `schtasks /query /xml`."""

    def test_the_registered_task_passes_every_check(self):
        task = vls.parse_schtasks_xml(vls.fixture("windows_schtasks_good.xml"))
        for check in vls.check_windows_task(task):
            with self.subTest(check.name):
                self.assertEqual(check.status, vls.PASS, check.detail)

    def test_the_real_capture_from_the_windows_box_still_passes(self):
        """Not the same fixture as the one above, and the difference is the
        point: this one is what `schtasks /query /xml` actually printed on the
        machine T3.8 was run on, childless elements, boilerplate and all. The
        handwritten fixture is what the checks were designed against; this is
        what they have to survive.
        """
        task = vls.parse_schtasks_xml(vls.fixture("windows_schtasks_real_capture.xml"))
        for check in vls.check_windows_task(task):
            with self.subTest(check.name):
                self.assertEqual(check.status, vls.PASS, check.detail)

    def test_the_three_windows_traps_are_each_caught(self):
        """One fixture carrying all three, because they arrive together: a
        task somebody built for "start it at boot" has a BootTrigger, stores a
        password so it can run with nobody logged on, and keeps the default
        72-hour execution limit that would kill the server mid-week.
        """
        task = vls.parse_schtasks_xml(
            vls.fixture("windows_schtasks_bad_boot_trigger.xml"))
        statuses = vls.statuses(vls.check_windows_task(task))
        self.assertEqual(statuses["windows.task.logon-trigger"], vls.FAIL)
        self.assertEqual(statuses["windows.task.logon-type"], vls.FAIL)
        self.assertEqual(statuses["windows.task.execution-time-limit"], vls.FAIL)

    def test_output_that_is_not_a_task_raises_rather_than_reading_as_absent(self):
        """Absence is an answer; unparsable output is not. Folding the two
        together would report a machine with a broken `schtasks` as a machine
        with no task, which is a different thing to go and fix.
        """
        with self.assertRaises(vls.ParseError):
            vls.parse_schtasks_xml("not xml at all")


class MacOsLaunchAgentTests(unittest.TestCase):
    """The macOS row, which nobody on this project can run for real."""

    def agent(self, plist_name, print_name, path="/Users/u/Library/LaunchAgents/x.plist"):
        plist = vls.parse_launchagent_plist(vls.fixture(plist_name))
        printed = vls.parse_launchctl_print(vls.fixture(print_name))
        return vls.statuses(vls.check_macos_agent(plist, printed, path))

    def test_an_aqua_agent_loaded_in_the_gui_domain_passes(self):
        statuses = self.agent("macos_launchagent_good.plist",
                              "macos_launchctl_print_agent.txt")
        for name, status in statuses.items():
            with self.subTest(name):
                self.assertEqual(status, vls.PASS)

    def test_an_unset_session_type_is_not_compliant(self):
        """Unset is not a neutral default: the agent then loads in Aqua,
        LoginWindow *and* Background, so it runs at the login screen.
        """
        statuses = self.agent("macos_launchagent_no_session_type.plist",
                              "macos_launchctl_print_agent.txt")
        self.assertEqual(statuses["macos.agent.session-type"], vls.FAIL)

    def test_a_loginwindow_session_type_is_not_compliant(self):
        """The deliberate version of the same mistake, and the one somebody
        reaches for on purpose: reading the three session types as a
        chronology and picking the earliest, so the panel is up "as soon as
        possible". LoginWindow is the greeter -- nobody is logged in there,
        which is the exact state the server's answer exists to distinguish.
        """
        statuses = self.agent("macos_launchagent_loginwindow.plist",
                              "macos_launchctl_print_agent.txt")
        self.assertEqual(statuses["macos.agent.session-type"], vls.FAIL)

    def test_a_daemon_is_not_an_agent_however_well_it_is_written(self):
        """`launchctl print system/...` finds it, and that is the failure:
        a LaunchDaemon runs with no user at all. The plist here is the good
        one, so the only thing under test is the domain it is loaded in.
        """
        statuses = self.agent("macos_launchagent_good.plist",
                              "macos_launchctl_print_daemon.txt")
        self.assertEqual(statuses["macos.agent.loaded"], vls.FAIL)

    def test_an_agent_that_is_not_loaded_fails(self):
        statuses = self.agent("macos_launchagent_good.plist",
                              "macos_launchctl_print_absent.txt")
        self.assertEqual(statuses["macos.agent.loaded"], vls.FAIL)

    def test_a_plist_in_the_system_wide_directory_fails(self):
        """/Library/LaunchAgents loads for every user who logs in, so the
        panel would report a stranger's session as the owner's.
        """
        statuses = self.agent("macos_launchagent_good.plist",
                              "macos_launchctl_print_agent.txt",
                              path="/Library/LaunchAgents/dev.bosco.deskpanel.plist")
        self.assertEqual(statuses["macos.agent.location"], vls.FAIL)


class EnvironmentDetectorTests(unittest.TestCase):
    """The three things that make a perfect unit report the wrong thing."""

    def test_auto_login_is_detected_on_all_three_platforms(self):
        """Auto-login degrades the signal to "the machine is powered on": the
        target activates with nobody present. Nothing at this layer can fix
        it, so the verifier's job is to say so.
        """
        linux_on = vls.detect_autologin("linux", {
            "gdm": vls.captured(vls.fixture("linux_gdm_autologin_on.conf"))})
        self.assertEqual(linux_on.status, vls.FAIL)

        # "win32", which is what sys.platform says on Windows and therefore
        # what run_checks passes. Spelling it "windows" here falls through to
        # the Linux branch, finds no display manager and answers UNKNOWN --
        # which is not a pass, so half of this test would have gone on
        # asserting something true about the wrong platform.
        windows_on = vls.detect_autologin("win32", {
            "winlogon": vls.captured(vls.fixture("windows_reg_autologin_on.txt"))})
        self.assertEqual(windows_on.status, vls.FAIL)

        macos_on = vls.detect_autologin("darwin", {
            "loginwindow": vls.captured(vls.fixture("macos_defaults_autologin_on.txt"))})
        self.assertEqual(macos_on.status, vls.FAIL)

    def test_auto_login_off_passes_on_all_three_platforms(self):
        # Asserted alongside the row above so neither can be satisfied by a
        # detector that simply always fails.
        self.assertEqual(vls.detect_autologin("linux", {
            "gdm": vls.captured(vls.fixture("linux_gdm_autologin_off.conf"))}).status,
            vls.PASS)
        self.assertEqual(vls.detect_autologin("win32", {
            "winlogon": vls.captured(vls.fixture("windows_reg_autologin_off.txt"))}).status,
            vls.PASS)
        self.assertEqual(vls.detect_autologin("darwin", {
            "loginwindow": vls.captured(vls.fixture("macos_defaults_autologin_absent.txt"))}).status,
            vls.PASS)

    def test_wsl_is_detected_from_the_kernel_release(self):
        """TT.10's table says /proc/version; the verifier reads
        /proc/sys/kernel/osrelease, which carries the same `microsoft` marker
        in a single line with nothing else in it. A WSL distribution's session
        has no relationship to whether anybody is at the Windows desktop -- it
        survives lock and outlives logout -- so a perfect systemd unit there
        still reports the wrong thing.
        """
        wsl = vls.detect_wsl("linux", {
            "osrelease": vls.captured(vls.fixture("linux_osrelease_wsl.txt"))})
        self.assertEqual(wsl.status, vls.FAIL)

        native = vls.detect_wsl("linux", {
            "osrelease": vls.captured(vls.fixture("linux_osrelease_native.txt"))})
        self.assertEqual(native.status, vls.PASS)

    def test_an_unreadable_kernel_release_is_unknown_and_not_a_pass(self):
        """UNKNOWN is a distinct outcome on purpose: "this machine is wrong"
        and "this tool could not tell" are different things to act on, and
        both are non-zero.
        """
        self.assertEqual(
            vls.detect_wsl("linux", {"osrelease": vls.unreadable("permission denied")}).status,
            vls.UNKNOWN)

    def test_a_container_is_detected_from_dockerenv(self):
        """A container answers with nobody logged in at all, which is the most
        complete way to break the invariant -- and ADR 0003 puts `docker
        compose` within arm's reach for the Android toolchain, so the wrong
        reflex is a familiar one on this project.
        """
        inside = vls.detect_container("linux", {"dockerenv": vls.captured("")})
        self.assertEqual(inside.status, vls.FAIL)

    def test_cgroup_v2_cannot_tell_a_container_from_a_host_and_says_so(self):
        """Verified against `docker run alpine`: under cgroup v2 a container's
        /proc/self/cgroup reads "0::/", exactly like the host. With no
        systemd-detect-virt to ask, the absence of markers proves nothing, and
        the detector returns UNKNOWN rather than a pass it cannot justify.
        """
        ambiguous = vls.detect_container("linux", {
            "cgroup": vls.captured(vls.fixture("linux_cgroup_v2_host.txt"))})
        self.assertEqual(ambiguous.status, vls.UNKNOWN)


class ExitCodeTests(unittest.TestCase):
    """What the shell sees, which is the only part T3.8 and T3.9 assert on."""

    def test_a_failure_and_an_unknown_are_both_non_zero(self):
        self.assertEqual(vls.exit_code([vls.Check("a", vls.PASS, "")]), 0)
        self.assertNotEqual(vls.exit_code([vls.Check("a", vls.FAIL, "")]), 0)
        self.assertNotEqual(vls.exit_code([vls.Check("a", vls.UNKNOWN, "")]), 0)

    def test_nothing_checked_is_not_success(self):
        """An empty report is what a verifier that failed to collect anything
        produces, and exiting 0 on it would turn a broken tool into a green
        acceptance line in T3.8 and T3.9.
        """
        self.assertNotEqual(vls.exit_code([]), 0)


if __name__ == "__main__":
    unittest.main()
