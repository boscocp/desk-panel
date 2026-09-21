#!/usr/bin/env python3
"""Fail if a finished wave has no note in docs/harness-notes/.

ADR 0011 says every round leaves a note. Nothing enforced it, the series lapsed for ten
waves, and the record migrated into tasks/STATUS.md by accident rather than by decision -
see docs/harness-notes/README.md. This is the enforcement.

A wave is finished when tasks/STATUS.md carries its `## Resuming after <date> (wave N)`
section, which is the repo's own record that the wave landed. From --floor onwards each
one needs a note at docs/harness-notes/<date>-wave-<N>.md carrying the three headings the
README requires. Earlier waves are the recorded backlog and are not failed retroactively.

Exit codes: 0 clean, 1 a wave has no note or a note is missing a heading, 2 usage error.

Usage:
  python scripts/check_harness_notes.py [--floor N] [--status PATH] [--notes DIR]
"""

import re
import sys
from pathlib import Path

FLOOR = 16
WAVE_RE = re.compile(r"^## Resuming after (\d{4}-\d{2}-\d{2}) \(wave (\d+)\)", re.M)
REQUIRED = ("## What ran", "## What the review found", "## What is not proven")


def main(argv: list[str]) -> int:
    floor, status, notes = FLOOR, Path("tasks/STATUS.md"), Path("docs/harness-notes")
    args = argv[1:]
    while args:
        flag = args.pop(0)
        if not args:
            print(f"check_harness_notes: {flag} needs a value", file=sys.stderr)
            return 2
        value = args.pop(0)
        if flag == "--floor":
            floor = int(value)
        elif flag == "--status":
            status = Path(value)
        elif flag == "--notes":
            notes = Path(value)
        else:
            print(f"check_harness_notes: unknown option {flag}", file=sys.stderr)
            return 2

    if not status.is_file():
        print(f"check_harness_notes: no such file: {status}", file=sys.stderr)
        return 2

    problems: list[str] = []
    waves = {int(n): date for date, n in WAVE_RE.findall(status.read_text(encoding="utf-8"))}

    for wave in sorted(w for w in waves if w >= floor):
        found = sorted(notes.glob(f"*-wave-{wave}.md"))
        if not found:
            problems.append(
                f"wave {wave} landed on {waves[wave]} and has no note: "
                f"expected {notes}/{waves[wave]}-wave-{wave}.md"
            )
            continue
        for note in found:
            text = note.read_text(encoding="utf-8")
            missing = [h for h in REQUIRED if h not in text]
            if missing:
                problems.append(f"{note}: missing {', '.join(missing)}")

    if problems:
        print(f"check_harness_notes: {len(problems)} problem(s)", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print("\n  see docs/harness-notes/README.md for what a wave note carries", file=sys.stderr)
        return 1

    counted = sum(1 for w in waves if w >= floor)
    print(f"check_harness_notes: {counted} wave(s) from {floor} onward, each with a note")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
