#!/usr/bin/env python3
"""Fail if .claude/settings.json and reasonix.toml have drifted apart.

The two permission files are declared twins by three separate documents -
CLAUDE.md, docs/LOCAL-MODELS.md and ADR 0011 - because Reasonix deliberately does
not read settings.json. They drifted within one PR of being declared twins, which
is why this is a script and not a fourth sentence asking people to remember.

The dialects differ, so the comparison is between normalised rules, not strings:

  - `Bash(cmd:*)` (Reasonix) and `Bash(cmd *)` (Claude Code) and `Bash(cmd)` all
    reduce to the command prefix `cmd`.
  - `Edit(./path)` and `Edit(path)` reduce to `path`.
  - `Read(...)` has NO Reasonix equivalent - its reader is `read_file`, and a
    copied `Read(...)` rule is silently inert. The mapping is onto `[sandbox]
    forbid_read`, which is stronger anyway because it also blocks `cat`. Each
    forbid_read entry is therefore compared as if it were a `Read(...)` deny.

An asymmetry that is meant is declared in reasonix.toml, as a comment:

    # parity: intentional <rule> <why>

The rule is matched against normalised keys with glob semantics, so one
`WebFetch(domain:*)` marker covers every domain and `Bash(docker *)` covers a
family. The reason is required - an exemption that cannot be argued is drift
wearing a marker. The markers live in reasonix.toml because JSON has no
comments, so the JSON twin could not carry the reason next to the rule.

Not every asymmetry is drift, and the difference matters. Reasonix allows
`Bash(cat:*)` safely because `[sandbox] forbid_read` blocks the secret files
underneath it; Claude Code has no such layer, so the same rule there would walk
past its own `Read(...)` denies. That one is a difference in the harnesses and
is declared, not repaired.

An exemption that matches nothing is reported too: the asymmetry it was written
for is gone, and the marker now hides whatever lands on that rule next.

Exit codes: 0 clean, 1 asymmetries found, 2 usage or parse error.

Usage:
  python scripts/check_permission_parity.py [--settings PATH] [--reasonix PATH]
  python scripts/check_permission_parity.py --selftest
"""

import json
import re
import sys
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

SETTINGS = Path(".claude/settings.json")
REASONIX = Path("reasonix.toml")

RULE_RE = re.compile(r"^(?P<tool>[A-Za-z0-9_]+)\((?P<target>.*)\)$", re.S)
BARE_RE = re.compile(r"^[A-Za-z0-9_]+$")
MARKER_RE = re.compile(
    r"#\s*parity:\s*intentional\s+"
    # `Tool(target)`, or a bare tool name - the same two shapes a rule may take.
    r"(?P<rule>[A-Za-z0-9_]+\([^)]*\)|[A-Za-z0-9_]+)\s*(?P<why>.*?)\s*$",
    re.M,
)

CLAUDE, RX = ".claude/settings.json", "reasonix.toml"


def normalise(rule: str, *, pattern: bool = False) -> tuple[str, str] | None:
    """Reduce a rule to (tool, target) in whichever dialect it was written.

    `pattern=True` is for a parity marker, whose target stays a glob: stripping
    the wildcard would leave `Bash(docker *)` matching only the literal command
    `docker`, so a marker written for a family of rules would cover none of them.

    Two limitations, both deliberate and both real blind spots:

      - A rule with no wildcard is an exact match in Claude Code and a prefix in
        Reasonix, and this reduces both to the same key. `Bash(adb devices)` and
        `Bash(adb devices:*)` are reported as paired although `adb devices -l`
        prompts on one side and not the other.
      - A command missing from BOTH files is symmetric, so nothing here sees it.
        That gap is covered by reading the `## Acceptance` blocks instead, which
        is how `sleep` was found in 27 criteria and neither allow list.
    """
    rule = rule.strip()

    # A bare tool name (`WebSearch`) or an MCP rule (`mcp__server__tool`) is a
    # legal Claude Code entry. It carries no target, and it is NOT a parse
    # error: a gate that goes red when someone adds WebSearch is a gate people
    # rip out. It compares as itself, and can be exempted like anything else.
    if BARE_RE.match(rule):
        return rule, ""

    m = RULE_RE.match(rule)
    if not m:
        return None
    tool, target = m.group("tool"), m.group("target").strip()

    if tool == "Bash":
        if not pattern:
            for tail in (":*", " *", "*"):
                if target.endswith(tail):
                    target = target[: -len(tail)]
                    break
        return "Bash", " ".join(target.split())

    if tool in ("Read", "Edit", "Write"):
        while target.startswith("./"):
            target = target[2:]
        return tool, target

    return tool, target


def key_str(key: tuple[str, str]) -> str:
    return f"{key[0]}({key[1]})"


def load_settings(path: Path) -> tuple[set, set, list[str]]:
    """Claude Code's side: permissions.allow and permissions.deny."""
    problems: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    perms = data.get("permissions", {})
    out = []
    for field in ("allow", "deny"):
        keys = set()
        for rule in perms.get(field, []):
            key = normalise(rule)
            if key is None:
                problems.append(f"{path}: unparseable {field} rule {rule!r}")
                continue
            keys.add(key)
        out.append(keys)
    return out[0], out[1], problems


def load_reasonix(path: Path) -> tuple[set, set, list[tuple], list[str]]:
    """Reasonix's side. forbid_read is folded into deny as Read(...) rules."""
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    perms = data.get("permissions", {})

    out = []
    for field in ("allow", "deny"):
        keys = set()
        for rule in perms.get(field, []):
            key = normalise(rule)
            if key is None:
                problems.append(f"{path}: unparseable {field} rule {rule!r}")
                continue
            # The one rule that looks right and does nothing. Reasonix's reader
            # is read_file, so a Read(...) here is silently inert - and pairing
            # it against its settings.json twin would make this script bless the
            # very hole it exists to find: move server/config.json out of
            # forbid_read into a Read(...) deny and the token is readable by
            # `cat` again, with the gate still green.
            if key[0] == "Read":
                problems.append(
                    f"{path}: {rule!r} does nothing - Reasonix's reader is read_file, "
                    "so a Read(...) rule is silently inert. Put the path in "
                    "[sandbox] forbid_read, which also blocks `cat`"
                )
                continue
            keys.add(key)
        out.append(keys)
    allow, deny = out

    for entry in data.get("sandbox", {}).get("forbid_read", []):
        deny.add(("Read", entry))

    exemptions = []
    for m in MARKER_RE.finditer(text):
        key = normalise(m.group("rule"), pattern=True)
        if key is None:
            problems.append(f"{path}: unparseable parity marker {m.group('rule')!r}")
            continue
        why = m.group("why").strip()
        if not why:
            problems.append(
                f"{path}: parity marker {m.group('rule')} carries no reason - "
                "an exemption that cannot be argued is drift wearing a marker"
            )
            continue
        exemptions.append((key, why))

    return allow, deny, exemptions, problems


def exempt_for(key: tuple[str, str], exemptions: list[tuple]) -> tuple | None:
    for entry in exemptions:
        pattern = entry[0]
        if pattern[0] == key[0] and fnmatchcase(key[1], pattern[1]):
            return entry
    return None


def compare(c_allow, c_deny, r_allow, r_deny, exemptions) -> list[str]:
    """Report every asymmetry between the two sides that is not exempt."""
    problems: list[str] = []
    used: set = set()

    def record(key, message):
        entry = exempt_for(key, exemptions)
        if entry is not None:
            used.add(entry[0])
            return
        problems.append(message)

    # A rule allowed on one side and denied on the other is one fact, not three.
    # Report it as the conflict it is and keep it out of the plain diffs below.
    conflicts = (c_allow & r_deny) | (r_allow & c_deny)
    for key in sorted(conflicts):
        allowed, denied = (CLAUDE, RX) if key in c_allow else (RX, CLAUDE)
        record(key, f"{key_str(key)}: allowed in {allowed}, denied in {denied}")

    for field, claude_side, rx_side in (
        ("allow", c_allow, r_allow),
        ("deny", c_deny, r_deny),
    ):
        for key in sorted(claude_side - rx_side - conflicts):
            record(key, f"{key_str(key)}: in {CLAUDE} {field}, missing from {RX}")
        for key in sorted(rx_side - claude_side - conflicts):
            record(key, f"{key_str(key)}: in {RX} {field}, missing from {CLAUDE}")

    for key, why in exemptions:
        if key not in used:
            problems.append(
                f"{key_str(key)}: exempted ({why}) but nothing is asymmetric - "
                "the marker now hides whatever lands on that rule next"
            )

    return problems


def run(settings: Path, reasonix: Path) -> int:
    for path in (settings, reasonix):
        if not path.is_file():
            print(f"check_permission_parity: no such file: {path}", file=sys.stderr)
            return 2

    try:
        c_allow, c_deny, c_problems = load_settings(settings)
        r_allow, r_deny, exemptions, r_problems = load_reasonix(reasonix)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"check_permission_parity: {exc}", file=sys.stderr)
        return 2

    if c_problems or r_problems:
        for line in c_problems + r_problems:
            print(f"  {line}", file=sys.stderr)
        return 2

    problems = compare(c_allow, c_deny, r_allow, r_deny, exemptions)
    if problems:
        print(f"check_permission_parity: {len(problems)} asymmetry(ies)", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print(
            "\n  the two files are twins - see docs/LOCAL-MODELS.md for what maps and what\n"
            "  does not, and add `# parity: intentional <rule> <why>` in reasonix.toml for\n"
            "  an asymmetry that is meant",
            file=sys.stderr,
        )
        return 1

    paired = len(c_allow & r_allow) + len(c_deny & r_deny)
    print(
        f"check_permission_parity: {paired} rule(s) paired, "
        f"{len(exemptions)} intentional asymmetry(ies)"
    )
    return 0


def selftest() -> int:
    """Prove the checker can fail. An always-green check is not a check.

    CLAUDE.md's rule for task files - a criterion the shell can settle - applies
    to the checker itself: run against drifted fixtures it must name the drift.
    """
    import tempfile

    settings = {
        "permissions": {
            "allow": [
                "Bash(make check)",
                "Bash(curl *)",
                "Bash(git commit *)",
                "Bash(docker compose build *)",
                "WebSearch",
                "mcp__playwright__browser_navigate",
            ],
            "deny": ["Read(./server/config.json)", "Edit(./.env)"],
        }
    }
    reasonix = """
# parity: intentional Bash(git commit*) publication is Claude's
# parity: intentional Bash(docker *) the family marker: a glob must reach past one command
# parity: intentional WebSearch no Reasonix equivalent
# parity: intentional mcp__playwright__browser_navigate no Reasonix equivalent
# parity: intentional Bash(nothing:*) stale, matches no asymmetry
[permissions]
allow = ["Bash(make check:*)", "Bash(sleep:*)"]
deny = ["Bash(git commit*)", "Edit(.env)"]
[sandbox]
forbid_read = ["server/config.json"]
"""
    expected = {
        "Bash(curl): in .claude/settings.json allow, missing from reasonix.toml",
        "Bash(sleep): in reasonix.toml allow, missing from .claude/settings.json",
        "Bash(nothing:*): exempted",
    }

    with tempfile.TemporaryDirectory() as tmp:
        sp, rp = Path(tmp) / "settings.json", Path(tmp) / "reasonix.toml"
        sp.write_text(json.dumps(settings), encoding="utf-8")
        rp.write_text(reasonix, encoding="utf-8")

        c_allow, c_deny, c_problems = load_settings(sp)
        r_allow, r_deny, exemptions, _ = load_reasonix(rp)
        problems = compare(c_allow, c_deny, r_allow, r_deny, exemptions)

        # A Read(...) rule in Reasonix's permission list looks right and does
        # nothing. It must be refused, not paired.
        inert = Path(tmp) / "inert.toml"
        inert.write_text('[permissions]\ndeny = ["Read(server/config.json)"]\n', encoding="utf-8")
        _, _, _, inert_problems = load_reasonix(inert)

    failures = []
    for want in expected:
        if not any(p.startswith(want) for p in problems):
            failures.append(f"did not report: {want}")
    # Paired, or exempt. A bare tool name and an MCP rule are legal Claude Code
    # entries: they must compare, not blow the gate up as parse errors.
    for unwanted in (
        "Bash(make check)",
        "Read(server/config.json)",
        "Edit(.env)",
        "Bash(docker compose build)",
        "WebSearch()",
        "mcp__playwright__browser_navigate()",
    ):
        if any(p.startswith(f"{unwanted}:") for p in problems):
            failures.append(f"reported a rule that is paired or exempt: {unwanted}")
    if c_problems:
        failures.append(f"treated a legal Claude Code rule as unparseable: {c_problems}")
    if not any("silently inert" in p for p in inert_problems):
        failures.append("accepted a Read(...) rule in reasonix.toml's permission list")

    if failures:
        print("check_permission_parity: SELFTEST FAILED", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        print("  it reported:", file=sys.stderr)
        for line in problems:
            print(f"    {line}", file=sys.stderr)
        return 1

    print(f"check_permission_parity: selftest OK - {len(problems)} drift(s) caught in fixtures")
    return 0


def main(argv: list[str]) -> int:
    settings, reasonix = SETTINGS, REASONIX
    args = argv[1:]
    while args:
        flag = args.pop(0)
        if flag == "--selftest":
            return selftest()
        if not args:
            print(f"check_permission_parity: {flag} needs a value", file=sys.stderr)
            return 2
        value = args.pop(0)
        if flag == "--settings":
            settings = Path(value)
        elif flag == "--reasonix":
            reasonix = Path(value)
        else:
            print(f"check_permission_parity: unknown option {flag}", file=sys.stderr)
            return 2

    return run(settings, reasonix)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
