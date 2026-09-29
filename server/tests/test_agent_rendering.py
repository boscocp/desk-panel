"""T3.10: the LaunchAgent, rendered and then read by the verifier's own parser.

`install_agent.sh` builds `~/Library/LaunchAgents/dev.bosco.deskpanel.plist`
from `dev.bosco.deskpanel.plist.in`. The first render on a real Mac
(2026-09-29) passed `plutil -lint`, loaded, ran and answered `/ping` -- and
`verify_login_scope.py` then reported **unknown** on it: "not well-formed
(invalid token): line 47". A comment in the template said "Background sessions
-- that is, at the login screen", and `--` is illegal inside an XML comment.
`plutil` is lenient about it; `plistlib`, which the verifier uses, is not. So
the agent worked and could never be proved to, which is the fail-closed rule
doing its job on a file this repository wrote.

This runs the shipped renderer -- the Python heredoc, lifted out of the real
script rather than copied, the same way test_unit_rendering.py lifts
`sed_escape` -- against paths carrying the characters XML reads as syntax,
and hands the result to the verifier. Nothing here runs launchctl or touches
~/Library, so it runs on any OS.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from server import verify_login_scope as vls

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(HERE)
INSTALLER = os.path.join(SERVER_DIR, "install_agent.sh")
TEMPLATE = os.path.join(SERVER_DIR, "dev.bosco.deskpanel.plist.in")
USER_AGENTS = "/Users/me/Library/LaunchAgents/dev.bosco.deskpanel.plist"

HOSTILE = {
    "plain": "/Users/me/desk-panel",
    "space": "/Users/me/My Projects/desk-panel",
    "ampersand": "/Users/me/proj&panel",
    "angle brackets": "/Users/me/<panel>",
    "all of them": "/Users/me/My <&> Projects",
}


def extract_renderer():
    """The heredoc between `<<'EOF'` and `EOF`, verbatim from the installer."""
    text = Path(INSTALLER).read_text(encoding="utf-8")
    match = re.search(r"<<'EOF'\n(.*?)\nEOF\n", text, re.S)
    if match is None:
        raise AssertionError("install_agent.sh no longer renders through a <<'EOF' heredoc")
    return match.group(1)


def render(root):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "agent.plist")
        subprocess.run(
            [sys.executable, "-", TEMPLATE, out,
             f"{root}/bin/python3", f"{root}/server/server.py",
             f"{root}/server/config.toml", f"{root}/desk-panel.log"],
            input=extract_renderer(), text=True, check=True, capture_output=True,
        )
        return Path(out).read_text(encoding="utf-8")


class TemplateTests(unittest.TestCase):

    def test_the_template_itself_is_a_plist_the_verifier_can_read(self):
        """Unrendered, so a comment that breaks XML fails here before any path is involved."""
        plist = vls.parse_launchagent_plist(Path(TEMPLATE).read_text(encoding="utf-8"))
        self.assertEqual(plist["Label"], vls.AGENT_LABEL)


class RenderedAgentTests(unittest.TestCase):

    def test_every_hostile_path_renders_to_an_agent_that_passes(self):
        printed = {"found": True, "type": "LaunchAgent", "domain": "gui/501"}
        for name, root in HOSTILE.items():
            with self.subTest(name):
                plist = vls.parse_launchagent_plist(render(root))
                self.assertEqual(plist["ProgramArguments"], [
                    f"{root}/bin/python3", "-u", f"{root}/server/server.py",
                    "--config", f"{root}/server/config.toml",
                ])
                self.assertEqual(plist["StandardOutPath"], f"{root}/desk-panel.log")
                statuses = vls.statuses(vls.check_macos_agent(plist, printed, USER_AGENTS))
                self.assertEqual(set(statuses.values()), {vls.PASS}, statuses)

    def test_the_fields_adr_0010_names_are_the_ones_shipped(self):
        plist = vls.parse_launchagent_plist(render(HOSTILE["plain"]))
        self.assertEqual(plist["LimitLoadToSessionType"], "Aqua")
        self.assertIs(plist["RunAtLoad"], True)
        self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(plist["ProcessType"], "Interactive")

    def test_a_placeholder_the_renderer_does_not_know_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            template = os.path.join(tmp, "t.plist.in")
            Path(template).write_text(
                Path(TEMPLATE).read_text(encoding="utf-8").replace(
                    "<string>-u</string>", "<string>@NEW@</string>"),
                encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-", template, os.path.join(tmp, "out.plist"),
                 "/p", "/s", "/c", "/l"],
                input=extract_renderer(), text=True, capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("@NEW@", result.stderr)


if __name__ == "__main__":
    unittest.main()
