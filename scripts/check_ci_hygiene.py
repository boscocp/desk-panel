#!/usr/bin/env python3
"""Assert the properties of `.github/` that a reader cannot see at a glance.

T7.8's deliverable. Six rules, and every one of them is something that looks
fine in a diff and is wrong in a way nothing else notices:

  1. every workflow declares `permissions:`, and none grants `write-all`.
     The default token is read/write across the repository unless the workflow
     says otherwise, and "otherwise" is invisible by being absent.
  2. every `uses:` is pinned to a 40-character commit SHA, with the version in
     a trailing comment. A tag is mutable; a compromised popular action runs
     with whatever the token allows.
  3. every workflow declares `concurrency:`. Three pushes to a branch should
     leave one run.
  4. `.github/dependabot.yml` names exactly the ecosystems this repo has --
     it fails on a missing one and on an invented one.
  5. every `scripts/check_*.py` is run by a workflow *and* named in the
     Makefile. A guard nobody runs is a rule nobody enforces -- which is what
     TT.12 found for the self-tests, one layer down.
  6. no `continue-on-error:` and no `if:` on a step, anywhere. Wave 23 found
     both in ci.yml turning a red suite into a green check, and the rule there
     is the rule here: a check that tries to decide which conditions are
     harmless will one day decide wrongly and say nothing. There is nothing
     conditional in this repo's workflows to express.

Rule 2 is stricter than T7.8's own wording, which exempted `actions/*` and
`github/*`. The exemption was dropped rather than implemented: this repo pins
those too, GitHub's hardening guide asks for it, and an exemption is a decision
the checker has to make correctly forever.

No PyYAML. This project takes no dependencies (server/CLAUDE.md), and the
reader below **fails loudly on a shape it cannot parse** rather than returning
an empty result that reads as agreement -- the same rule check_workflow.py
follows and for the same reason.

Exit codes: 0 clean, 1 a violation, 2 usage error.

Usage:
  python scripts/check_ci_hygiene.py [repo_root]
  python scripts/check_ci_hygiene.py --self-test   # the rules against fixtures
"""

import contextlib
import io
import re
import sys
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)")
# A step-level `if:`. `if-no-files-found:` is a different key that starts with
# the same three characters, and reading it as a condition is how a checker
# reports a problem that is not there.
IF_RE = re.compile(r"^\s*-?\s*if:\s")
CONTINUE_RE = re.compile(r"^\s*continue-on-error:\s*(\S+)")
TOP_LEVEL_RE = re.compile(r"^([a-z-]+):")

# What a Dependabot ecosystem name means in terms of files on disk. Presence is
# decided by a dependency actually being declared, never by a file merely
# existing: `pyproject.toml` here configures ruff and declares nothing, and a
# rule keyed on the filename would demand a `pip` block this repo must not have.
ECOSYSTEMS = {
    "github-actions": lambda root: any((root / ".github" / "workflows").glob("*.yml")),
    "gradle": lambda root: any(root.rglob("build.gradle.kts")) or any(root.rglob("build.gradle")),
    "docker": lambda root: any(root.rglob("Dockerfile")),
    "npm": lambda root: any(p for p in root.rglob("package.json") if ".git" not in p.parts),
    "pip": lambda root: _declares_python_dependencies(root),
}


def _declares_python_dependencies(root):
    """True only when something actually pins a Python package."""
    if any(root.glob("requirements*.txt")) or any(root.glob("*/requirements*.txt")):
        return True
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    text = pyproject.read_text(encoding="utf-8")
    return bool(re.search(r"^\s*dependencies\s*=", text, re.M))


def workflow_files(root):
    directory = root / ".github" / "workflows"
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix in {".yml", ".yaml"})


def top_level_keys(text):
    """The keys at column zero. Comments and blanks are not keys."""
    keys = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        m = TOP_LEVEL_RE.match(line)
        if m:
            keys.append(m.group(1))
    return keys


def strip_comments(text):
    """Drop whole-line comments so a rule never fires on prose explaining it.

    `check_workflow.py` learned this the hard way: `connectedAndroidTest`
    matched inside the comment saying why it is deliberately absent, and the
    alternatives were deleting the comment or gutting the rule.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def check_workflow(path, text):
    problems = []
    name = path.name
    body = strip_comments(text)
    keys = top_level_keys(body)

    if "permissions" not in keys:
        problems.append(f"{name}: no top-level `permissions:` -- the default token is read/write")
    if re.search(r"permissions:\s*write-all", body):
        problems.append(f"{name}: grants `write-all`")
    if "concurrency" not in keys:
        problems.append(f"{name}: no `concurrency:` -- superseded runs are never cancelled")

    for number, line in enumerate(body.splitlines(), 1):
        m = USES_RE.match(line)
        if m:
            ref = m.group(1)
            if "@" not in ref:
                problems.append(f"{name}:{number}: `uses: {ref}` has no ref at all")
            elif not SHA_RE.match(ref.split("@", 1)[1]):
                problems.append(f"{name}:{number}: `{ref}` is pinned to a tag, not a 40-character SHA")
            elif "#" not in line:
                problems.append(f"{name}:{number}: `{ref}` is pinned with no version in a trailing comment")
        if IF_RE.match(line):
            problems.append(
                f"{name}:{number}: `if:` is banned -- a step that may not run is a check that may not check"
            )
        m = CONTINUE_RE.match(line)
        if m:
            problems.append(f"{name}:{number}: `continue-on-error: {m.group(1)}` turns a red step into a green check")
    return problems


def check_dependabot(root):
    path = root / ".github" / "dependabot.yml"
    if not path.is_file():
        return [f"{path} does not exist"]
    body = strip_comments(path.read_text(encoding="utf-8"))
    declared = set(re.findall(r"^\s*-?\s*package-ecosystem:\s*[\"']?([a-z-]+)", body, re.M))
    if not declared:
        # Failing loudly on a shape this reader cannot parse, rather than
        # reporting "no invented ecosystems" about a file it did not understand.
        return ["dependabot.yml: no `package-ecosystem:` found -- unreadable, not empty"]
    present = {name for name, has in ECOSYSTEMS.items() if has(root)}
    problems = []
    for name in sorted(present - declared):
        problems.append(f"dependabot.yml: the repo has {name} and the config does not name it")
    for name in sorted(declared - present):
        problems.append(f"dependabot.yml: names {name}, which this repo does not have")
    return problems


def check_guards_are_run(root, workflows):
    """Every `scripts/check_*.py` is run by a workflow and named in the Makefile.

    Found by glob, deliberately: T7.4 and T7.5 each land another guard, and the
    point is that they arrive already wired rather than waiting for somebody to
    remember two lists.
    """
    guards = sorted(p.name for p in (root / "scripts").glob("check_*.py"))
    workflow_text = "\n".join(strip_comments(p.read_text(encoding="utf-8")) for p in workflows)
    makefile = root / "Makefile"
    makefile_text = makefile.read_text(encoding="utf-8") if makefile.is_file() else ""
    problems = []
    for guard in guards:
        if guard not in workflow_text:
            problems.append(f"scripts/{guard}: no workflow runs it")
        if guard not in makefile_text:
            problems.append(f"scripts/{guard}: the Makefile never runs it, so it is CI-only")
    return problems


def check_pr_template(root, workflows):
    """A contributor is never asked to confirm something no job verifies.

    T7.6 owns the template's wording. What belongs here is that any command it
    names in backticks is a command some workflow or the Makefile actually
    runs -- a rule that does nothing until that file exists, and is true the
    day it does.
    """
    path = root / ".github" / "PULL_REQUEST_TEMPLATE.md"
    if not path.is_file():
        return []
    ran = "\n".join(p.read_text(encoding="utf-8") for p in workflows)
    makefile = root / "Makefile"
    ran += makefile.read_text(encoding="utf-8") if makefile.is_file() else ""
    problems = []
    for command in re.findall(r"`((?:make|python|node|\./gradlew)\s[^`]+)`", path.read_text(encoding="utf-8")):
        if command.strip() not in ran:
            problems.append(f"PULL_REQUEST_TEMPLATE.md: asks for `{command}`, which nothing runs")
    return problems


def run(root):
    workflows = workflow_files(root)
    if not workflows:
        print(f"check_ci_hygiene: no workflows under {root / '.github' / 'workflows'}", file=sys.stderr)
        return 1
    problems = []
    for path in workflows:
        problems += check_workflow(path, path.read_text(encoding="utf-8"))
    problems += check_dependabot(root)
    problems += check_guards_are_run(root, workflows)
    problems += check_pr_template(root, workflows)

    for problem in problems:
        print(f"  {problem}")
    if problems:
        print(f"\ncheck_ci_hygiene: FAIL - {len(problems)} problems")
        return 1
    print(f"check_ci_hygiene: OK - {len(workflows)} workflows, {len(ECOSYSTEMS)} ecosystems considered")
    return 0


# --------------------------------------------------------------------------
# --self-test: every rule, against a fixture that violates exactly one of them.
# An assertion nobody has seen fail is not an assertion.
# --------------------------------------------------------------------------

PINNED = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
GUARD_STEP = "      - run: python scripts/check_acceptance.py"

CLEAN = """\
name: x
on:
  push:
permissions:
  contents: read
concurrency:
  group: x-${{ github.ref }}
  cancel-in-progress: true
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - uses: {pinned}
{guard}
"""


CLEAN = CLEAN.format(pinned=PINNED, guard=GUARD_STEP)


def _one(text, name="x.yml"):
    return check_workflow(Path(name), text)


def self_test_cases():
    """One fixture, and a mutation of it per rule. Each mutation must be caught."""
    return [
        ("the clean fixture is clean", lambda: _one(CLEAN) == []),
        (
            "a missing permissions block is caught",
            lambda: _caught("permissions", CLEAN.replace("permissions:\n  contents: read\n", "")),
        ),
        (
            "write-all is caught",
            lambda: _caught("write-all", CLEAN.replace("permissions:\n  contents: read", "permissions: write-all")),
        ),
        (
            "a missing concurrency block is caught",
            lambda: _caught("concurrency", re.sub(r"concurrency:\n(?:  .*\n)+", "", CLEAN)),
        ),
        (
            "an action pinned to a tag is caught",
            lambda: _caught("not a 40-character SHA", CLEAN.replace(PINNED, "actions/checkout@v4")),
        ),
        (
            "a first-party action gets no exemption",
            lambda: _caught("not a 40-character SHA", CLEAN.replace(PINNED, "github/codeql-action/init@v4")),
        ),
        (
            "a SHA with no version comment is caught",
            lambda: _caught("no version in a trailing comment", CLEAN.replace(" # v7.0.1", "")),
        ),
        (
            "a uses with no ref at all is caught",
            lambda: _caught("no ref at all", CLEAN.replace(PINNED, "actions/checkout")),
        ),
        (
            "continue-on-error is caught",
            lambda: _caught(
                "continue-on-error",
                CLEAN.replace(GUARD_STEP, GUARD_STEP + "\n        continue-on-error: true"),
            ),
        ),
        (
            "a step-level if is caught",
            lambda: _caught(
                "`if:` is banned",
                CLEAN.replace(GUARD_STEP, "      - if: github.event_name == 'push'\n        run: true"),
            ),
        ),
        (
            "`if-no-files-found:` is not an `if:`",
            lambda: _one(CLEAN.replace(GUARD_STEP, GUARD_STEP + "\n        with:\n          if-no-files-found: error"))
            == [],
        ),
        (
            "a violation inside a comment is not a violation",
            lambda: _one(CLEAN.replace("name: x", "# never write `continue-on-error: true` here\nname: x")) == [],
        ),
        (
            "an ecosystem the repo has and the config omits is caught",
            lambda: any("does not name it" in p for p in _dependabot_case(["github-actions"])),
        ),
        (
            "an invented ecosystem is caught",
            lambda: any(
                "which this repo does not have" in p
                for p in _dependabot_case(["github-actions", "gradle", "docker", "npm"])
            ),
        ),
        (
            "a dependabot.yml this reader cannot parse is a failure, not a pass",
            lambda: any("unreadable" in p for p in _dependabot_case([])),
        ),
        (
            # Output swallowed: a rule's own report in the middle of the case
            # list reads as a failure of the case above it.
            "the repo itself is clean",
            lambda: _quiet(lambda: run(Path(__file__).resolve().parent.parent)) == 0,
        ),
    ]


def _caught(fragment, text):
    """The mutated fixture produces a problem mentioning `fragment`."""
    return any(fragment in problem for problem in _one(text))


def _quiet(call):
    with contextlib.redirect_stdout(io.StringIO()):
        return call()


def _dependabot_case(ecosystems):
    """check_dependabot against a throwaway tree declaring `ecosystems`."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "x.yml").write_text(CLEAN, encoding="utf-8")
        (root / "android").mkdir()
        (root / "android" / "build.gradle.kts").write_text("// gradle\n", encoding="utf-8")
        (root / "docker").mkdir()
        (root / "docker" / "Dockerfile").write_text("FROM x\n", encoding="utf-8")
        body = "version: 2\nupdates:\n" + "".join(
            f'  - package-ecosystem: {name}\n    directory: "/"\n' for name in ecosystems
        )
        (root / ".github" / "dependabot.yml").write_text(body, encoding="utf-8")
        return check_dependabot(root)


def self_test(stream=sys.stdout):
    failures = 0
    cases = self_test_cases()
    for name, check in cases:
        try:
            ok = bool(check())
        except Exception as exc:  # a raising case is a failing case
            ok, name = False, f"{name}  [{type(exc).__name__}: {exc}]"
        print(f"{'ok  ' if ok else 'FAIL'}  {name}", file=stream)
        failures += 0 if ok else 1
    print(f"\ncheck_ci_hygiene --self-test: {len(cases) - failures}/{len(cases)} cases passed", file=stream)
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv[1:]:
        return self_test()
    positional = [a for a in argv[1:] if not a.startswith("-")]
    if len(positional) > 1:
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    return run(Path(positional[0]) if positional else Path("."))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
