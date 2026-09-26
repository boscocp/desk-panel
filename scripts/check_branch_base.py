#!/usr/bin/env python3
"""Fail if this branch was cut from a `main` that is no longer current.

The failure this exists to stop has happened twice, and prose did not stop the
second one.

  - **2026-09-24**, wave 21: a session opened on a `main` four waves stale,
    rebuilt T0.6 from scratch, reviewed it, and found at the merge that the
    work had already shipped. PR #30, closed unmerged.
  - **2026-09-26**, wave 24: a session opened on a `main` that was four commits
    behind, read a `tasks/STATUS.md` whose "Next:" line had been superseded the
    day before, and rebuilt TT.12 -- which was merged as PR #31 while it was
    being written.

`CLAUDE.md` already said "git fetch before you branch" in words after the first
one. The second happened anyway, because the git status a session opens with is
a snapshot that reads as current when it is not, and nothing compared it to
anything. This repo's own rule is that every criterion is a command with an
exit code; "remember to fetch" is not one.

So this is the command, and `make wave-start` runs it **twice**, on either
side of the fast-forward, because one call cannot do both jobs:

  - `--report` **before** the merge, where `main` is still the stale thing the
    session opened on. This is the call that prints the commits and names the
    superseded `Next:` line. It never fails: being behind at the start of a
    wave is the normal case and fast-forwarding is the answer, not refusing.
  - plain **after** it, as a post-condition. By then HEAD is `origin/main` by
    construction, so this one is only allowed to be green -- and if it is not,
    the fast-forward did not do what it said.

Running only the second call is what the first cut did, and it made the guard
unable to fire in the one place it was wired: `git log origin/main ^HEAD` after
a fast-forward is empty whatever happened before it. Found by review.

It is deliberately **not** in `make check`, and that is not an oversight: a pull
request branch falls behind `main` as a matter of course, and a guard that goes
red on every open pull request the moment `main` moves is the same failure one
layer up. Run it by hand -- with `--fetch` -- on a tree that has been open a
while and is about to be worked on.

Exit codes: 0 the base is current, 1 it is behind, 2 this is not a git tree.

Usage:
  python scripts/check_branch_base.py            # compare against the last fetch
  python scripts/check_branch_base.py --fetch    # fetch first, then compare
  python scripts/check_branch_base.py --report   # say it, never fail on it
  python scripts/check_branch_base.py --self-test
"""

import subprocess
import sys

UPSTREAM = "origin/main"


def git(*args):
    """stdout, or None when git says no. Never raises."""
    try:
        done = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def missing_commits(log):
    """The upstream commits that HEAD does not contain, newest first.

    Pure: `log` is whatever `git log <upstream> ^HEAD` printed. Split out so
    --self-test can reach the decision without a repository.
    """
    if log is None:
        return None
    return [line for line in log.splitlines() if line.strip()]


def describe(missing, upstream=UPSTREAM, report=False):
    """The report text. `report` changes the verdict, never the evidence.

    Both modes print the same commits: the whole value of the `--report` call
    is that a session sees what it was about to miss, and a mode that said
    less would be the reminder this repo already proved does not work.
    """
    if not missing:
        return f"check_branch_base: OK - the base is {upstream}"
    lines = [
        f"  {upstream} has {len(missing)} commit(s) this branch was not cut from:",
        *(f"    {line}" for line in missing[:10]),
    ]
    if len(missing) > 10:
        lines.append(f"    ... and {len(missing) - 10} more")
    if report:
        lines += [
            "",
            f"  Read the newest `## Resuming after` section of tasks/STATUS.md at {upstream},",
            "  not the one this tree opened with: a `Next:` line older than these commits",
            "  has been superseded before, and cost a wave.",
            "",
            f"check_branch_base: REPORT - {len(missing)} commit(s) behind, not failing",
        ]
        return "\n".join(lines)
    lines += [
        "",
        "  Whatever tasks/STATUS.md says here may already be done. Rebase onto",
        f"  {upstream} and re-read the last `## Resuming after` section before",
        "  writing anything: this has cost two waves of duplicated work.",
        "",
        "check_branch_base: FAIL - stale base",
    ]
    return "\n".join(lines)


def run(fetch=False, report=False):
    if git("rev-parse", "--git-dir") is None:
        print("check_branch_base: not a git repository", file=sys.stderr)
        return 2
    if fetch and git("fetch", "--quiet", "origin") is None:
        # Offline is not "up to date". Say which one this is rather than
        # reporting a comparison against a ref that may be days old.
        print(
            f"check_branch_base: could not fetch origin; comparing against {UPSTREAM}"
            " as it stands locally, which may itself be stale",
            file=sys.stderr,
        )
    if git("rev-parse", "--verify", "--quiet", UPSTREAM) is None:
        print(f"check_branch_base: no {UPSTREAM} -- nothing to compare against", file=sys.stderr)
        return 2

    log = git("log", "--oneline", "--no-decorate", UPSTREAM, "^HEAD")
    missing = missing_commits(log)
    if missing is None:
        print("check_branch_base: git log failed", file=sys.stderr)
        return 2
    print(describe(missing, report=report))
    return 0 if report else (1 if missing else 0)


SELF_TEST_CASES = [
    ("a base with nothing missing is clean", lambda: missing_commits("") == []),
    (
        "one missing commit is one line",
        lambda: missing_commits("abc1234 docs: next session starts on T8.1") ==
        ["abc1234 docs: next session starts on T8.1"],
    ),
    (
        "blank lines are not commits",
        lambda: missing_commits("abc1234 x\n\n\ndef5678 y") == ["abc1234 x", "def5678 y"],
    ),
    ("a failed git log is not an empty answer", lambda: missing_commits(None) is None),
    ("clean describes as OK", lambda: describe([]).endswith("OK - the base is origin/main")),
    ("stale describes as FAIL", lambda: describe(["abc1234 x"]).endswith("FAIL - stale base")),
    (
        "a long list is truncated and says so",
        lambda: "and 5 more" in describe([f"{n:07d} c" for n in range(15)]),
    ),
    (
        "the advice names the thing that was missed",
        lambda: "Resuming after" in describe(["abc1234 x"]),
    ),
    (
        "--report prints the same commits as a failure does",
        lambda: "abc1234 x" in describe(["abc1234 x"], report=True),
    ),
    (
        "--report does not call itself a failure",
        lambda: describe(["abc1234 x"], report=True).endswith("behind, not failing"),
    ),
    (
        "--report still sends the reader to the newest Resuming after",
        lambda: "Resuming after" in describe(["abc1234 x"], report=True),
    ),
    (
        "nothing behind reads the same either way",
        lambda: describe([], report=True) == describe([]),
    ),
]


def self_test(stream=sys.stdout):
    failures = 0
    for name, check in SELF_TEST_CASES:
        try:
            ok = bool(check())
        except Exception as exc:  # a raising case is a failing case
            ok, name = False, f"{name}  [{type(exc).__name__}: {exc}]"
        if not ok:
            failures += 1
            print(f"FAIL  {name}", file=stream)
    print(f"{len(SELF_TEST_CASES) - failures}/{len(SELF_TEST_CASES)} self-test cases passed", file=stream)
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv[1:]:
        return self_test()
    unknown = [a for a in argv[1:] if a not in {"--fetch", "--report"}]
    if unknown:
        print(__doc__.split("Usage:")[1], file=sys.stderr)
        return 2
    return run(fetch="--fetch" in argv[1:], report="--report" in argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
