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
     it fails on a missing one, on an invented one, and on one whose
     `directory:` holds none of that ecosystem's files. A `gradle` entry
     pointing at `/` instead of `/android` updates nothing and reads as
     coverage, which is the failure the rule is for.
  5. every `scripts/check_*.py` is run by the Makefile, and every one that
     `make check` reaches is also run by a workflow. A guard nobody runs is a
     rule nobody enforces -- which is what TT.12 found for the self-tests, one
     layer down. The two halves are not the same rule: `check_branch_base.py`
     belongs to `make wave-start` and is meaningless on a runner, whose
     checkout is a pull request branch by construction.
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
    # Whatever this script reads as a workflow, `.yaml` included -- otherwise a
    # repo spelling them `.yaml` is told its dependabot config names an
    # ecosystem it does not have, about workflows this script is checking.
    "github-actions": lambda root: bool(workflow_files(root)),
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
    """Blank out whole-line comments so a rule never fires on prose explaining it.

    `check_workflow.py` learned this the hard way: `connectedAndroidTest`
    matched inside the comment saying why it is deliberately absent, and the
    alternatives were deleting the comment or gutting the rule.

    Blanked rather than dropped, so line N of the result is line N of the file.
    An earlier cut dropped them, and every `{name}:{number}` this script printed
    pointed at the wrong line -- in `lint.yml`, which is half comment, by 26.
    A checker that names the wrong line is one a reader stops believing.
    """
    return "\n".join("" if line.lstrip().startswith("#") else line for line in text.splitlines())


# A Makefile recipe line: tab-indented, not a comment, and not `help:` printing
# the name of a target. See makefile_commands().
ECHO_RE = re.compile(r"^\t\s*[@-]*echo\b")


def makefile_commands(text):
    """The lines of a Makefile that actually run something.

    Rule 5 asks whether the Makefile *runs* a guard, and a substring search over
    the whole file cannot tell that from a guard named in a comment or printed
    by `help:`. Both read as wired while nothing invokes them, which is exactly
    the state TT.12 found one layer down.
    """
    lines = []
    for line in text.splitlines():
        if not line.startswith("\t"):
            continue
        stripped = line.lstrip("\t").lstrip("@-").lstrip()
        if stripped.startswith("#"):
            continue
        if ECHO_RE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines)


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


# Where each ecosystem's marker has to sit for a `directory:` to be pointing at
# anything. A name that is right and a directory that is wrong updates nothing
# and still reads as coverage, which is rule 4's whole subject. Found by review.
DIRECTORY_MARKERS = {
    "github-actions": [".github/workflows"],
    "gradle": ["build.gradle.kts", "build.gradle", "settings.gradle.kts", "settings.gradle"],
    "docker": ["Dockerfile"],
    "npm": ["package.json"],
    "pip": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"],
}


def declared_entries(body):
    """(ecosystem, directory) per `updates:` entry, directory None when absent.

    A flat scan, not a parser: `package-ecosystem:` opens an entry and the next
    `directory:` before the following one belongs to it.
    """
    entries = []
    for line in body.splitlines():
        eco = re.match(r"^\s*-?\s*package-ecosystem:\s*[\"']?([a-z-]+)", line)
        if eco:
            entries.append([eco.group(1), None])
            continue
        directory = re.match(r"^\s*directory:\s*[\"']?([^\"'\s]+)", line)
        if directory and entries and entries[-1][1] is None:
            entries[-1][1] = directory.group(1)
    return [tuple(entry) for entry in entries]


def misdirected(entries, root):
    """Entries whose `directory:` holds none of that ecosystem's markers."""
    problems = []
    for ecosystem, directory in entries:
        markers = DIRECTORY_MARKERS.get(ecosystem)
        if markers is None or directory is None:
            continue
        where = root / directory.lstrip("/")
        if not any((where / marker).exists() for marker in markers):
            problems.append(
                f"dependabot.yml: {ecosystem} points at {directory}, which holds no "
                f"{' or '.join(markers[:2])} -- it would update nothing"
            )
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
    return problems + misdirected(declared_entries(body), root)


def check_reachable(makefile_text):
    """The recipe text of every target `check:` depends on, plus its own.

    One level of dependency, which is all this Makefile has. A guard invoked
    from a target nothing depends on is exactly the state TT.12 found.
    """
    deps = re.search(r"^check:(.*)$", makefile_text, re.M)
    targets = set(deps.group(1).split()) if deps else set()
    recipes = []
    for name in sorted(targets):
        body = re.search(rf"^{re.escape(name)}:.*\n((?:[\t#].*\n|\n)*)", makefile_text, re.M)
        if body:
            recipes.append(makefile_commands(body.group(1)))
    return "\n".join(recipes)


def check_guards_are_run(root, workflows):
    """Every `scripts/check_*.py` is wired, and the two halves differ.

    Run by the Makefile: always. A guard that only a workflow runs cannot be
    failed before pushing, which is half the value of having it. "Run by" is a
    search over recipe lines, not the file -- a guard named in a comment or
    printed by `help:` is named, not run.

    Run by a workflow: only for the guards `make check` reaches. The others are
    reached by a target with a different job -- `make wave-start` runs
    `check_branch_base.py` against `origin/main`, which on a runner compares a
    pull request branch against the base it was opened from and is green by
    construction. A rule that demanded it would be asking for a green tick that
    means nothing.

    Found by glob, deliberately: T7.4 and T7.5 each land another guard, and the
    point is that they arrive already wired rather than waiting for somebody to
    remember two lists.
    """
    guards = sorted(p.name for p in (root / "scripts").glob("check_*.py"))
    workflow_text = "\n".join(strip_comments(p.read_text(encoding="utf-8")) for p in workflows)
    makefile = root / "Makefile"
    makefile_text = makefile.read_text(encoding="utf-8") if makefile.is_file() else ""
    commands = makefile_commands(makefile_text)
    reachable = check_reachable(makefile_text)
    problems = []
    for guard in guards:
        if guard not in commands:
            problems.append(f"scripts/{guard}: the Makefile never runs it, so it is CI-only")
        elif guard in reachable and guard not in workflow_text:
            problems.append(f"scripts/{guard}: `make check` runs it and no workflow does")
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
    makefile_text = makefile.read_text(encoding="utf-8") if makefile.is_file() else ""
    ran += makefile_text
    # A Makefile declares `check:`, never the string `make check`, so a template
    # asking for this repo's own headline command would otherwise be reported as
    # asking for something nothing runs. Every declared target counts as its own
    # invocation; a `make` of a target that does not exist still fails.
    ran += "\n" + "\n".join(
        f"make {name}"
        for line in makefile_text.splitlines()
        if not line.startswith("\t")
        for match in [re.match(r"^([A-Za-z0-9_][A-Za-z0-9_. -]*):(?!=)", line)]
        if match
        for name in match.group(1).split()
    )
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
            "a guard `make check` reaches and no workflow runs is caught",
            lambda: any(
                "no workflow does" in p
                for p in _guard_case("check: lint-x\n\nlint-x:\n\tpython scripts/check_x.py\n", workflow_runs=False)
            ),
        ),
        (
            "a guard reached only by another target needs no workflow",
            lambda: _guard_case(
                "check: lint-y\n\nlint-y:\n\ttrue\n\nwave-start:\n\tpython scripts/check_x.py\n",
                workflow_runs=False,
            ) == [],
        ),
        (
            "a guard no target runs at all is caught",
            lambda: any("CI-only" in p for p in _guard_case("check: lint-y\n\nlint-y:\n\ttrue\n", workflow_runs=True)),
        ),
        (
            # `help:` prints the name of every target and, in this repo, what
            # each one runs. Named is not run.
            "a guard only `help:` prints is not a guard the Makefile runs",
            lambda: any(
                "CI-only" in p
                for p in _guard_case(
                    'help:\n\t@echo "lint-x  runs scripts/check_x.py"\n\ncheck: lint-y\n\nlint-y:\n\ttrue\n',
                    workflow_runs=True,
                )
            ),
        ),
        (
            "a guard only a comment names is not a guard the Makefile runs",
            lambda: any(
                "CI-only" in p
                for p in _guard_case(
                    "# one day, scripts/check_x.py\ncheck: lint-y\n\nlint-y:\n\ttrue\n",
                    workflow_runs=True,
                )
            ),
        ),
        (
            "a violation is reported at its line in the file, not in the comment-stripped body",
            _line_number_case,
        ),
        (
            "a template asking for a Makefile target this repo has is not a problem",
            lambda: _pr_template_case("Run `make check` before opening this.") == [],
        ),
        (
            "a template asking for a target that does not exist is caught",
            lambda: any("which nothing runs" in p for p in _pr_template_case("Run `make nonesuch`.")),
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
            "an entry pointing at a directory with none of its files is caught",
            lambda: any("would update nothing" in p for p in _dependabot_case(
                ["github-actions", "gradle", "docker"], gradle_directory="/")),
        ),
        (
            "an entry pointing at the right directory is not",
            lambda: _dependabot_case(["github-actions", "gradle", "docker"]) == [],
        ),
        (
            "directory and ecosystem are paired by order, not by guessing",
            lambda: declared_entries(
                "updates:\n"
                "  - package-ecosystem: gradle\n    directory: \"/android\"\n"
                "  - package-ecosystem: docker\n    directory: \"/docker\"\n"
            ) == [("gradle", "/android"), ("docker", "/docker")],
        ),
        (
            "an entry with no directory is not invented one",
            lambda: declared_entries("  - package-ecosystem: gradle\n") == [("gradle", None)],
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


def _line_number_case():
    """A violation under a comment block is reported at its line in the file."""
    text = "# one\n# two\n# three\n" + CLEAN.replace(PINNED, "actions/checkout@v4")
    expected = next(n for n, line in enumerate(text.splitlines(), 1) if "checkout@v4" in line)
    return any(problem.startswith(f"x.yml:{expected}:") for problem in _one(text))


def _quiet(call):
    with contextlib.redirect_stdout(io.StringIO()):
        return call()


def _guard_case(makefile, workflow_runs):
    """check_guards_are_run against a throwaway tree holding one guard."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "scripts" / "check_x.py").write_text("# a guard\n", encoding="utf-8")
        (root / "Makefile").write_text(makefile, encoding="utf-8")
        (root / ".github" / "workflows").mkdir(parents=True)
        body = CLEAN if workflow_runs else CLEAN.replace(GUARD_STEP, "      - run: true")
        path = root / ".github" / "workflows" / "x.yml"
        path.write_text(body.replace("check_acceptance.py", "check_x.py"), encoding="utf-8")
        return check_guards_are_run(root, [path])


def _pr_template_case(template):
    """check_pr_template against a throwaway tree holding one template."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github" / "workflows").mkdir(parents=True)
        path = root / ".github" / "workflows" / "x.yml"
        path.write_text(CLEAN, encoding="utf-8")
        (root / "Makefile").write_text("check: lint-y\n\nlint-y:\n\ttrue\n", encoding="utf-8")
        (root / ".github" / "PULL_REQUEST_TEMPLATE.md").write_text(template, encoding="utf-8")
        return check_pr_template(root, [path])


DEPENDABOT_DIRECTORIES = {"github-actions": "/", "gradle": "/android", "docker": "/docker"}


def _dependabot_case(ecosystems, gradle_directory=None):
    """check_dependabot against a throwaway tree declaring `ecosystems`."""
    import tempfile

    directories = dict(DEPENDABOT_DIRECTORIES)
    if gradle_directory:
        directories["gradle"] = gradle_directory
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "x.yml").write_text(CLEAN, encoding="utf-8")
        (root / "android").mkdir()
        (root / "android" / "build.gradle.kts").write_text("// gradle\n", encoding="utf-8")
        (root / "docker").mkdir()
        (root / "docker" / "Dockerfile").write_text("FROM x\n", encoding="utf-8")
        body = "version: 2\nupdates:\n" + "".join(
            f'  - package-ecosystem: {name}\n    directory: "{directories.get(name, "/")}"\n'
            for name in ecosystems
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
