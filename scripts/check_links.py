#!/usr/bin/env python3
"""Fail if a Markdown link in the given files points at nothing.

Documentation that lies is worse than documentation that is missing: a reader
who follows a dead link learns not to follow the next one. This repository is
mostly prose -- ADRs, task files, three setup guides -- so the links are a
large part of what it is, and nothing checked them until T7.4.

Two kinds of link, two kinds of failure, and keeping them apart is the point:

  - a **relative** link is resolved against the file that carries it and the
    target has to exist on disk. A broken one is always the repository's fault.
  - an **https** link has to answer 2xx. A 404 is the repository's fault; a
    timeout or a DNS failure is not, and is reported under its own heading
    with its own exit code, because a contributor on a train should be able to
    tell "you broke a link" from "you are offline" without reading the source.

`--skip-remote` is the offline switch. `--self-test` runs the parser and the
classification against a throwaway tree and touches no network at all, which
is what `make lint-selftests` discovers by grep.

Exit codes: 0 clean, 1 a dead link, 2 usage error, 3 only network failures.

Usage:
  python scripts/check_links.py [--skip-remote] [--timeout S] FILE [FILE ...]
  python scripts/check_links.py --self-test
"""

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Inline links only: `[text](target)`. Reference-style definitions and bare
# URLs in prose are deliberately out of scope -- this repository writes inline
# links everywhere, and a parser that tried to cover every Markdown dialect
# would have failure modes of its own that nobody would trust.
#
# The target stops at the first whitespace so a titled link, `[t](url "why")`,
# yields the url. Nested parentheses are not handled and are why no link in
# these documents may carry one: an `Activity#setTurnScreenOn(boolean)` anchor
# would truncate here, silently, and be reported as a page that exists.
LINK_RE = re.compile(r"\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)")

# Fenced code blocks are skipped. A shell snippet that contains `[x](y)` is not
# a link, and `docs/` is full of shell snippets.
FENCE_RE = re.compile(r"^\s*(```|~~~)")

USER_AGENT = "desk-panel-link-check"


def links_in(text):
    """Pure: every inline link target in `text`, outside fenced code."""
    found = []
    fenced = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for target in LINK_RE.findall(line):
            found.append(target.strip("<>"))
    return found


def classify(target):
    """Pure: `remote`, `local`, or `skip` -- and why each is which.

    `mailto:` and other schemes are nothing this script can check. A pure
    anchor (`#section`) is a link inside one rendered page, and checking it
    would mean modelling how the renderer builds slugs from headings -- a
    different job with a different failure mode.
    """
    if target.startswith(("http://", "https://")):
        return "remote"
    if target.startswith("#") or ":" in target.split("/")[0]:
        return "skip"
    return "local"


def check_local(source, target):
    """The file a relative link names, or a reason it is not there."""
    path = (source.parent / target.split("#")[0].split("?")[0]).resolve()
    if path.exists():
        return None
    return "no such file"


def check_remote(url, timeout, opener=None):
    """`None` if the page answers 2xx, else (`dead` | `unreachable`, why).

    HEAD first because it is cheap, then GET: plenty of servers answer 405 or
    403 to a HEAD they would serve happily, and reporting one of those as a
    dead link would be this script crying wolf on its first run.
    """
    opener = opener or _urlopen
    reason = None
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method,
                                         headers={"User-Agent": USER_AGENT})
        try:
            with opener(request, timeout) as answer:
                if 200 <= answer.status < 300:
                    return None
                reason = ("dead", f"HTTP {answer.status}")
        except urllib.error.HTTPError as exc:
            reason = ("dead", f"HTTP {exc.code}")
        except urllib.error.URLError as exc:
            # No status at all: DNS, a refused connection, a timeout. The
            # server never said anything about the page, so neither do we.
            return ("unreachable", str(getattr(exc, "reason", exc)))
        except TimeoutError as exc:
            return ("unreachable", f"timed out: {exc}" if str(exc) else "timed out")
    return reason


def _urlopen(request, timeout):
    return urllib.request.urlopen(request, timeout=timeout)


def check(paths, skip_remote=False, timeout=10.0, opener=None):
    """Returns (dead, unreachable), each a list of printable lines."""
    dead, unreachable = [], []
    seen = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for target in links_in(text):
            kind = classify(target)
            if kind == "skip":
                continue
            if kind == "local":
                why = check_local(path, target)
                if why:
                    dead.append(f"{path}: {target} -- {why}")
                continue
            if skip_remote:
                continue
            # One request per url, however many documents carry it. The four
            # citations T7.4 asks for repeat across two files by design.
            if target not in seen:
                seen[target] = check_remote(target, timeout, opener)
            verdict = seen[target]
            if verdict is not None:
                bucket, why = verdict
                (dead if bucket == "dead" else unreachable).append(
                    f"{path}: {target} -- {why}")
    return dead, unreachable


def report(dead, unreachable):
    if dead:
        print(f"check_links: {len(dead)} dead link(s)", file=sys.stderr)
        for line in dead:
            print(f"  {line}", file=sys.stderr)
    if unreachable:
        print(f"check_links: {len(unreachable)} link(s) could not be reached",
              file=sys.stderr)
        for line in unreachable:
            print(f"  {line}", file=sys.stderr)
        print("\n  These are network failures, not broken links. Re-run, or pass\n"
              "  --skip-remote if you are working offline.", file=sys.stderr)
    if dead:
        return 1
    if unreachable:
        return 3
    return 0


# --------------------------------------------------------------------------
# Self-test. No network: the opener is injected, which is the same shape
# `server/actions.py` uses for the mixer and for the same reason.
# --------------------------------------------------------------------------

class FakeAnswer:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _self_test():
    import contextlib
    import io
    import tempfile

    failures = []

    def ok(name, condition):
        print(f"{'ok  ' if condition else 'FAIL'}  {name}")
        if not condition:
            failures.append(name)

    ok("an inline link is found",
       links_in("see [the guide](docs/BUILD.md) for more") == ["docs/BUILD.md"])
    ok("a link inside a fence is not a link",
       links_in("```\n[x](y)\n```\n[real](z)\n") == ["z"])
    ok("an angle-bracketed target loses its brackets",
       links_in("[t](<a b.md>)") == ["a b.md"])
    ok("a title after the url is not part of it",
       links_in('[t](docs/x.md "why")') == ["docs/x.md"])
    ok("an anchor alone is skipped", classify("#section") == "skip")
    ok("mailto is skipped", classify("mailto:someone@example.com") == "skip")
    ok("http and https are remote",
       classify("http://x/y") == "remote" and classify("https://x/y") == "remote")
    ok("a path is local", classify("adr/0015-x.md") == "local")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        (root / "docs" / "there.md").write_text("# there\n", encoding="utf-8")
        page = root / "docs" / "page.md"
        page.write_text(
            "[here](there.md)\n[gone](missing.md)\n[far](https://example.invalid/x)\n",
            encoding="utf-8")

        dead, unreachable = check([page], skip_remote=True)
        ok("a relative link that resolves passes",
           len(dead) == 1 and "missing.md" in dead[0])
        ok("--skip-remote asks nothing of the network", unreachable == [])

        def answers(status):
            return lambda request, timeout: FakeAnswer(status)

        dead, unreachable = check([page], opener=answers(200))
        ok("a 2xx remote link passes", len(dead) == 1 and unreachable == [])

        dead, unreachable = check([page], opener=answers(404))
        ok("a 404 is a dead link", len(dead) == 2 and unreachable == [])

        def refuses(request, timeout):
            raise urllib.error.URLError("Name or service not known")

        dead, unreachable = check([page], opener=refuses)
        ok("a network failure is not a dead link",
           len(dead) == 1 and len(unreachable) == 1)
        # `report` writes to stderr; the self-test asserts on its exit code,
        # not on a wall of text about a domain that does not exist.
        with contextlib.redirect_stderr(io.StringIO()):
            only_network = report([], unreachable)
            both = report(dead, unreachable)
        ok("a network failure has its own exit code", only_network == 3)
        ok("a dead link outranks a network failure", both == 1)

        calls = []

        def counting(request, timeout):
            calls.append(request.full_url)
            return FakeAnswer(200)

        twice = root / "docs" / "twice.md"
        twice.write_text("[a](https://example.invalid/x)\n[b](https://example.invalid/x)\n",
                         encoding="utf-8")
        check([page, twice], opener=counting)
        ok("one request per url, however many documents carry it",
           calls.count("https://example.invalid/x") == 1)

        methods = []

        def head_refused(request, timeout):
            methods.append(request.get_method())
            if request.get_method() == "HEAD":
                raise urllib.error.HTTPError(request.full_url, 405, "no", None, None)
            return FakeAnswer(200)

        dead, _ = check([twice], opener=head_refused)
        ok("a HEAD refused is retried as GET", methods == ["HEAD", "GET"] and dead == [])

    print(f"\ncheck_links --self-test: {len(failures)} failure(s)")
    return 1 if failures else 0


def main(argv):
    args, paths = argv[1:], []
    skip_remote, timeout = False, 10.0
    while args:
        flag = args.pop(0)
        if flag == "--self-test":
            return _self_test()
        if flag == "--skip-remote":
            skip_remote = True
        elif flag == "--timeout":
            if not args:
                print("check_links: --timeout needs a value", file=sys.stderr)
                return 2
            timeout = float(args.pop(0))
        elif flag.startswith("-"):
            print(f"check_links: unknown option {flag}", file=sys.stderr)
            return 2
        else:
            paths.append(Path(flag))
    if not paths:
        print(__doc__.strip().splitlines()[-2].strip(), file=sys.stderr)
        return 2
    missing = [p for p in paths if not p.is_file()]
    if missing:
        for path in missing:
            print(f"check_links: no such file: {path}", file=sys.stderr)
        return 2

    dead, unreachable = check(paths, skip_remote=skip_remote, timeout=timeout)
    code = report(dead, unreachable)
    if code == 0:
        total = sum(len(links_in(p.read_text(encoding="utf-8"))) for p in paths)
        where = "local only" if skip_remote else "local and remote"
        print(f"check_links: OK - {total} link(s) in {len(paths)} file(s), {where}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
