#!/usr/bin/env python3
"""Fail if any task's Acceptance section is not a command with an exit code.

CLAUDE.md states the rule three times: "Every acceptance criterion is a command with
an exit code. If you find yourself judging a task by looking at output, the task file
is wrong - fix the task file." This script is that rule, enforced.

It reads every tasks/*.md with an id (T*.md, TT*.md) and checks the `## Acceptance`
section for:

  - at least one fenced command block
  - no criterion whose real assertion is prose ("no output", "Returns nothing")
  - no command that never terminates (`adb logcat` without -d, a bare server start)
  - no command that exits 0 regardless of the result: `curl -w` with nothing reading
    it, or a grep that matches a label while its comment carries the real assertion
  - no prose telling a human what to look at - that belongs under `## Manual check`
  - a `Requires:` header field whenever the acceptance touches the phone

Exit codes: 0 clean, 1 violations found, 2 usage error.

Usage:
  python scripts/check_acceptance.py [tasks_dir]
"""

import re
import sys
from pathlib import Path

# A criterion whose verdict is read by a human instead of by the shell.
PROSE_VERDICT = [
    (re.compile(r"#\s*no output", re.I), "prose verdict '# no output' - use `! grep -q ...`"),
    (re.compile(r"#\s*expected:", re.I), "prose verdict '# expected:' - assert it instead"),
    (re.compile(r"returns nothing", re.I), "prose verdict 'returns nothing' - use `! grep -q ...`"),
]

# A command that blocks forever, hanging whoever runs the acceptance.
NON_TERMINATING = [
    (
        # -d dumps and exits; -c clears the buffer and exits. Everything else
        # follows the log forever and hangs whoever runs the acceptance.
        re.compile(r"\badb\s+logcat\b(?![^\n]*\s-[dc]\b)"),
        "`adb logcat` without -d or -c never returns - use `adb logcat -d | grep -q ...`",
    ),
    (
        re.compile(r"\bpython3?\s+server/server\.py\s*(&\s*)?$", re.M),
        "a bare server start never returns - start and stop it in one command",
    ),
]

# A command whose exit status carries no information about the assertion.
ALWAYS_ZERO = [
    (
        re.compile(r"curl[^\n|]*-w[^\n|]*$", re.M),
        "`curl -w` prints the code but always exits 0 - pipe it into `grep -qx`",
    ),
    (
        # `... | grep -i "mCurrentFocus"   # names this activity` matches the field
        # label on every device, whatever is focused. The assertion lives in the
        # comment, where the shell cannot reach it.
        re.compile(r"\|\s*grep\b[^\n#]*#[^\n]*\b(names?|shows?|prints?|must|should|appears?)\b", re.I),
        "the grep matches a label while the assertion sits in its comment - grep for the value",
    ),
]

# Prose that tells a human what to look at. Not wrong - but it belongs under
# `## Manual check`, where nothing pretends it has an exit code.
HUMAN_VERDICT = re.compile(
    r"^\s*(?:Then[, ]+)?(?:Open|Confirm|Observe|Watch|Judged|Leave it|Install it|Browse)\b"
    r"|\bplausible\b|\bvisibly\b|\bby eye\b|\bnothing (?:clips|overlaps)\b"
    r"|\bconsole is clean\b|\bNetwork tab\b|\bstill advancing\b|\btrack reality\b",
    re.M | re.I,
)

# Acceptance that can only run with the phone attached.
PHONE = re.compile(r"\badb\b|connectedAndroidTest")

ID_RE = re.compile(r"^(T\d+\.\d+|TT\.\d+)-")
FENCE_RE = re.compile(r"```[a-z]*\n(.*?)```", re.S)


def acceptance_section(text: str) -> str | None:
    """Return the body of the `## Acceptance` section, or None if there is none."""
    m = re.search(r"^##\s+Acceptance\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    return m.group(1) if m else None


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []

    body = acceptance_section(text)
    if body is None:
        return [f"{path.name}: no `## Acceptance` section"]

    blocks = FENCE_RE.findall(body)
    if not blocks:
        problems.append(f"{path.name}: Acceptance has no command block - it is prose only")

    commands = "\n".join(blocks)

    # Check prose with inline `code` spans removed, so a task may quote the wrong
    # way of writing a criterion while explaining why it is wrong.
    prose = re.sub(r"`[^`]*`", "", FENCE_RE.sub("", body))
    for pattern, message in PROSE_VERDICT:
        if pattern.search(commands) or pattern.search(prose):
            problems.append(f"{path.name}: {message}")
    for pattern, message in NON_TERMINATING + ALWAYS_ZERO:
        if pattern.search(commands):
            problems.append(f"{path.name}: {message}")

    hit = HUMAN_VERDICT.search(prose)
    if hit:
        problems.append(
            f"{path.name}: Acceptance asks a human to look ({hit.group(0).strip()!r}) "
            "- move it to `## Manual check`"
        )

    if PHONE.search(commands) and not re.search(r"^Requires:.*\bphone\b", text, re.M | re.I):
        problems.append(
            f"{path.name}: acceptance needs the phone but the header has no `Requires: phone`"
        )

    return problems


def main(argv: list[str]) -> int:
    tasks_dir = Path(argv[1]) if len(argv) > 1 else Path("tasks")
    if not tasks_dir.is_dir():
        print(f"check_acceptance: no such directory: {tasks_dir}", file=sys.stderr)
        return 2

    files = sorted(p for p in tasks_dir.glob("*.md") if ID_RE.match(p.name))
    if not files:
        print(f"check_acceptance: no task files in {tasks_dir}", file=sys.stderr)
        return 2

    problems = [p for f in files for p in check_file(f)]
    for problem in problems:
        print(f"  {problem}")

    if problems:
        print(f"\ncheck_acceptance: FAIL - {len(problems)} in {len(files)} task files")
        return 1
    print(f"check_acceptance: OK - {len(files)} task files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
