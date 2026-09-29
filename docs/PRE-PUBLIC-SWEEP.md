# The pre-public sweep

**What is in this repository, and what a clone gets.** Run on 2026-09-28, before
[T7.3](../tasks/T7.3-pre-public-review.md) and before
[T7.7](../tasks/T7.7-open-to-community.md) makes the repository public.

This is not a claim that the repository is clean. It is the answer to the question a
stranger should be able to ask — *do the people who published this know what is in it* —
and the list below is what they knew.

## How it was looked at

| | command | covers |
|---|---|---|
| the tree | `python scripts/check_secrets.py` | the 332 tracked files a clone checks out |
| the history | `python scripts/check_secrets.py --history` | all 1,935 blobs in the pack, reachable from any ref |
| words | `git log -p \| grep -iE "token\|password\|keystore\|api[_-]?key"` | T7.3 step 1, kept |

The two halves are reported apart and exit differently **because they have different
remedies**. A finding in the tree is fixed by deleting it. A finding in the history is in
every clone already, so the remedy is *rotate the credential* — deleting it now changes
nothing, and rewriting published history is a force-push, which is a person's decision and
not a script's.

`make check` runs the tree half on every save. CI runs both, and the history half gets its
own job for one reason: it needs `fetch-depth: 0`. The guards job fetches thirty commits,
and a sweep of "the history" over a shallow clone is a green tick that means "we looked at
the last thirty".

### The scanner was proved before it was trusted

A secret scanner that has never found anything is indistinguishable from one that cannot.
Two fake credentials — an AWS example key and a `ghp_` string that opens nothing — were
committed to a throwaway branch, **deleted in a following commit**, and the history half
reported both, named the blob, and exited 3. The branch was then deleted and the sweep went
green. That is the property the whole task is about: `git rm` removes nothing from a clone.

## What the sweep found

**No credential, in the tree or in the history.** Everything below is deliberate, and every
one of them is allowed in [`scripts/secrets-allowlist.toml`](../scripts/secrets-allowlist.toml)
with a reason — the file format refuses an entry without one, because an allowlist of bare
patterns is a guard turned off with extra steps.

### Deliberately kept

Everything in this table is **deliberately kept**: it was looked at on 2026-09-28 and the
decision was to publish it.

| what | where | why it stays |
|---|---|---|
| **The PC's real LAN address**, `192.168.15.3` | Markdown only: ADRs, `SERVER-SETUP.md`, `BUILD.md`, harness notes, `STATUS.md`, task files | ADR 0013 is *about* this machine not being a placeholder, and the notes are a record of what was measured. An RFC1918 address is not reachable from outside the LAN it names. Rewriting a record to look tidier is how a record stops being worth keeping |
| **The phone's adb serial**, `303f1f9c` | `tasks/STATUS.md`, three times | A USB serial. It addresses nothing over a network, and the lines it appears in are the measurements that make those entries worth reading |
| **Home paths and the owner's names** — `/home/bosco`, `/Users/bosco`, `C:\Users\Adalberto`, `D:\projetos-vscode` | `server/fixtures/login_scope/*` | Captured command output, realistic on purpose: TT.10's argument is that a fixture with invented shapes proves less than one taken from a real machine, and the macOS half is only checkable at all because of it. The same names are in every commit's author line already |
| **The author's name and email** | every one of the 162 commits | `Adalberto Pereira <adalbertobosco@gmail.com>`. Going public publishes it. Changing it now would mean rewriting every commit; changing it going forward is a `git config` away and is the owner's call, recorded here so it is a choice rather than a discovery |
| **Pinned dependency digests** — action SHAs, the Docker base image, the Gradle distribution checksum | `.github/workflows/*.yml`, `docker/Dockerfile`, `gradle-wrapper.properties` | Publishing them is their entire purpose. `check_ci_hygiene.py` rule 3 *requires* the action pins |
| **`super-secret-token`** | `server/tests/test_config_format.py` | The obviously-fake value that test asserts is not echoed back by the config endpoint. A test about not leaking a token needs a token-shaped string to not leak |
| **A container id** | `server/fixtures/login_scope/linux_cgroup_v1_docker.txt` | 64 hex characters of captured `/proc/self/cgroup`. The container is long gone and an id is not a credential |
| **`WINDOWS-NEXT-SESSION.md`** at the root | tracked | Live triage for [T3.8](../tasks/T3.8-windows-autostart.md), which is still `blocked`. The file says on its first line that it is temporary and names the condition for deleting it. Publishing a session hand-off note is odd; deleting live triage to look tidier is worse. **T7.3 re-checks it**, and if T3.8 is still blocked then, it ships |

### Changed by this sweep

- **`192.168.15.3` is out of source.** It was in `ActionsTest.java` and `server/tests/test_actions.py`
  as an arbitrary host string in assertions — not load-bearing in either, and both are files
  T7.3's own grep line reads because that line excludes `docs` and `*.md` but not source.
  Both now use the placeholder `192.168.1.100`, and the 362 server tests and the Android JVM
  suite pass unchanged.
  It is **still in the history of both files**, and the sweep says so rather than
  pretending otherwise: the old blobs are in the pack of every clone, and the allowlist
  carries two entries marked `where = "history"` explaining that this is accepted rather
  than unnoticed. The `where` field exists for exactly this — a decision may differ
  between the two halves, and "we took it out of the tree" is not the same statement as
  "it was never there". Removing it from history would buy nothing, since the same address
  is deliberately published in twenty Markdown files, and would cost a force-push over
  published commits.
- **Seven stale `.gitkeep` files are gone** — `docker/`, `web/css/`, `web/js/`, `web/test/`,
  `server/tests/fixtures/`, `android/app/src/main/res/xml/` and
  `android/app/src/test/java/dev/bosco/deskpanel/` all have tracked content now, so the
  placeholder was keeping an empty directory that has not been empty for weeks. The one in
  `androidTest/` stays: that directory really is empty until TT.7 lands.

### Looked for and not found

Each of these is a command that will keep saying so:

- No `-----BEGIN … PRIVATE KEY-----`, no `ssh-rsa`, no JWT, no `AKIA…`, no `ghp_…`, no
  `xox…`, no `AIza…`, no bearer header, in the tree or in any blob in the history.
- No `config.json`, `config.toml`, `*.keystore`, `*.jks`, `keystore.properties`, `.env`,
  `*.pem` or `*.key` has ever been committed, under any name, in any commit. The only hit
  for the word is `tasks/T7.1-release-keystore.md`, which is a task file.
- **Nothing tracked that `.gitignore` excludes.** `git add -f` and a rename past a rule both
  do that silently, and the first five lines of `.gitignore` are the secret files.
- No `TODO`, `FIXME` or `XXX:` marker in any source file. This project puts unfinished
  business in `tasks/`, so one in the code would be either stale or a task nobody filed.
- **The brapi token appears nowhere** — not in a fixture, a test, a doc example or a
  comment. It lives in `server/config.toml` on the PC, which is gitignored, and the phone
  never sees it (ADR 0004).

## What this sweep does not cover

- **Screenshots.** [T7.3](../tasks/T7.3-pre-public-review.md) step 4 owns them, and there
  are no image files in the repository today to check.
- **The binary blob.** `android/gradle/wrapper/gradle-wrapper.jar` is not read by the
  scanner — it is not text. It is Gradle's own vendored wrapper, pinned by the checksum in
  `gradle-wrapper.properties`.
- **Whether a string that is not shaped like a credential is one.** A scanner reads shapes.
  A password that looks like a word goes through it, and the only defence against that is
  the rule this project already follows: secrets live in gitignored files on the PC.
- **What GitHub does after the push.** Secret scanning and push protection are worth turning
  on in T7.7 and are not a substitute for this: they run *after* the push, and the push is
  the thing that cannot be undone.

## Keeping it true

`make check` runs the tree half, so a credential added tomorrow fails the build before it is
committed. CI runs the history half on every push. Both halves are in
[`scripts/check_secrets.py`](../scripts/check_secrets.py), whose `--self-test` proves each of
its rules can fail — 31 cases, every one of them hermetic.

When a finding is deliberate, add it to the allowlist **with the reason**, and add the
decision to the table above. A row here is what makes the answer checkable a year from now.
