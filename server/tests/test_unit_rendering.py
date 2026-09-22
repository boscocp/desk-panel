"""T3.9: the systemd unit, rendered from paths that are hostile to `sed`.

`install_user_unit.sh` builds the unit by substituting four of this machine's
own paths into `desk-panel.service.in`. Nothing about that is interesting
until one of the paths contains a character `sed` reads as syntax -- and three
do: `&` stands for the whole match in a replacement, `|` is the delimiter the
script chose, and a backslash escapes whatever follows it.

**This file exists because the escaping has now been wrong twice.** The first
version had none at all. The second added a `sed_escape` whose replacement was
one backslash too many, so it emitted `\\\\&` where `sed` wanted `\\&`; a repo
at `~/proj&panel` rendered an `ExecStart` with the *placeholder's own text*
spliced into it, installed cleanly, enabled cleanly, printed "Installed" and
then failed at start naming half a path. A `|` was worse: the outer expression
aborted with `unknown option to 's'` after the redirection had already
truncated the unit file, so the failure left a zero-byte unit behind.

Both were caught by reading, once each. Reading is not a test, and the guard
that failed here was itself written to prevent exactly the corruption it
produced -- a comment can claim a path is escaped while the code unescapes it,
and only running it can tell the two apart.

So this runs the shipped function. `sed_escape` is extracted from the real
script rather than copied, because a copy is a second account that drifts:
if somebody rewrites the escaping and forgets this file, the extraction fails
loudly instead of testing a function nobody ships any more.

Nothing here touches `~/.config/systemd`, runs `systemctl`, or needs a Linux
session -- it renders the template to a string and reads it.
"""
import os
import re
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(HERE)
INSTALLER = os.path.join(SERVER_DIR, "install_user_unit.sh")
TEMPLATE = os.path.join(SERVER_DIR, "desk-panel.service.in")

# The four placeholders the installer substitutes, and the order it does it in.
PLACEHOLDERS = ("@PYTHON@", "@SERVER_PY@", "@CONFIG@", "@REPO@")

# One path per character that means something to sed, plus the ordinary case
# and the space the template's quoting is there for. None of these exists on
# anybody's machine today, which is the whole reason nobody would look here.
HOSTILE = {
    "plain": "/home/me/desk-panel",
    "ampersand": "/home/me/proj&panel",
    "pipe": "/home/me/a|b",
    "backslash": "/home/me/a\\b",
    "space": "/home/My Projects/desk-panel",
    "all of them": "/home/My &Projects|a\\b",
}


def extract_sed_escape():
    """The `sed_escape` definition, lifted verbatim out of the shipped script."""
    with open(INSTALLER, encoding="utf-8") as handle:
        source = handle.read()
    match = re.search(r"^sed_escape\(\) \{.*?^\}", source, re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(
            "install_user_unit.sh no longer defines sed_escape(); this test "
            "renders the shipped function and cannot find it")
    return match.group(0)


class UnitRenderingTests(unittest.TestCase):
    """Render the real template through the real escaping."""

    @classmethod
    def setUpClass(cls):
        if shutil.which("bash") is None or shutil.which("sed") is None:
            raise unittest.SkipTest("needs bash and sed, which is every Linux desk")
        cls.sed_escape = extract_sed_escape()
        with open(TEMPLATE, encoding="utf-8") as handle:
            cls.template = handle.read()

    def render(self, paths):
        """Run the installer's own pipeline: escape each value, then one sed."""
        script = [self.sed_escape, 'value=""']
        args = []
        for placeholder, path in zip(PLACEHOLDERS, paths):
            args.append(placeholder)
            args.append(path)
        # The script body mirrors install_user_unit.sh: escape into a variable,
        # then interpolate that variable into `s|@NAME@|...|g`.
        script.append('set -e')
        script.append('expr_args=()')
        script.append('while [ "$#" -gt 0 ]; do')
        script.append('  name="$1"; val="$2"; shift 2')
        script.append('  esc="$(sed_escape "$val")"')
        script.append('  expr_args+=(-e "s|$name|$esc|g")')
        script.append('done')
        script.append('sed "${expr_args[@]}"')
        proc = subprocess.run(
            ["bash", "-c", "\n".join(script), "bash"] + args,
            input=self.template, capture_output=True, text=True)
        return proc

    def test_every_hostile_path_renders_to_itself(self):
        # The assertion is deliberately the strongest one available: the path
        # comes back *byte for byte*. A weaker check -- "sed did not fail", or
        # "the placeholder is gone" -- passes for the exact bug this file was
        # written after, where the output was a well-formed line containing the
        # wrong path.
        for label, path in HOSTILE.items():
            with self.subTest(path=label):
                proc = self.render([path] * len(PLACEHOLDERS))
                self.assertEqual(proc.returncode, 0,
                                 f"sed failed for {label}: {proc.stderr.strip()}")
                self.assertIn(f'ExecStart="{path}" -u "{path}" --config "{path}"',
                              proc.stdout,
                              f"{label} did not survive the substitution")

    def test_no_placeholder_survives_the_render(self):
        # The ampersand bug's signature: the replacement text put `@PYTHON@`
        # back into the output, so a placeholder was still there afterwards and
        # systemd was handed it as part of a path.
        for label, path in HOSTILE.items():
            with self.subTest(path=label):
                proc = self.render([path] * len(PLACEHOLDERS))
                for placeholder in PLACEHOLDERS:
                    self.assertNotIn(
                        placeholder, proc.stdout,
                        f"{placeholder} survived the render for {label}")

    def test_a_pipe_does_not_abort_the_expression(self):
        # This one failed loudly rather than quietly, but it failed *after* the
        # redirection had truncated the unit file -- so the state it left was a
        # zero-byte unit, not the previous one. Worth its own name.
        proc = self.render(["/home/me/a|b"] * len(PLACEHOLDERS))
        self.assertEqual(proc.returncode, 0, proc.stderr.strip())
        self.assertNotIn("unknown option", proc.stderr)

    def test_the_template_still_quotes_every_value(self):
        # The other half of the space case, and it lives in the template rather
        # than in the escaping: systemd splits a command line on whitespace, so
        # a path with a space in it needs quotes there whatever sed did.
        self.assertIn('ExecStart="@PYTHON@" -u "@SERVER_PY@" --config "@CONFIG@"',
                      self.template)


if __name__ == "__main__":
    unittest.main()
