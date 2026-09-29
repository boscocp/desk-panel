#!/usr/bin/env python3
"""Fail if this repository carries something that looks like a credential.

T7.3 step 1 greps `git log -p` for the words *token*, *password*, *keystore* and *api key*.
A word list only finds a secret that happens to sit near a word somebody thought of: a JWT,
an `ssh-rsa` blob, an `AKIA...` key or forty characters of hex carry none of them. This
looks for the *shapes*.

Two halves, reported apart, because they have different remedies:

  - the **tree** is what a clone gets today. A finding here is fixed by deleting it.
  - the **history** is every blob that has ever been committed, reachable or not. A file
    deleted in a later commit is still in the pack and still in a clone, so a finding here
    means **rotate the credential**; deleting it now changes nothing, and rewriting
    published history is a separate, worse conversation that a person takes, not a script.

`scripts/check_links.py` draws the same line between a dead link and an unreachable one,
for the same reason: a reader has to be able to tell which of two different problems they
have. Note the exit codes run the other way round to that script's -- here 3 is the more
serious of the two, and it is 3 rather than 1 so that `make check`, which runs the tree
half only, cannot be made green by a fix that does nothing.

Every deliberate finding is allowed in `scripts/secrets-allowlist.toml` **with a reason**,
which the file format requires. An allowlist of bare patterns is a way of turning a guard
off with extra steps; the reason is what makes the second run readable and the third one
worth doing.

One invocation runs one half. There is no combined mode and no combined exit code: CI
runs both, as two steps in two jobs, so that a red tick says which half went red without
anybody opening the log.

Exit codes: 0 clean, 1 a finding in the tree (or a stale allowlist entry, reported under
its own heading), 2 usage error or an unusable allowlist, 3 a finding in the history.

Usage:
  python scripts/check_secrets.py [--allowlist PATH]            # the tree
  python scripts/check_secrets.py --history [--allowlist PATH]  # every blob, ever
  python scripts/check_secrets.py --self-test
"""

import fnmatch
import math
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ALLOWLIST = Path("scripts/secrets-allowlist.toml")

# One entry per credential shape, and the `why` is printed with the finding: somebody
# reading a red build at the wrong end of a week should not have to read this file.
#
# `assigned-secret` is the only rule here that reads words, and it is kept because it is
# the shape this project actually risks -- the brapi token lives in `server/config.toml`,
# which is gitignored, and the way it would escape is somebody pasting a config into a doc
# or a test. It requires an assignment and a quoted value, so prose about tokens does not
# fire it.
RULES = (
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
     "a PEM private key block"),
    ("ssh-public-key", re.compile(r"\bssh-(?:rsa|ed25519|dss) AAAA[0-9A-Za-z+/]{20,}"),
     "an SSH key; the public half names a machine and the private half is never far"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
     "a JSON web token"),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "an AWS access key id"),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,})"),
     "a GitHub token"),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "a Slack token"),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "a Google API key"),
    ("bearer-header", re.compile(r"(?i)authorization\s*[:=]\s*[\"']?bearer\s+\S{12,}"),
     "a bearer token in an Authorization header"),
    ("assigned-secret", re.compile(
        r"(?i)\b[a-z0-9_.-]*(?:token|api[_-]?key|apikey|password|passwd|secret)\s*[:=]\s*"
        r"[\"'][^\"'\s]{12,}[\"']"),
     "a secret-looking name assigned a quoted value"),
    # Not a credential, and here because a sweep is about what you did not mean to
    # publish. The PC's real LAN address is pinned all over this repository by design
    # (ADR 0013) and `192.168.1.100` is the agreed placeholder that reaches no PC. In
    # prose it is a fact about this desk; in *source* it is a value somebody will ship.
    # T7.3 greps for this too -- two overlapping checks on the thing that cannot be
    # undone is the right number -- but only this one carries the reasons.
    ("lan-address", re.compile(r"\b192\.168\.(?!1\.100\b)\d{1,3}\.\d{1,3}\b"),
     "a LAN address that is not the placeholder 192.168.1.100"),
    ("hex-blob", re.compile(r"\b[0-9a-fA-F]{40,}\b"),
     "forty or more hex characters: a hash, a commit, or a key"),
    ("random-blob", None,
     "a long high-entropy string, which is what a key looks like with its label removed"),
)

# The generic rule, kept apart because it is the only one that is a judgement rather than a
# shape. A run of token characters is reported when it mixes cases and digits *and* carries
# more entropy than words do. Without the mix every camelCase Java test method in this
# repository is a finding -- `anAbsentOrEmptyLanguageLeavesTheKeyOutAltogether` is 47
# characters of perfectly ordinary English -- and a rule that fires on those is a rule
# nobody reads twice. `/` is excluded from the run so that file paths and URLs, which are
# base64's alphabet with a different meaning, do not arrive here at all, and `=` counts
# only as trailing padding -- taking it mid-run turns every `KEY=value` line of captured
# systemd output into one long "high-entropy" string, which is what the first cut did.
BLOB_RE = re.compile(r"[A-Za-z0-9+_-]{32,}={0,2}")
MIN_ENTROPY = 4.0

# A name that should never be committed, whatever is inside it. Checked over the history
# too: the whole point is that `git rm` does not remove anything from a clone.
FORBIDDEN_NAMES = (
    ("server/config.json", "the live config, which holds the brapi token"),
    ("server/config.toml", "the live config, which holds the brapi token"),
    ("*.keystore", "a signing keystore"),
    ("*.jks", "a signing keystore"),
    ("keystore.properties", "signing passwords"),
    (".env", "build-time local config, including signing passwords"),
    ("*.pem", "a certificate or key"),
    ("*.key", "a key"),
)

# Anything that is not text is not read. A binary blob cannot be grepped usefully and the
# one that matters -- a keystore -- is caught by name, above.
MAX_BYTES = 2_000_000


def entropy(text):
    """Pure: Shannon entropy of `text` in bits per character."""
    if not text:
        return 0.0
    counts = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def looks_random(run):
    """Pure: is this run of characters a key rather than a word?

    Three conditions, and each one is there because dropping it floods the report: a digit
    and both cases (prose and identifiers rarely have all three), and entropy above what
    English-shaped text reaches. Pure hex is excluded here because `hex-blob` owns it and
    two rules naming the same string is a report nobody trusts.
    """
    if re.fullmatch(r"[0-9a-fA-F]+", run):
        return False
    return (any(c.isdigit() for c in run)
            and any(c.islower() for c in run)
            and any(c.isupper() for c in run)
            and entropy(run) >= MIN_ENTROPY)


def findings_in(text, path):
    """Every rule hit in `text`, as (rule, path, matched text) triples."""
    found = []
    for rule, pattern, _why in RULES:
        if pattern is None:
            continue
        for match in pattern.finditer(text):
            found.append((rule, path, match.group(0)))
    for match in BLOB_RE.finditer(text):
        if looks_random(match.group(0)):
            found.append(("random-blob", path, match.group(0)))
    return found


def name_findings(path):
    """A path that should never have been committed, whatever it contains."""
    name = path.split("/")[-1]
    for pattern, why in FORBIDDEN_NAMES:
        target = path if "/" in pattern else name
        if fnmatch.fnmatch(target, pattern):
            return [("forbidden-name", path, f"{pattern}: {why}")]
    return []


# The rules that are not a regex over text. Kept beside RULES rather than inside it so
# that `findings_in` stays a pure function of a string.
OTHER_WHY = {
    "forbidden-name": "a name that should never be committed, whatever is inside it",
    "ignored-but-tracked": (
        "`.gitignore` says this file should not be here and git is tracking it anyway; "
        "for the entries at the top of that file, that is how a secret ships"),
}


def why_for(rule):
    for name, _pattern, why in RULES:
        if name == rule:
            return why
    return OTHER_WHY.get(rule, "something that should not be here")


def ignored_but_tracked(cwd=None):
    """Tracked files that `.gitignore` excludes.

    `git add -f` and a rename past a rule both do this silently. The first five lines of
    this repository's `.gitignore` are `server/config.json`, `server/config.toml`,
    `*.keystore`, `*.jks` and `keystore.properties`, so a file that is both ignored and
    tracked is the exact shape of the accident this sweep exists for.
    """
    listing = _git("ls-files", "-i", "-c", "--exclude-standard", "-z", cwd=cwd).decode("utf-8")
    return [("ignored-but-tracked", path, ".gitignore excludes it and it is tracked")
            for path in listing.split("\0") if path]


def load_allowlist(path):
    """The allowed findings, or a usage error naming the entry that is malformed.

    Returns (entries, problems). Every entry needs a `reason` that says something, and
    something to match on -- an entry that allows a rule everywhere is the guard turned
    off, written as though it were a decision.
    """
    if not path.is_file():
        return [], [f"no allowlist at {path}"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return [], [f"{path}: {exc}"]

    entries, problems = [], []
    for index, entry in enumerate(data.get("allow", []), 1):
        where = f"{path}: allow[{index}]"
        if not str(entry.get("reason", "")).strip():
            problems.append(f"{where}: no reason, and the reason is the point")
            continue
        if not entry.get("path") and not entry.get("match"):
            problems.append(f"{where}: allows a rule everywhere; name a path or a match")
            continue
        if entry.get("where") not in (None, "both", "tree", "history"):
            problems.append(f"{where}: `where` is tree, history or both")
            continue
        entries.append(entry)
    return entries, problems


def allowed(entry, rule, path, text, half="tree"):
    """Does this allowlist entry cover this finding, in this half of the sweep?

    `where` exists because a decision can legitimately differ between the two. The real
    LAN address was taken out of source by T7.10 and is still in the history of those
    files -- which is the whole point of the history half -- and accepting it there is
    not the same statement as accepting it in the tree.
    """
    if entry.get("where") not in (None, "both", half):
        return False
    if entry.get("rule") not in (None, "*", rule):
        return False
    if entry.get("path") and not fnmatch.fnmatch(path, entry["path"]):
        return False
    if entry.get("match") and entry["match"] not in text:
        return False
    return True


def sieve(found, entries, half="tree"):
    return [f for f in found if not any(allowed(e, *f, half=half) for e in entries)]


def stale(entries, tracked):
    """Allowlist entries naming a file that is not in the tree.

    An entry that outlived the thing it allowed is a comment claiming a decision that no
    longer exists. Two kinds escape: `history = true`, and `where = "history"` -- which
    is about blobs rather than files and becomes *most* necessary at the moment the file
    is renamed or deleted. Reading only the first of those would have turned a correct
    history entry red exactly when it started to matter. Found by review.
    """
    problems = []
    for entry in entries:
        path = entry.get("path")
        if not path or any(c in path for c in "*?["):
            continue
        if entry.get("history") or entry.get("where") == "history":
            continue
        if path not in tracked:
            problems.append(f"allowlist names {path}, which is not in the tree any more")
    return problems


def _git(*args, cwd=None):
    return subprocess.run(("git",) + args, capture_output=True, check=True, cwd=cwd).stdout


def tracked_files():
    return [p for p in _git("ls-files", "-z").decode("utf-8").split("\0") if p]


def scan_tree(entries):
    """Findings in what a clone gets today."""
    found = list(ignored_but_tracked())
    for path in tracked_files():
        found.extend(name_findings(path))
        blob = Path(path)
        if not blob.is_file() or blob.stat().st_size > MAX_BYTES:
            continue
        try:
            text = blob.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.extend(findings_in(text, path))
    return sieve(found, entries)


def history_objects():
    """Every named object in the history, as sha -> the set of paths it has had.

    `--all` covers every ref; an object reachable from none of them is not in a clone
    either. One `cat-file --batch` for the whole walk, because 2,000 subprocesses is the
    difference between a check CI runs and a check somebody disables.

    A *set* of paths, because `rev-list --objects` emits the same sha once per path it has
    ever had, and keeping only the last one mis-attributes the finding: a secret committed
    at `server/config.toml` and later copied elsewhere would be reported under whichever
    path came last, and an allowlist entry naming the real file would silently miss.
    Trees are named here too and are dropped in the walk, where `cat-file` says which is
    which. Found by review.
    """
    listing = _git("rev-list", "--objects", "--all").decode("utf-8", "replace")
    objects = {}
    for line in listing.splitlines():
        sha, _, path = line.partition(" ")
        if path:
            objects.setdefault(sha, set()).add(path)
    return objects


def scan_history(entries):
    """Findings in every blob in the pack, and how many blobs that was.

    Returns (findings, blob count). The count is what `cat-file` called a blob, not what
    `rev-list --objects` named: that listing includes trees, and counting them made the
    headline "1,970 blobs" for a history with 1,080 of them -- a number that had already
    been copied into three documents as the proof of coverage. Found by review.
    """
    objects = history_objects()
    if not objects:
        return [], 0

    # Findings are collected against the *bare* path and sieved before the blob sha is
    # appended for the report. The first cut decorated first, so every allowlist entry
    # naming a path matched nothing here and the history half reported thirty-six
    # allowed hashes as findings. Found by running it.
    found = []
    for sha, paths in objects.items():
        for path in sorted(paths):
            for rule, _p, text in name_findings(path):
                found.append((rule, path, text, sha))

    request = "".join(f"{sha}\n" for sha in objects)
    out = subprocess.run(["git", "cat-file", "--batch"], input=request.encode(),
                         capture_output=True, check=True).stdout
    offset, blobs = 0, 0
    while offset < len(out):
        end = out.index(b"\n", offset)
        sha, kind, size = out[offset:end].decode("utf-8").split()
        body = out[end + 1:end + 1 + int(size)]
        offset = end + 1 + int(size) + 1
        if kind != "blob":
            continue
        blobs += 1
        if int(size) > MAX_BYTES or b"\0" in body[:8000]:
            continue
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            continue
        # One finding per (blob, path): the same bytes committed under two names are two
        # decisions, and a path-scoped allowlist entry has to be able to cover one of them.
        for path in sorted(objects.get(sha, {""})):
            found.extend((rule, p, match, sha) for rule, p, match in findings_in(text, path))

    kept = sieve([(rule, path, text) for rule, path, text, _sha in found], entries, "history")
    keep = {(rule, path, text) for rule, path, text in kept}
    return ([(rule, f"{path} ({sha[:12]})", text)
             for rule, path, text, sha in found if (rule, path, text) in keep], blobs)


def report(found, half, stream=sys.stderr):
    if not found:
        return
    print(f"check_secrets: {len(found)} finding(s) in the {half}", file=stream)
    for rule, path, text in found:
        shown = text if len(text) <= 48 else f"{text[:45]}..."
        print(f"  [{rule}] {path}: {shown}", file=stream)
        print(f"      {why_for(rule)}", file=stream)


def main(argv):
    args = argv[1:]
    if "--self-test" in args:
        return _self_test()

    allowlist, history = ALLOWLIST, False
    while args:
        flag = args.pop(0)
        if flag == "--history":
            history = True
        elif flag == "--allowlist":
            if not args:
                print("check_secrets: --allowlist needs a value", file=sys.stderr)
                return 2
            allowlist = Path(args.pop(0))
        else:
            print(f"check_secrets: unknown option {flag}", file=sys.stderr)
            return 2

    entries, problems = load_allowlist(allowlist)
    if problems:
        print("check_secrets: the allowlist is not usable", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 2

    if history:
        found, blobs = scan_history(entries)
        report(found, "history")
        if found:
            print("\n  These are in the pack, so they are in every clone. Deleting them now\n"
                  "  changes nothing: rotate whatever they are keys to, then decide about\n"
                  "  rewriting history -- which is a force-push over published commits and\n"
                  "  is a person's decision, not this script's.", file=sys.stderr)
            return 3
        print(f"check_secrets: {blobs} blob(s) in the history, nothing found")
        return 0

    found = scan_tree(entries)
    report(found, "tree")
    leftovers = stale(entries, set(tracked_files()))
    if leftovers:
        # Its own heading. A stale entry is not a credential in the tree, and printing it
        # as unlabelled lines under the exit code documented as "a finding in the tree"
        # told the reader the wrong thing about their own repository. Found by review.
        print(f"check_secrets: {len(leftovers)} stale allowlist entry(ies)", file=sys.stderr)
        for line in leftovers:
            print(f"  {line}", file=sys.stderr)
        print("\n  Each allows something that is not there any more. Delete the entry, or"
              "\n  mark it `where = \"history\"` if it is about a blob rather than a file.",
              file=sys.stderr)
    if found or leftovers:
        return 1
    print(f"check_secrets: {len(tracked_files())} tracked file(s), nothing found; "
          f"{len(entries)} allowed with a reason")
    return 0


# --------------------------------------------------------------------------
# Self-test. Every rule against a string shaped like the thing it looks for and
# keyed to nothing, and every way the allowlist is allowed to be wrong.
#
# None of the strings below is a credential. The key blocks are truncated, the
# tokens are the documented prefix plus filler, and nothing here opens anything.
# --------------------------------------------------------------------------

def _sample(*parts):
    """A sample assembled from pieces, so that no rule matches this file.

    Every string below would otherwise be a finding in `scripts/check_secrets.py`, and it
    was: the first version of this file failed its own guard fifteen times. The obvious
    fix is an allowlist entry covering this path, and it is the wrong one -- it would
    blind the sweep to a real key pasted into the one file nobody would think to look in.
    Splitting each sample so the *pattern* never appears whole keeps the guard live over
    its own source, and costs a join. Each split falls inside the part of the pattern that
    cannot be spelled around it.
    """
    return "".join(parts)


SAMPLES = {
    "private-key": _sample("-----BEGIN RSA PRIVATE", " KEY-----\nMIIB\n-----END-----"),
    "ssh-public-key": _sample("ssh-", "rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDnotarealkey"),
    "jwt": _sample("ey", "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiJub2JvZHkifQ.c2lnbmF0dXJlLWhlcmU"),
    "aws-key": _sample("AKI", "AIOSFODNN7EXAMPLE"),
    # Three parts, not two: the token's body is itself a 36-character high-entropy run,
    # so `random-blob` found it after `github-token` stopped matching. The same for the
    # Google key below. Every piece here is under the 32-character floor.
    "github-token": _sample("ghp_", "A1b2C3d4E5f6G7h8", "I9j0K1l2M3n4O5p6Q7r8"),
    "slack-token": _sample("xox", "b-000000000000-000000000000-abcdefghijklmnop"),
    "google-key": _sample("AIza", "SyD-0123456789", "abcdefghijklmnopqrstu"),
    "bearer-header": _sample("Authorization: Bearer ", "abcdefghijklmnopqrstuvwxyz012345"),
    # The shape this project would actually leak. The key is a *suffix*: a rule anchored
    # with \b immediately before `token` misses `brapi_token`, which is the name of the
    # only credential this repository has.
    "assigned-secret": _sample('brapi_token = ', '"abcd1234efgh5678"'),
    "lan-address": _sample("the PC answers on 192.168.", "15.3 today"),
    "hex-blob": _sample("d41d8cd98f00b204e980", "0998ecf8427e5f3a1b2c9d8e7f60"),
    "random-blob": _sample("Zx9Qv2Lm8Tb4Nc7Rj1Ks", "6Hd3Gf0Pw5Yt2Ua9Ie4Oq7"),
}

CLEAN = """\
# A file with nothing in it but the kind of text this repository is full of.
def anAbsentOrEmptyLanguageLeavesTheKeyOutAltogether():
    return "http://192.168.1.100:8777/quotes"
"""


def _self_test():
    import tempfile

    failures = []

    def ok(name, condition):
        print(f"{'ok  ' if condition else 'FAIL'}  {name}")
        if not condition:
            failures.append(name)

    for rule, _pattern, _why in RULES:
        sample = SAMPLES[rule]
        hits = {r for r, _p, _m in findings_in(sample, "x.txt")}
        ok(f"{rule} is found", rule in hits)

    ok("ordinary source is clean", findings_in(CLEAN, "x.py") == [])
    ok("the placeholder address is not a finding",
       findings_in("http://192.168.1.100:8777/quotes", "x.py") == [])
    ok("a camelCase name is not a key", not looks_random("anAbsentOrEmptyLanguageLeaves"))
    ok("a file path is not a key", findings_in("android/app/src/main/java/dev/bosco", "x") == [])
    ok("a git sha is hex and not a random blob",
       not looks_random(_sample("3d3c42e5aac5ba80", "5825da76410c181273ba90b1")))
    ok("prose about a token is not a finding",
       findings_in("The brapi token lives on the PC and is proxied.", "x.md") == [])
    ok("an empty value is not a finding", findings_in('brapi_token = ""', "x.toml") == [])

    ok("a keystore is caught by name", name_findings("app/release.keystore") != [])
    ok("the live config is caught by name", name_findings("server/config.toml") != [])
    ok("a task file about a keystore is not",
       name_findings("tasks/T7.1-release-keystore.md") == [])

    with tempfile.TemporaryDirectory() as tmp:
        # A throwaway repository, because this rule is the one that is a question to git
        # rather than a question about a string, and asserting it any other way would be
        # asserting that subprocess works.
        _git("init", "-q", cwd=tmp)
        (Path(tmp) / ".gitignore").write_text("*.keystore\n", encoding="utf-8")
        (Path(tmp) / "a.keystore").write_text("not a keystore\n", encoding="utf-8")
        (Path(tmp) / "b.txt").write_text("ordinary\n", encoding="utf-8")
        _git("add", "b.txt", ".gitignore", cwd=tmp)
        ok("an ignored file that is not tracked is not a finding",
           ignored_but_tracked(cwd=tmp) == [])
        _git("add", "-f", "a.keystore", cwd=tmp)
        found = ignored_but_tracked(cwd=tmp)
        ok("a tracked file that .gitignore excludes is caught",
           len(found) == 1 and found[0][1] == "a.keystore")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "allow.toml"

        def load(text):
            path.write_text(text, encoding="utf-8")
            return load_allowlist(path)

        entries, problems = load(
            '[[allow]]\nrule = "hex-blob"\npath = "a.yml"\nreason = "pinned action shas"\n')
        ok("an entry with a reason loads", len(entries) == 1 and problems == [])

        _entries, problems = load('[[allow]]\nrule = "hex-blob"\npath = "a.yml"\n')
        ok("an entry with no reason is rejected", len(problems) == 1 and "reason" in problems[0])

        _entries, problems = load('[[allow]]\nrule = "hex-blob"\nreason = "because"\n')
        ok("an entry that allows a rule everywhere is rejected",
           len(problems) == 1 and "everywhere" in problems[0])

        _entries, problems = load_allowlist(Path(tmp) / "nope.toml")
        ok("a missing allowlist is a usage error, not a pass", len(problems) == 1)

        entries, _ = load(
            '[[allow]]\nrule = "hex-blob"\npath = "a.yml"\nmatch = "abc"\nreason = "x"\n')
        found = [("hex-blob", "a.yml", "abcdef"), ("hex-blob", "b.yml", "abcdef"),
                 ("jwt", "a.yml", "abcdef")]
        ok("an entry silences only what it names", sieve(found, entries) == found[1:])

        entries, _ = load('[[allow]]\nrule = "jwt"\npath = "a.txt"\nwhere = "history"\n'
                          'reason = "x"\n')
        one = [("jwt", "a.txt", "eyJ")]
        ok("a `where = history` entry does not silence the tree",
           sieve(one, entries, "tree") == one and sieve(one, entries, "history") == [])

        _entries, problems = load(
            '[[allow]]\nrule = "jwt"\npath = "a.txt"\nwhere = "yesterday"\nreason = "x"\n')
        ok("an unknown `where` is rejected", len(problems) == 1 and "where" in problems[0])

        entries, _ = load(
            '[[allow]]\nrule = "jwt"\npath = "gone.txt"\nreason = "x"\n')
        ok("an entry naming a file that is gone is stale",
           stale(entries, {"still-here.txt"}) != [])
        ok("an entry marked history is not stale",
           stale([{"path": "gone.txt", "history": True, "reason": "x"}], set()) == [])

    # No case here reads this repository. A self-test answers whether the code is right;
    # `make check` running the guard itself answers whether the repository is. Wave 32
    # learned that the expensive way -- a case asserting "the repo is clean" is red for
    # every wave in which it is not, and `lint-selftests` stops at the first red script.

    print(f"\ncheck_secrets --self-test: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
