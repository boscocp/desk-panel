#!/usr/bin/env python3
"""Fail if `.claude/settings.json` and `reasonix.toml` have drifted apart.

The two files are one permission policy written twice, because Reasonix does not
read settings.json (`internal/config/paths.go`, ConventionDirs) and Claude Code
does not read reasonix.toml. Three separate documents declare them a maintained
pair -- CLAUDE.md, docs/LOCAL-MODELS.md and ADR 0011 -- and they drifted inside
the PR that declared it. This is that rule with an exit code instead.

What it compares, after normalising each rule to (tool, command prefix):

  * the allow lists,
  * the deny lists,
  * Claude's `Read(path)` denies against Reasonix's `[sandbox] forbid_read`,
    which is the mechanism that replaces them -- a `Read(...)` rule copied into
    reasonix.toml is silently inert, so the pairing has to be made here.

Spelling is not the subject. `Bash(make check)`, `Bash(make check *)` and
`Bash(make check:*)` all normalise to the same rule, because the question is
whether one agent can run a command family the other cannot, not whether the
two harnesses punctuate alike.

Asymmetries that are deliberate are declared in reasonix.toml, in a comment:

    # parity: intentional -- Bash(git commit:*), Bash(git push:*): git belongs
    # to the reviewing agent (ADR 0011).

Every `Tool(spec)` token in that comment block is exempt. A declaration that no
longer describes a real asymmetry is reported too: a stale exemption hides the
next drift behind a rule nobody re-read.

Exit codes: 0 in step, 1 drift or a stale exemption, 2 usage or parse error.

Usage:
  python scripts/check_permission_parity.py [--settings PATH] [--reasonix PATH]
"""

import json
import re
import sys
import tomllib
from pathlib import Path

# The opening line of a declared-asymmetry comment block in reasonix.toml.
MARKER_RE = re.compile(r"#.*\bparity:\s*intentional\b", re.I)


def normalise(rule: str) -> tuple[str, str]:
    """`Bash(make check:*)`, `Bash(make check *)` and `Bash(make check)` are one rule."""
    text = rule.strip()
    match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)\s*(?:\((.*)\))?", text, re.S)
    if not match:
        raise ValueError(f"unparseable permission rule: {rule!r}")
    tool = match.group(1)
    spec = (match.group(2) or "").strip()
    if spec.startswith("./"):
        spec = spec[2:]
    if spec.endswith("*"):
        spec = spec[:-1]
    # Bash(cmd:*) leaves a colon behind where Bash(cmd *) leaves a space.
    spec = spec.rstrip(": ")
    return tool, spec


def show(rule: tuple[str, str]) -> str:
    tool, spec = rule
    return f"{tool}({spec})" if spec else tool


def read_exemptions(text: str) -> set[tuple[str, str]]:
    """Every `Tool(spec)` named in a `# parity: intentional` comment block.

    A block is the marker line plus the comment lines that follow it, so a
    declaration may wrap over as many lines as its reason needs.
    """
    exempt: set[tuple[str, str]] = set()
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if not MARKER_RE.search(lines[index]):
            index += 1
            continue
        block = [lines[index]]
        index += 1
        while index < len(lines) and lines[index].lstrip().startswith("#"):
            block.append(lines[index])
            index += 1
        joined = " ".join(block)
        for tool, spec in re.findall(r"([A-Za-z_][A-Za-z_0-9]*)\(([^)]*)\)", joined):
            exempt.add(normalise(f"{tool}({spec})"))
    return exempt


def main(argv: list[str]) -> int:
    settings_path = Path(".claude/settings.json")
    reasonix_path = Path("reasonix.toml")

    args = argv[1:]
    while args:
        flag = args.pop(0)
        if not args:
            print(f"check_permission_parity: {flag} needs a value", file=sys.stderr)
            return 2
        value = args.pop(0)
        if flag == "--settings":
            settings_path = Path(value)
        elif flag == "--reasonix":
            reasonix_path = Path(value)
        else:
            print(f"check_permission_parity: unknown option {flag}", file=sys.stderr)
            return 2

    for path in (settings_path, reasonix_path):
        if not path.is_file():
            print(f"check_permission_parity: no such file: {path}", file=sys.stderr)
            return 2

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        raw_reasonix = reasonix_path.read_text(encoding="utf-8")
        reasonix = tomllib.loads(raw_reasonix)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"check_permission_parity: {error}", file=sys.stderr)
        return 2

    claude_perms = settings.get("permissions", {})
    reasonix_perms = reasonix.get("permissions", {})
    forbid_read = reasonix.get("sandbox", {}).get("forbid_read", [])

    try:
        claude_allow = {normalise(r) for r in claude_perms.get("allow", [])}
        claude_deny = {normalise(r) for r in claude_perms.get("deny", [])}
        reasonix_allow = {normalise(r) for r in reasonix_perms.get("allow", [])}
        reasonix_deny = {normalise(r) for r in reasonix_perms.get("deny", [])}
        # forbid_read is the mechanism that stands in for Claude's Read denies.
        reasonix_deny |= {normalise(f"Read({path})") for path in forbid_read}
        exempt = read_exemptions(raw_reasonix)
    except ValueError as error:
        print(f"check_permission_parity: {error}", file=sys.stderr)
        return 2

    asymmetric: set[tuple[str, str]] = set()
    problems: list[str] = []

    for label, claude_side, reasonix_side in (
        ("allow", claude_allow, reasonix_allow),
        ("deny", claude_deny, reasonix_deny),
    ):
        for rule in sorted(claude_side - reasonix_side):
            asymmetric.add(rule)
            if rule not in exempt:
                problems.append(
                    f"{label}: {show(rule)} is in {settings_path} and not in {reasonix_path}"
                )
        for rule in sorted(reasonix_side - claude_side):
            asymmetric.add(rule)
            if rule not in exempt:
                problems.append(
                    f"{label}: {show(rule)} is in {reasonix_path} and not in {settings_path}"
                )

    for rule in sorted(exempt - asymmetric):
        problems.append(
            f"stale exemption: {show(rule)} is declared intentional in {reasonix_path} "
            f"but the two files agree about it - delete the declaration"
        )

    if problems:
        print(f"{len(problems)} permission parity problem(s):\n")
        for problem in problems:
            print(f"  {problem}")
        print(
            "\nAdd the rule to the other file, or declare the asymmetry in "
            f"{reasonix_path} with a `# parity: intentional` comment naming it."
        )
        return 1

    shared = len(claude_allow & reasonix_allow) + len(claude_deny & reasonix_deny)
    print(
        f"permission parity: {shared} rules in both files, "
        f"{len(exempt)} asymmetries declared intentional"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
