#!/usr/bin/env python3
"""Fail a commit message that is the wrong *shape*.

Shape, never content. Subject length, a known type, no Title Case, no trailing
period, a blank second line -- and nothing cleverer than that. A checker that
tries to judge whether a message is *good* fires on a legitimate one sooner or
later, and the thing a contributor learns from that is `--no-verify`.

One implementation, two callers: `.githooks/commit-msg` runs it on every
commit, and CI runs it over the history. A hook and a workflow with their own
copies of a rule is two rules that will disagree.

Two modes, because the two callers have different things to hand it:

  FILE   a commit message: subject, blank line, body. What the hook gets.
  -      one subject per line on stdin. `git log --format=%s -30 | ... -`,
         which is what makes the rules honest: a convention this repository's
         own history breaks is a convention nobody will follow, and it should
         fail here rather than in a stranger's first pull request.

Exit codes: 0 clean, 1 a message that does not fit, 2 usage error.

Usage:
  python scripts/check_commit_msg.py .git/COMMIT_EDITMSG
  git log --format=%s -30 | python scripts/check_commit_msg.py -
  python scripts/check_commit_msg.py --self-test
"""

import re
import sys
from pathlib import Path

# The types this repository actually uses, counted over its own history rather
# than copied from the conventional-commits page. A longer list would be a
# vocabulary nobody here writes in; a shorter one would fail the log.
TYPES = ("feat", "fix", "docs", "test", "chore", "refactor", "ci")

# `type(scope)!: description`, with the scope and the breaking-change bang
# both optional.
SUBJECT_RE = re.compile(rf"^({'|'.join(TYPES)})(\([a-z0-9._/-]+\))?(!)?: (.+)$")

# Written by git itself, never by a person, and rejecting them would mean
# every merge needed `--no-verify` -- which is how a hook stops being run at
# all.
GENERATED_RE = re.compile(r"^(Merge |Revert \")")

# 80 because that is where `git log --oneline` wraps in the terminal these are
# read in, and because this repository's own recent subjects fit inside it.
# The earliest commits do not, and are not being rewritten to suit a rule that
# arrived after them.
MAX_SUBJECT = 80

# Tooling does not get a byline here. The project's commits carry one author
# and no assistant trailers, and this is the rule stated as a command with an
# exit code rather than as a line in a guide nobody re-reads.
TRAILER_RE = re.compile(r"^(co-authored-by:|generated with |🤖)", re.I)


def check_subject(subject):
    """Pure: the reasons `subject` is the wrong shape, as a list."""
    problems = []
    if GENERATED_RE.match(subject):
        return problems
    if len(subject) > MAX_SUBJECT:
        problems.append(f"{len(subject)} characters, and {MAX_SUBJECT} is the limit")
    found = SUBJECT_RE.match(subject)
    if not found:
        problems.append(
            "not `type: description` with a type from " + ", ".join(TYPES))
        return problems
    description = found.group(4)
    if description.endswith("."):
        problems.append("ends in a full stop")
    # **Title Case is the thing being rejected, not capitals**, and the
    # distinction is what keeps this rule from firing on legitimate messages.
    #
    # `MIC`, `POST` and `ADR` open real subjects in this history: acronyms,
    # not a sentence that started with a shift key, so an all-capitals word is
    # not evidence of anything. Neither is a handful of capitalised words --
    # `Gradle`, `PcPoller`, `Linux and macOS` are proper nouns, and counting
    # them flagged three legitimate subjects in this repository's own log.
    #
    # What Title Case actually is, is *density*: the short function words get
    # capitals too, so half the line or more is capitalised. That is the test.
    #
    # The cost of getting this wrong is asymmetric, which is why the test is
    # the loose one: a false positive teaches a contributor to pass
    # --no-verify, and after that the hook checks nothing at all. A missed
    # `feat: Add a thing` costs a moment of inconsistency.
    words = description.split()
    capitalised = [word for word in words
                   if len(word) > 1 and word[0].isupper() and word[1].islower()]
    if len(capitalised) > 1 and len(capitalised) * 2 >= len(words):
        problems.append(
            f"reads as Title Case ({', '.join(repr(w) for w in capitalised[:3])}...); "
            "lower case, imperative")
    return problems


# `git commit --verbose` (and `commit.verbose = true`, which plenty of people
# set) appends the whole diff below a scissors line. Git itself discards
# everything from that marker down -- and it has to be a marker rather than the
# comment filter below, because **the diff's own lines are not comments**. Left
# in, a commit that touches a file containing the words this checker rejects
# would be rejected for containing them, which is a confusing way to learn that
# a guard is wrong.
SCISSORS_RE = re.compile(r"^#\s*-+\s*>8\s*-+\s*$")


def _above_the_scissors(lines):
    """Pure: the message git would keep, dropping a --verbose diff."""
    for index, line in enumerate(lines):
        if SCISSORS_RE.match(line):
            return lines[:index]
    return lines


def check_message(lines):
    """Pure: the problems in a whole message -- subject, blank line, trailers."""
    lines = [line.rstrip("\n") for line in lines]
    lines = _above_the_scissors(lines)
    body = [line for line in lines if not line.startswith("#")]
    while body and not body[-1].strip():
        body.pop()
    if not body or not body[0].strip():
        return ["the message is empty"]

    problems = [f"subject: {why}" for why in check_subject(body[0])]
    if len(body) > 1 and body[1].strip():
        problems.append("line 2 must be blank: a subject, then the body")
    for line in body[1:]:
        if TRAILER_RE.match(line.strip()):
            problems.append(f"no attribution trailers: {line.strip()[:60]!r}")
    return problems


# Subjects already on `main` that break a rule, by their exact text, each with
# why it stays. `main` is not rewritten to fix one: it is published, and a
# force-push over it is the kind of thing CLAUDE.md stops for. Without this
# the listing check fails every branch for the next thirty commits, over a
# subject nobody can change any more.
#
# The listing only. A new commit is checked by `check_subject` through the
# commit-msg hook, and this table does not reach it: the same subject written
# again is refused.
PUBLISHED_EXCEPTIONS = {
    'feat(web): AGENDA do neon com até três eventos e o título do segundo inteiro (#63)':
        "squash-merged as #63 on 2026-09-30 with the PR's title, which is 82 characters; "
        "the branch's own commits were short, so the PR's lint passed",
    'feat: alerta de reunião, barra de volume do PC e umidade no TEMPO (wave 40) (#66)':
        "squash-merged as #66 on 2026-09-30; the PR title was 74 characters and GitHub's "
        "' (#66)' took it to 81, after every check that could have seen it",
}


def check_subjects(lines):
    """Pure: the problems in a list of subjects, each named by its own text.

    A subject in PUBLISHED_EXCEPTIONS is already on `main` and is skipped.
    """
    problems = []
    for line in lines:
        subject = line.rstrip("\n")
        if not subject.strip() or subject in PUBLISHED_EXCEPTIONS:
            continue
        for why in check_subject(subject):
            problems.append(f"{subject[:60]!r}: {why}")
    return problems


def _self_test():
    failures = []

    def ok(name, condition):
        print(f"{'ok  ' if condition else 'FAIL'}  {name}")
        if not condition:
            failures.append(name)

    ok("a subject in the right shape passes", check_subject("feat: add a thing") == [])
    ok("a scope is allowed", check_subject("fix(server): stop the thing") == [])
    ok("a breaking change is allowed", check_subject("feat(web)!: change the payload") == [])
    ok("no type at all is caught", check_subject("fixed some stuff") != [])
    ok("an unknown type is caught", check_subject("wip: something") != [])
    ok("a full stop is caught", check_subject("fix: stop the thing.") != [])
    ok("Title Case is caught", check_subject("feat: Add A Capitalised Thing") != [])
    ok("an acronym is not Title Case",
       check_subject("fix: MIC mutes every input on Linux") == []
       and check_subject("fix: POST alone does not keep a web page out") == [])
    ok("proper nouns are not Title Case",
       check_subject("feat(android): PcPoller, the panel's only network code") == []
       and check_subject("feat: Gradle project, pinned cleartext and a state ladder") == []
       and check_subject("feat: make the login signal work on Linux, macOS and Windows") == [])
    ok("an overlong subject is caught", check_subject("feat: " + "x" * MAX_SUBJECT) != [])
    ok("a merge subject is git's own", check_subject("Merge pull request #39 from x/y") == [])
    ok("a revert is git's own", check_subject('Revert "feat: a thing"') == [])

    ok("a blank second line is required",
       any("line 2" in p for p in check_message(["feat: a thing", "body straight away"])))
    ok("a body after a blank line is fine",
       check_message(["feat: a thing", "", "because of the reason"]) == [])
    ok("comments are not the message",
       check_message(["feat: a thing", "", "# Please enter the commit message"]) == [])
    ok("an empty message is caught", check_message(["", ""]) != [])
    ok("a --verbose diff is not the message",
       check_message(["feat: a thing", "", "why",
                      "# ------------------------ >8 ------------------------",
                      "# Do not modify or remove the line above.",
                      "diff --git a/x b/x",
                      "+Co-Authored-By: Someone <x@y>"]) == [])
    ok("an attribution trailer is caught",
       any("trailer" in p for p in
           check_message(["feat: a thing", "", "Co-Authored-By: Someone <x@y>"])))
    ok("a subject listing is checked line by line",
       len(check_subjects(["feat: fine", "nope", "also nope"])) == 2)
    ok("blank lines in a listing are skipped", check_subjects(["", "feat: fine", ""]) == [])
    published = next(iter(PUBLISHED_EXCEPTIONS))
    ok("a published exception is skipped in the listing", check_subjects([published]) == [])
    ok("a published exception is still refused as a new commit", check_subject(published) != [])
    ok("an exception is exact, not a prefix", check_subjects([published + " more"]) != [])

    print(f"\ncheck_commit_msg --self-test: {len(failures)} failure(s)")
    return 1 if failures else 0


def main(argv):
    args = argv[1:]
    if not args:
        print("usage: check_commit_msg.py FILE | - | --self-test", file=sys.stderr)
        return 2
    if args[0] == "--self-test":
        return _self_test()
    if len(args) > 1:
        print("check_commit_msg: one message at a time", file=sys.stderr)
        return 2

    if args[0] == "-":
        # UTF-8 whatever the locale says: `git log` writes UTF-8, and on
        # Windows stdin defaults to the ANSI code page, which turns an accent
        # into two characters -- a subject 82 long reads as 85, and an entry
        # in PUBLISHED_EXCEPTIONS stops matching its own text.
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        problems = check_subjects(text.splitlines())
        what = "subject(s)"
    else:
        # Read it rather than stat it. The hook is handed a real file, but
        # the acceptance line pipes into `/dev/stdin`, which is a pipe and
        # not a file -- and a checker that refused the way its own
        # documentation demonstrates it would be a fine joke.
        try:
            text = Path(args[0]).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"check_commit_msg: cannot read {args[0]}: {exc}", file=sys.stderr)
            return 2
        problems = check_message(text.splitlines())
        what = "message"

    if problems:
        print(f"check_commit_msg: {len(problems)} problem(s) in the {what}", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print("\n  See CONTRIBUTING.md. The rules are about shape, not about what you wrote.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
