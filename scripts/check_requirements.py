#!/usr/bin/env python3
"""Fail if `docs/REQUIREMENTS.md` disagrees with what the build actually pins.

Documentation that has drifted from the build is worse than no documentation:
a contributor installs the version the page names, hits an error the page
cannot explain, and stops trusting every other page in the repository. This is
the one kind of prose here a script can keep honest, so it does.

Each fact below names a value, the file that decides it, and the pattern that
reads it out of that file. The document has to carry a table row whose first
cell is the fact's name and whose row text contains the value the build uses.
Nothing here parses the prose around the table -- the table is the contract,
and the paragraphs are free to say whatever they need to.

The direction matters: **the build is the truth and the document follows.**
Bumping a version in `docker/Dockerfile` turns this red, which is the moment
the page is cheapest to fix.

Exit codes: 0 clean, 1 drift, 2 usage error.

Usage:
  python scripts/check_requirements.py [--doc PATH] [--root PATH]
  python scripts/check_requirements.py --self-test
"""

import re
import sys
from pathlib import Path


class Fact:
    """One version, where it is decided, and how it is read."""

    def __init__(self, name, source, pattern, join="."):
        self.name = name
        self.source = source
        self.pattern = re.compile(pattern, re.M)
        self.join = join

    def read(self, root):
        path = root / self.source
        if not path.is_file():
            return None, f"{self.source} is missing"
        found = self.pattern.search(path.read_text(encoding="utf-8"))
        if not found:
            return None, f"{self.source} no longer matches {self.pattern.pattern!r}"
        return self.join.join(found.groups()), None


# Every floor a contributor has to meet, and the single file that decides each.
# A value with two sources would be a value that can disagree with itself.
FACTS = (
    Fact("Python", "server/server.py", r"^MIN_PYTHON = \((\d+), (\d+)\)"),
    Fact("Python (CI)", ".github/workflows/ci.yml", r'python-version: "([\d.]+)"'),
    Fact("Node", ".github/workflows/ci.yml", r'node-version: "([\d.]+)"'),
    Fact("JDK", "docker/Dockerfile", r"^FROM eclipse-temurin:([\d.]+)_"),
    Fact("Java bytecode", "android/app/build.gradle.kts",
         r"sourceCompatibility = JavaVersion\.VERSION_(\d+)"),
    Fact("Gradle", "android/gradle/wrapper/gradle-wrapper.properties",
         r"gradle-([\d.]+)-bin\.zip"),
    Fact("compileSdk", "android/app/build.gradle.kts", r"^\s*compileSdk = (\d+)"),
    Fact("minSdk", "android/app/build.gradle.kts", r"^\s*minSdk = (\d+)"),
    Fact("Android build-tools", "docker/Dockerfile", r"ARG BUILD_TOOLS=([\d.]+)"),
    Fact("Android platform", "docker/Dockerfile", r"ARG ANDROID_PLATFORM=(android-\d+)"),
    Fact("Command-line tools", "docker/Dockerfile", r"ARG CMDLINE_TOOLS_VERSION=(\d+)"),
    Fact("ruff", ".github/workflows/lint.yml", r"pip install ruff==([\d.]+)"),
)

ROW_RE = re.compile(r"^\|([^|]+)\|(.*)$", re.M)


def rows(text):
    """Pure: {first cell: the rest of the row} for every table row."""
    found = {}
    for cell, rest in ROW_RE.findall(text):
        name = cell.strip().strip("`*").strip()
        # `|---|---|` is a table's header separator, not a row. Left in, it
        # would be a name a document could accidentally define a fact under.
        if not name or set(name) <= set("-: "):
            continue
        if name not in found:
            found[name] = rest
    return found


def check(root, doc):
    if not doc.is_file():
        return [f"{doc} is missing, and every other guard here assumes it exists"]
    table = rows(doc.read_text(encoding="utf-8"))
    problems = []
    for fact in FACTS:
        value, why = fact.read(root)
        if why:
            problems.append(f"{fact.name}: {why}")
            continue
        if fact.name not in table:
            problems.append(
                f"{fact.name}: no row in {doc.name} (the build says {value}, from {fact.source})")
        elif value not in table[fact.name]:
            problems.append(
                f"{fact.name}: {doc.name} does not say {value}, which is what "
                f"{fact.source} pins")
    return problems


def _self_test():
    import tempfile

    failures = []

    def ok(name, condition):
        print(f"{'ok  ' if condition else 'FAIL'}  {name}")
        if not condition:
            failures.append(name)

    ok("a row is read by its first cell",
       rows("| Python | 3.11 | server |\n")["Python"].strip().startswith("3.11"))
    ok("backticks and emphasis do not hide a name",
       "ruff" in rows("| `**ruff**` | 0.1 |\n"))
    ok("the header separator is not a row", "---" not in rows("| a | b |\n|---|---|\n"))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "server").mkdir()
        (root / "server" / "server.py").write_text("MIN_PYTHON = (3, 11)\n", encoding="utf-8")
        doc = root / "REQUIREMENTS.md"
        one = (Fact("Python", "server/server.py", r"^MIN_PYTHON = \((\d+), (\d+)\)"),)
        global FACTS
        every = FACTS
        FACTS = one
        try:
            doc.write_text("| Python | 3.11 | floor |\n", encoding="utf-8")
            ok("a document that agrees is clean", check(root, doc) == [])

            doc.write_text("| Python | 3.9 | floor |\n", encoding="utf-8")
            problems = check(root, doc)
            ok("a version the build does not pin is caught",
               len(problems) == 1 and "3.11" in problems[0])

            doc.write_text("| Node | 24 |\n", encoding="utf-8")
            problems = check(root, doc)
            ok("a fact with no row at all is caught",
               len(problems) == 1 and "no row" in problems[0])

            (root / "server" / "server.py").write_text("MIN_PYTHON = 3.11\n", encoding="utf-8")
            doc.write_text("| Python | 3.11 |\n", encoding="utf-8")
            problems = check(root, doc)
            ok("a source that stopped matching is a failure, not a pass",
               len(problems) == 1 and "no longer matches" in problems[0])

            (root / "server" / "server.py").unlink()
            ok("a source that vanished is a failure too",
               "missing" in check(root, doc)[0])

            ok("a missing document is a failure",
               len(check(root, root / "nope.md")) == 1)
        finally:
            FACTS = every

    print(f"\ncheck_requirements --self-test: {len(failures)} failure(s)")
    return 1 if failures else 0


def main(argv):
    root, doc = Path("."), None
    args = argv[1:]
    while args:
        flag = args.pop(0)
        if flag == "--self-test":
            return _self_test()
        if flag in ("--doc", "--root"):
            if not args:
                print(f"check_requirements: {flag} needs a value", file=sys.stderr)
                return 2
            value = Path(args.pop(0))
            if flag == "--doc":
                doc = value
            else:
                root = value
        else:
            print(f"check_requirements: unknown option {flag}", file=sys.stderr)
            return 2
    doc = doc or root / "docs" / "REQUIREMENTS.md"

    problems = check(root, doc)
    if problems:
        print(f"check_requirements: {len(problems)} problem(s)", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print(f"\n  {doc} follows the build, never the other way round.", file=sys.stderr)
        return 1
    print(f"check_requirements: OK - {len(FACTS)} version(s) match the build")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
