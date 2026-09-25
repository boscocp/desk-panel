#!/usr/bin/env python3
"""Fail if .github/workflows/ci.yml and the Makefile have drifted apart.

TT.9's actual subject. Two files claim to run the same suites -- `make check`
on a desk, `ci.yml` on a push -- and nothing made them agree, so they already
had: the workflow was a `workflow_dispatch` skeleton written at bootstrap,
and every suite added since arrived in the Makefile alone. Drift in this
direction is the expensive one, because CI stays green while running less
than it says it does.

So this reads both files and asserts, for each of the three layers that need
no phone, that the command CI runs is **the same string** the Makefile runs:

  job `server`   ==  make test-server
  job `web`      ==  make test-web
  job `android`  ==  make test-android, and make apk

The one difference allowed is the `$(DC)` prefix -- the Makefile runs Gradle
inside the toolchain container to keep the developer's Windows host clean
(ADR 0003), and a CI runner is disposable, so the container is dropped there
and nothing else is. Stripping exactly that prefix and requiring equality of
what remains is what makes this check sharp rather than decorative.

**The three suites, not `make check` entire.** `check` also runs this repo's
guard scripts, and CI does not: that gap is T7.8's, which adds the lint job
and must not be pre-empted here. So a desk is stricter than CI today, and
LAYERS is where that stops being true the moment T7.8 lands.

It also asserts the three things TT.9 says CI must never do:

  - run `connectedAndroidTest`, which needs the physical phone
  - set RUN_CONTRACT_TESTS, which would put five live APIs in the build path
  - stay on `workflow_dispatch` only, which is a workflow nobody runs

**No PyYAML.** This project takes no dependencies, and CI installing one to
check that CI installs none would be its own joke. The reader below handles
the subset of YAML this workflow is written in and **fails loudly on anything
it does not recognise**: a file it cannot parse is a failure, never a pass.
That is the rule this repository keeps relearning -- a check that cannot fail
is worse than no check -- and `--self-test` proves each rule can.

Exit codes: 0 clean, 1 drift found, 2 usage error.

Usage:
  python scripts/check_workflow.py [--workflow PATH] [--makefile PATH]
  python scripts/check_workflow.py --self-test
"""

import re
import sys
from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml")
MAKEFILE = Path("Makefile")

# job name -> the Makefile targets whose recipes it must reproduce, in order.
LAYERS = {
    "server": ["test-server"],
    "web": ["test-web"],
    "android": ["test-android", "build apk"],
}

# The container prefix. `$(DC) ./gradlew test` on a desk is `./gradlew test`
# on a runner; the wrapper pins the same Gradle either way, and the root
# `gradlew` shim means both spell the path identically.
CONTAINER_PREFIX = "$(DC) "

REQUIRED_TRIGGERS = ("push", "pull_request")

FORBIDDEN = (
    ("connectedAndroidTest", "connectedAndroidTest needs the physical phone (TT.9 step 5)"),
    ("RUN_CONTRACT_TESTS", "CI must never set RUN_CONTRACT_TESTS - the contract tests "
                           "call five live APIs (TT.9 step 6)"),
)


def normalise(command: str) -> str:
    """A shell command with its whitespace collapsed, for comparison."""
    return " ".join(command.split())


def makefile_recipes(text: str) -> dict[str, list[str]]:
    """`{target: [command, ...]}` for every target with a recipe.

    Recipe lines are the tab-indented ones under `target:`, which is Make's
    own rule and needs no more parsing than that. Comments and blank lines
    are dropped; a line continued with a backslash is not, because none of
    the targets this checks uses one and quietly mis-joining it would be a
    way to pass by accident.
    """
    recipes: dict[str, list[str]] = {}
    target = None
    for line in text.splitlines():
        if line.startswith("\t"):
            if target is not None:
                body = line.strip()
                if body and not body.startswith("#"):
                    recipes[target].append(normalise(body))
            continue
        match = re.match(r"^([A-Za-z0-9_. -]+):(?!=)", line)
        if match:
            target = match.group(1).strip()
            recipes.setdefault(target, [])
        elif line.strip() and not line.startswith(" "):
            target = None
    return recipes


def strip_comments(text: str) -> str:
    """`text` with YAML comments removed.

    A `#` opens a comment at the start of a line or after whitespace, which is
    YAML's own rule; a `#` inside a word (a colour, a fragment) is left alone.
    """
    return re.sub(r"(?m)(?:^|(?<=\s))#.*$", "", text)


def _unwrap(value: str) -> str:
    """A YAML-quoted scalar with its quotes removed, and nothing else touched.

    `value.strip("'\"")` is the obvious version and it is wrong: `run: node
    --test "web/test/**/*.test.js"` ends in a quote that belongs to the
    command, and stripping characters from each end independently takes it
    off -- the shell then runs an unterminated string. Caught by --self-test
    on its first run, which is the argument for having written the self-test
    before trusting the reader.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


class WorkflowError(Exception):
    """The workflow is not in the shape this reader understands."""


def workflow_jobs(text: str) -> dict[str, list[str]]:
    """`{job: [run command, ...]}`, read without a YAML library.

    Indentation-driven, and deliberately strict: `jobs:` at column 0, a job
    name two spaces in, and `- run:` or `run:` anywhere below it belongs to
    the job currently open. Both the inline form and the `|` block scalar are
    read, because a multi-line run step is the obvious next edit and a reader
    that silently skipped it would report a job with no commands as matching
    a Makefile target with none either.

    Raises WorkflowError rather than returning `{}` for a file it cannot make
    sense of: an empty result must never be mistaken for agreement.
    """
    lines = text.splitlines()
    jobs: dict[str, list[str]] = {}
    in_jobs = False
    job = None
    block: list[str] | None = None
    block_indent = 0

    for raw in lines:
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))

        # Inside a `run: |` block scalar: everything indented past the step
        # keeps belonging to it.
        if block is not None:
            if stripped and indent > block_indent:
                block.append(stripped)
                continue
            jobs[job].append(normalise(" && ".join(block)))
            block = None

        if not stripped or stripped.startswith("#"):
            continue

        if indent == 0:
            in_jobs = stripped == "jobs:"
            job = None
            continue
        if not in_jobs:
            continue

        if indent == 2 and stripped.endswith(":"):
            job = stripped[:-1].strip()
            jobs.setdefault(job, [])
            continue
        if job is None:
            continue

        match = re.match(r"^-?\s*run:\s*(.*)$", stripped)
        if match:
            value = match.group(1).strip()
            if value in ("|", ">", "|-", ">-"):
                block, block_indent = [], indent
            elif value:
                jobs[job].append(normalise(_unwrap(value)))

    if block is not None:
        jobs[job].append(normalise(" && ".join(block)))

    if not jobs:
        raise WorkflowError("no jobs found - the file is not the workflow this reader knows")
    if not any(jobs.values()):
        raise WorkflowError("jobs found but not one `run:` step - the reader is looking "
                            "at a shape it does not understand, which is not agreement")
    return jobs


def workflow_triggers(text: str) -> list[str]:
    """The event names under `on:`.

    `on:` is at column 0 and its events are the two-space keys under it. A
    workflow that never runs is the failure mode this catches: the skeleton
    this file replaces was `workflow_dispatch` only, which is green forever.
    """
    triggers = []
    in_on = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            in_on = stripped in ("on:", '"on":', "'on':")
            continue
        if in_on and indent == 2:
            triggers.append(stripped.rstrip(":").strip())
    return triggers


def check(workflow_text: str, makefile_text: str) -> list[str]:
    """Every disagreement between the two files, as messages."""
    problems: list[str] = []

    try:
        jobs = workflow_jobs(workflow_text)
    except WorkflowError as exc:
        return [f"ci.yml: {exc}"]

    recipes = makefile_recipes(makefile_text)

    triggers = workflow_triggers(workflow_text)
    for event in REQUIRED_TRIGGERS:
        if event not in triggers:
            problems.append(
                f"ci.yml: `on:` has no `{event}` - triggers are {triggers or 'none'}. "
                "A workflow that only runs on dispatch runs when someone remembers to.")

    # Against the code, not the comments. The workflow *explains* why
    # connectedAndroidTest is absent, and a scan of the raw text reads that
    # explanation as the violation it is documenting -- which would leave only
    # two ways out, both bad: delete the comment, or make the rule toothless.
    code = strip_comments(workflow_text)
    for pattern, why in FORBIDDEN:
        if pattern in code:
            problems.append(f"ci.yml: runs or sets {pattern} - {why}")

    # A `working-directory:` is what turns the comparison above into a lie:
    # `./gradlew test` run from android/ and `./gradlew test` run from the
    # root are the same string and not the same command. They happen to agree
    # today, via the root `gradlew` shim -- and "happen to" is the part this
    # rule removes. The Makefile runs everything from the root; so does CI.
    if re.search(r"^\s*working-directory:", code, re.M):
        problems.append(
            "ci.yml: a step sets `working-directory:`, so a command matching the "
            "Makefile's text no longer means it runs the same thing. The Makefile "
            "runs from the repository root and `./gradlew` there is the shim into "
            "android/ - use it.")

    for job, targets in LAYERS.items():
        if job not in jobs:
            problems.append(f"ci.yml: no `{job}` job - CI does not run that layer at all")
            continue

        expected = []
        for target in targets:
            if target not in recipes:
                problems.append(
                    f"Makefile: no `{target}` target, which the `{job}` job is checked against")
                continue
            expected += [
                command[len(CONTAINER_PREFIX):] if command.startswith(CONTAINER_PREFIX)
                else command
                for command in recipes[target]
            ]

        actual = jobs[job]
        for command in expected:
            if command not in actual:
                problems.append(
                    f"ci.yml: the `{job}` job does not run {command!r}, which "
                    f"`make {targets[0]}` does. CI is green while running less than "
                    "the Makefile.")
        for command in actual:
            if command not in expected:
                problems.append(
                    f"ci.yml: the `{job}` job runs {command!r}, which no Makefile target "
                    "does. Put it in the Makefile so a desk runs it too.")

    return problems


# ---------------------------------------------------------------------------
# --self-test: the rules, proved able to fail, on any box, with no repository.
#
# after_update.py established this pattern and wave 22 found the gap in it:
# nothing in `make check` ran it, so its own self-test had been red on Linux
# for two waves without anyone noticing. `make lint-workflow` runs this one,
# so that cannot happen here. See tasks/TT.12.
# ---------------------------------------------------------------------------

GOOD_MAKEFILE = """\
DC := docker compose -f docker/compose.yml run --rm build

test-server:
\tpython -m unittest discover -s server/tests -t .

test-web:
\tnode --test "web/test/**/*.test.js"

test-android:
\t$(DC) ./gradlew test

build apk:
\t$(DC) ./gradlew assembleDebug
"""

GOOD_WORKFLOW = """\
name: ci

on:
  push:
  pull_request:

jobs:
  server:
    steps:
      - run: python -m unittest discover -s server/tests -t .
  web:
    steps:
      - run: node --test "web/test/**/*.test.js"
  android:
    steps:
      - run: ./gradlew test
      - run: ./gradlew assembleDebug
"""


def self_test_cases():
    """`(name, workflow, makefile, expect_clean)`, each aimed at one rule."""
    return [
        ("the pair that agrees is clean", GOOD_WORKFLOW, GOOD_MAKEFILE, True),
        ("a dispatch-only workflow is caught",
         GOOD_WORKFLOW.replace("on:\n  push:\n  pull_request:", "on:\n  workflow_dispatch:"),
         GOOD_MAKEFILE, False),
        ("a missing job is caught",
         GOOD_WORKFLOW.replace("  web:\n    steps:\n"
                               '      - run: node --test "web/test/**/*.test.js"\n', ""),
         GOOD_MAKEFILE, False),
        ("a command CI stopped running is caught",
         GOOD_WORKFLOW.replace("      - run: ./gradlew assembleDebug\n", ""),
         GOOD_MAKEFILE, False),
        ("a command only CI runs is caught",
         GOOD_WORKFLOW.replace("      - run: ./gradlew test",
                               "      - run: ./gradlew test\n      - run: ./gradlew lint"),
         GOOD_MAKEFILE, False),
        ("a suite the Makefile changed under CI is caught",
         GOOD_WORKFLOW,
         GOOD_MAKEFILE.replace("-s server/tests -t .", "-s server/tests -t . -v"), False),
        ("connectedAndroidTest is caught",
         GOOD_WORKFLOW.replace("      - run: ./gradlew test",
                               "      - run: ./gradlew test\n"
                               "      - run: ./gradlew connectedAndroidTest"),
         GOOD_MAKEFILE, False),
        ("RUN_CONTRACT_TESTS is caught",
         GOOD_WORKFLOW.replace("  server:\n    steps:",
                               "  server:\n    env:\n      RUN_CONTRACT_TESTS: 1\n    steps:"),
         GOOD_MAKEFILE, False),
        ("a workflow this reader cannot parse is a failure, not a pass",
         "name: ci\non: [push]\njobs: {server: {steps: [{run: true}]}}\n",
         GOOD_MAKEFILE, False),
        ("a block scalar is read, not skipped",
         GOOD_WORKFLOW.replace("      - run: ./gradlew test",
                               "      - run: |\n          ./gradlew test"),
         GOOD_MAKEFILE, True),
        ("a Makefile target that vanished is caught",
         GOOD_WORKFLOW, GOOD_MAKEFILE.replace("test-web:", "test-browser:"), False),
        ("a forbidden word inside a comment is not a violation",
         GOOD_WORKFLOW.replace("jobs:",
                               "# connectedAndroidTest is deliberately absent, and\n"
                               "# RUN_CONTRACT_TESTS is deliberately unset.\njobs:"),
         GOOD_MAKEFILE, True),
        ("a working-directory is caught",
         GOOD_WORKFLOW.replace("  android:\n    steps:",
                               "  android:\n    defaults:\n      run:\n"
                               "        working-directory: android\n    steps:"),
         GOOD_MAKEFILE, False),
    ]


def self_test() -> int:
    failures = 0
    for name, workflow, makefile, expect_clean in self_test_cases():
        problems = check(workflow, makefile)
        ok = (not problems) if expect_clean else bool(problems)
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1
            for problem in problems:
                print(f"        {problem}")
            if expect_clean is False:
                print("        (expected a complaint and got none)")
    if failures:
        print(f"\ncheck_workflow --self-test: FAIL - {failures} rules do not hold")
        return 1
    print(f"\ncheck_workflow --self-test: OK - {len(self_test_cases())} rules")
    return 0


def main(argv: list[str]) -> int:
    workflow, makefile = WORKFLOW, MAKEFILE
    args = argv[1:]
    while args:
        flag = args.pop(0)
        if flag == "--self-test":
            return self_test()
        if not args:
            print(f"check_workflow: {flag} needs a value", file=sys.stderr)
            return 2
        value = args.pop(0)
        if flag == "--workflow":
            workflow = Path(value)
        elif flag == "--makefile":
            makefile = Path(value)
        else:
            print(f"check_workflow: unknown option {flag}", file=sys.stderr)
            return 2

    for path in (workflow, makefile):
        if not path.is_file():
            print(f"check_workflow: no such file: {path}", file=sys.stderr)
            return 2

    problems = check(workflow.read_text(encoding="utf-8"),
                     makefile.read_text(encoding="utf-8"))
    for problem in problems:
        print(f"  {problem}")

    if problems:
        print(f"\ncheck_workflow: FAIL - {len(problems)} disagreements between "
              f"{workflow} and {makefile}")
        return 1
    print(f"check_workflow: OK - {len(LAYERS)} jobs run what the Makefile runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
