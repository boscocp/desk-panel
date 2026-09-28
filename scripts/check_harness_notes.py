#!/usr/bin/env python3
"""Fail if a finished wave has no note in docs/harness-notes/, or the note is a shell.

ADR 0011 says every round leaves a note. Nothing enforced it, the series lapsed for ten
waves, and the record migrated into tasks/STATUS.md by accident rather than by decision -
see docs/harness-notes/README.md. This is the enforcement.

A wave is finished when tasks/STATUS.md carries its `## Resuming after <date> (wave N)`
section, which is the repo's own record that the wave landed. From --floor onwards each
one needs a note at docs/harness-notes/<date>-wave-<N>.md carrying the three headings the
README requires, *with something under each of them*. Earlier waves are the recorded
backlog and are not failed retroactively.

The second half of that sentence is T10.4, and it is here because the first half was not
enough: wave 30 shipped `## What the review found` followed by
`<!-- filled in after the review runs -->` and `make check` was green. A guard that reads
the label and never the thing under it is this repository's recurring failure.

Exit codes: 0 clean, 1 a wave has no note or a note has an empty or missing section,
2 usage error.

Usage:
  python scripts/check_harness_notes.py [--floor N] [--status PATH] [--notes DIR]
  python scripts/check_harness_notes.py --self-test
"""

import re
import sys
from pathlib import Path

FLOOR = 16
WAVE_RE = re.compile(r"^## Resuming after (\d{4}-\d{2}-\d{2}) \(wave (\d+)\)", re.M)
REQUIRED = ("## What ran", "## What the review found", "## What is not proven")

# The floor a section has to clear to count as written. It is a word count because a
# placeholder is short in words however it is spelled - `<!-- todo -->`, `TBD`, `n/a`,
# a bare bullet - while an honest section is a sentence at minimum.
#
# Twelve, and the number is measured rather than picked. Across the sixteen wave notes
# that existed when this rule was written, the smallest required section was 37 words
# (`## What ran` in wave 16); the median is well over a hundred. Twelve is a third of the
# smallest one anybody has actually written, which leaves room for the shortest section
# the README explicitly sanctions - a wave with nothing outstanding saying so in one line.
#
# Generous on purpose. A guard that fires on a short but honest section teaches people to
# pad, and padding is worse than the placeholder this rule was written to catch.
MIN_WORDS = 12

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^(##\s+.*)$")


def sections(text: str) -> dict[str, str]:
    """Map each `## ` heading to the text under it, up to the next one.

    Fenced blocks are tracked so a `## ` inside one is content and not a heading.
    `###` and deeper stay inside their parent section, which is where they read.
    """
    found: dict[str, str] = {}
    heading, body, fenced = None, [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            fenced = not fenced
        match = None if fenced else HEADING_RE.match(line)
        if match:
            if heading is not None:
                found[heading] = "\n".join(body)
            heading, body = match.group(1).strip(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        found[heading] = "\n".join(body)
    return found


def substance(body: str) -> str:
    """The body with HTML comments removed - what is left is what somebody wrote.

    `<!-- ... -->` is how a placeholder is written here, so a section holding only one
    has to come out of this empty.
    """
    return COMMENT_RE.sub(" ", body).strip()


def section_problem(heading: str, note: Path, found: dict[str, str]) -> str | None:
    if heading not in found:
        return f"{note}: no {heading} heading"
    written = substance(found[heading])
    if not written:
        return f"{note}: {heading} is empty (a comment is a placeholder, not a section)"
    words = len(written.split())
    if words < MIN_WORDS:
        return (
            f"{note}: {heading} has {words} word(s), under the {MIN_WORDS} a written "
            f"section clears - say it in a sentence or say there was nothing"
        )
    return None


def run(floor: int, status: Path, notes: Path) -> list[str]:
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
            written = sections(note.read_text(encoding="utf-8"))
            problems.extend(
                p for p in (section_problem(h, note, written) for h in REQUIRED) if p
            )

    return problems


def _self_test() -> int:
    import tempfile

    failures = []

    def ok(name, condition):
        print(f"{'ok  ' if condition else 'FAIL'}  {name}")
        if not condition:
            failures.append(name)

    prose = (
        "The branch, the PR and the diff, plus the one thing this wave learned that the "
        "next one needs, written out at a length nobody would mistake for a placeholder."
    )
    complete = "".join(f"{h}\n\n{prose}\n\n" for h in REQUIRED)
    status = "## Resuming after 2026-01-01 (wave 99)\n\ntext\n"

    ok("a heading inside a fence is not a heading",
       list(sections("## a\n\n```\n## b\n```\n")) == ["## a"])
    ok("a `###` subheading stays inside its section",
       "### deeper" in sections("## a\n\n### deeper\n\ntext\n")["## a"])
    ok("a comment is not substance", substance("  <!-- filled in later -->  ") == "")
    ok("a comment spanning lines is not substance",
       substance("<!--\nfilled in\nlater\n-->") == "")
    ok("prose beside a comment is substance", substance("<!-- x -->\nreal text") == "real text")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        notes = root / "notes"
        notes.mkdir()
        status_file = root / "STATUS.md"
        status_file.write_text(status, encoding="utf-8")
        note = notes / "2026-01-01-wave-99.md"

        def problems(text):
            note.write_text(text, encoding="utf-8")
            return run(99, status_file, notes)

        ok("a complete note passes", problems(complete) == [])

        empty = problems(complete.replace(f"## What the review found\n\n{prose}",
                                          "## What the review found\n"))
        ok("a heading with nothing under it is caught",
           len(empty) == 1 and "is empty" in empty[0] and "What the review found" in empty[0])

        commented = problems(complete.replace(
            f"## What the review found\n\n{prose}",
            "## What the review found\n\n<!-- filled in after the review runs -->"))
        ok("a heading with only a comment is caught - wave 30's note, exactly",
           len(commented) == 1 and "is empty" in commented[0])

        thin = problems(complete.replace(f"## What is not proven\n\n{prose}",
                                         "## What is not proven\n\nTBD"))
        ok("a section too thin to be a sentence is caught",
           len(thin) == 1 and f"under the {MIN_WORDS}" in thin[0])

        missing = problems(complete.replace("## What ran", "## What happened"))
        ok("a heading that is not there at all is still caught",
           len(missing) == 1 and "no ## What ran heading" in missing[0])

        note.unlink()
        gone = run(99, status_file, notes)
        ok("a finished wave with no note at all is caught",
           len(gone) == 1 and "has no note" in gone[0])

        ok("a wave under the floor is not failed retroactively",
           run(100, status_file, notes) == [])

    repo = Path(__file__).resolve().parent.parent
    ok("this repository's own notes pass",
       run(FLOOR, repo / "tasks" / "STATUS.md", repo / "docs" / "harness-notes") == [])

    print(f"\ncheck_harness_notes --self-test: {len(failures)} failure(s)")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    floor, status, notes = FLOOR, Path("tasks/STATUS.md"), Path("docs/harness-notes")
    args = argv[1:]
    while args:
        flag = args.pop(0)
        if flag == "--self-test":
            return _self_test()
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

    problems = run(floor, status, notes)
    if problems:
        print(f"check_harness_notes: {len(problems)} problem(s)", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print("\n  see docs/harness-notes/README.md for what a wave note carries", file=sys.stderr)
        return 1

    waves = WAVE_RE.findall(status.read_text(encoding="utf-8"))
    counted = sum(1 for _, n in waves if int(n) >= floor)
    print(f"check_harness_notes: {counted} wave(s) from {floor} onward, each with a written note")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
