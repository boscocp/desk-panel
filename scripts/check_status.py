#!/usr/bin/env python3
"""Fail if tasks/STATUS.md and tasks/*.md disagree.

STATUS.md is the index an agent reads to decide what to do next. When it drifts from
the files, the agent either works on something that does not exist or skips something
that does. Three things must hold:

  - every task file has a row in the index
  - every row with an id has a file, or is listed as bootstrap work
  - every `Prereqs:` names a task that exists
  - the prerequisite graph has no cycle

Exit codes: 0 clean, 1 disagreement, 2 usage error.

Usage:
  python scripts/check_status.py [tasks_dir]
"""

import re
import sys
from pathlib import Path

ID_RE = re.compile(r"^(T\d+\.\d+|TT\.\d+)-")
ROW_RE = re.compile(r"^\|\s*(T\d+\.\d+|TT\.\d+)\s*\|", re.M)
PREREQ_RE = re.compile(r"^Size:.*?Prereqs:\s*([^·\n]+)", re.M)
# Rows kept for history: the bootstrap commits, which predate the task system.
BOOTSTRAP = {"T0.0", "T0.2", "T0.3", "T0.4"}


def task_id(path: Path) -> str:
    return ID_RE.match(path.name).group(1)


def main(argv: list[str]) -> int:
    tasks_dir = Path(argv[1]) if len(argv) > 1 else Path("tasks")
    status = tasks_dir / "STATUS.md"
    if not status.is_file():
        print(f"check_status: no such file: {status}", file=sys.stderr)
        return 2

    files = {task_id(p): p for p in sorted(tasks_dir.glob("*.md")) if ID_RE.match(p.name)}
    rows = set(ROW_RE.findall(status.read_text(encoding="utf-8")))

    problems: list[str] = []
    graph: dict[str, list[str]] = {tid: [] for tid in files}

    for tid in sorted(set(files) - rows):
        problems.append(f"{files[tid].name}: no row in STATUS.md")
    for tid in sorted(rows - set(files) - BOOTSTRAP):
        problems.append(f"STATUS.md: row {tid} has no task file")

    for tid, path in sorted(files.items()):
        m = PREREQ_RE.search(path.read_text(encoding="utf-8"))
        if not m:
            continue
        # Parenthetical asides are prose, not dependencies.
        declared = re.sub(r"\([^)]*\)", "", m.group(1))
        for dep in (d.strip() for d in declared.split(",")):
            dep = dep.split()[0].strip("`") if dep else ""
            if not dep or dep.lower() in {"none", "-"}:
                continue
            if dep not in files:
                problems.append(f"{path.name}: prereq {dep} does not exist")
            else:
                graph[tid].append(dep)

    # A cycle is how T4.1 and T4.2 each ended up waiting on the other: T4.1's
    # acceptance needed a native caller, and the only caller declared T4.1 as its
    # prerequisite. Existence checks do not catch that.
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {tid: WHITE for tid in graph}

    def walk(tid: str, path: list[str]) -> None:
        colour[tid] = GREY
        for dep in graph[tid]:
            if colour.get(dep) == GREY:
                cycle = path[path.index(dep):] if dep in path else [dep]
                problems.append("cycle in prereqs: " + " -> ".join(cycle + [tid, dep]))
            elif colour.get(dep) == WHITE:
                walk(dep, path + [tid])
        colour[tid] = BLACK

    for tid in sorted(graph):
        if colour[tid] == WHITE:
            walk(tid, [])

    for problem in problems:
        print(f"  {problem}")
    if problems:
        print(f"\ncheck_status: FAIL - {len(problems)} disagreements")
        return 1
    print(f"check_status: OK - {len(files)} task files, {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
