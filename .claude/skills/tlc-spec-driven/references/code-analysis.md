# Code Analysis Tools

Claude Code ships the search tools; use them instead of shelling out.

## Tool Priority

1. **`Grep`** - ripgrep under the hood. Content search with `pattern`, `glob`/`type`, and
   `output_mode` (`files_with_matches` to locate, `content` with `-A`/`-B`/`-C` to read hits).
   This is the default for "where is X used".
2. **`Glob`** - path search by pattern (`web/js/**/*.js`, `**/*Test.java`). Use it to find files
   by name or layout, never `find` in a Bash call.
3. **`Read`** - once the search narrowed things down. Read the file, not a grep window, before
   changing it.
4. **`Bash`** only for what the tools above cannot do: `git log -S`, `git diff`, `git grep` over
   history, or piping into `sort`/`uniq -c` for counts.

`ast-grep` (`sg`) is worth reaching for on a large structural refactor, but it is not installed
here and is not a dependency of this skill. Check with `command -v sg` before suggesting it, and
never make a step depend on it.

## Scope

This repo is small and has no vendored dependency trees, so unscoped searches are cheap. Still
scope by layer, because the layers are genuinely separate:

- `web/` - plain HTML/CSS/JS, no build step (`web/js/format.js` holds the pure functions)
- `android/` - Java, one Activity
- `server/` - Python 3.13, standard library only
- `e2e/`, `tasks/`, `docs/adr/`

Exclude build output (`build/`, `out/`, `.gradle/`) - it is gitignored but still on disk after a
Docker build.

## When to Use

- Finding usage patterns across a layer
- Locating a function, class, or Activity before editing it
- Tracing which layer owns a behaviour (the same concept often appears in `web/`, `android/` and
  `server/` under different names)
- Refactoring impact analysis
