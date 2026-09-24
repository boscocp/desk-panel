# Read this when you are on the Windows PC

**Temporary.** Written 2026-09-23 from the Linux box, after the report that *the panel did not
come up by itself when Windows was turned on*, while on CachyOS it does. Delete this file once
the cause is found and T3.8 is unblocked — it is a triage script, not documentation.

## What to tell Claude on the Windows side

> Read `WINDOWS-NEXT-SESSION.md` and work through it. The Scheduled Task did not start the
> server at logon.

## What is known here, and what is not

- The Linux carrier works: `server/install_user_unit.sh`, systemd user unit bound to
  `graphical-session.target` (T3.9, wave 18). That is why CachyOS behaves.
- On Windows the task **was** registered and verified once, on **2026-09-19**: it answered
  `/ping` on `127.0.0.1:8777` and `server/verify_login_scope.py` exited 0 with eleven PASS.
- **T3.12 landed on 2026-09-20, one day later**, and moved config to `server/config.toml`.
  The installer bakes an *absolute* `--config <path>` into the task action, so a task
  registered on the 19th still names `server\config.json`. See the trap below.
- Nothing about the current state of the Windows machine is known from here. Every line below
  is a question to ask it, not a fact.

## The trap to check first

`docs/SERVER-SETUP.md` ("If you already have a `config.json`") records this exact failure:

> Deleting the `config.json` breaks the panel: the server exits 1 at every logon, under
> `pythonw`, with no console to say why, and the phone reports offline forever —
> indistinguishable from the DHCP-drift failure.

So if `server/config.json` was tidied away after the TOML migration, the task still fires, the
process still starts, and it dies immediately and silently. That is the first hypothesis, and
it is cheap to settle: read the path the task actually passes and check the file is there.

Wave 19's lesson applies — **read the switch before the mechanism.** Settle "is it even
registered, and what did it return" before reasoning about triggers.

## Start with the script that now exists

Wave 20 (PR #25, merged 2026-09-22 from another session) added exactly the tool for this:

```powershell
git pull
python scripts/after_update.py
```

Read [`docs/UPDATING.md`](docs/UPDATING.md) if it fails. It finds the Scheduled Task, reads the
paths the task was **actually registered with** rather than guessing, runs `--check-only`
against that config, restarts through the launcher, and compares `/weather` against the key set
the tree's own `normalise()` produces. Exit 0 means every check this OS could run passed, 1
means something is really wrong, 2 means something could not be determined.

If it answers cleanly and the panel still did not come up at logon, the trigger itself is the
suspect and the list below is the next step. If it fails, its report names the step — go
straight to that row of the table.

## Triage, in order. Each line is an exit code or one field.

Run from the repository root, in PowerShell.

```powershell
# 1. Does the task exist at all on THIS machine and THIS checkout?
schtasks /Query /TN "desk-panel"

# 2. What happened at the last logon? LastTaskResult 0 = ran and exited fine,
#    267011 = never run. Anything else is the server's own exit code.
Get-ScheduledTaskInfo -TaskName "desk-panel" | Format-List TaskName, LastRunTime, LastTaskResult, NumberOfMissedRuns

# 3. Which config and which interpreter did it bake in? Check both paths exist.
([xml](Export-ScheduledTask -TaskName 'desk-panel')).Task.Actions.Exec | Format-List Command, Arguments, WorkingDirectory

# 4. The server's own log. It is the only place a pythonw crash leaves a trace.
Get-Content "$env:LOCALAPPDATA\desk-panel\server.log" -Tail 40

# 5. Is it answering right now?
python server\probe.py --host 127.0.0.1 --expect up

# 6. Is the scope still right (not a service in disguise)?
python server\verify_login_scope.py
```

Then, by what those five said:

| Symptom | Likely cause | Fix |
|---|---|---|
| (1) task not found | never installed on this checkout, or installed from a different folder | re-run the installer, below |
| (3) names a `config.json` that is gone | the TOML migration trap above | re-run the installer; it picks `config.toml` first |
| (3) names a Python under `WindowsApps\` or inside a deleted venv | interpreter drift | `-Python <abs path>` on the installer |
| (4) log ends in a traceback | a real server bug — read it, it is not an autostart problem | fix the server |
| (5) up, but the phone still says offline | firewall or DHCP drift, **not** autostart | `-FirewallOnly`, and check the pinned IP |
| (2) `LastRunTime` empty after a login | the trigger genuinely did not fire | re-register, then test across a *real* reboot and a Fast Startup one |

Re-registering is idempotent and is usually the whole fix:

```powershell
powershell -ExecutionPolicy Bypass -File server\install_task.ps1
```

Do **not** run that elevated to get the firewall rule — it would re-register the task for
whichever account elevated. Use a separate elevated shell with `-FirewallOnly`.

## Two things that are correct and look like bugs

- **Answering at the lock screen is correct.** Locked is not logged out; an at-logon task is
  supposed to keep answering through Win+L. `docs/SERVER-SETUP.md` reads as if this were the
  bug. It is not.
- **Not answering before anyone logs in is the entire point** (invariant 2, ADR 0010). If the
  fix under consideration is "make it a Windows Service", stop — that is the one change this
  project exists to refuse.

## What would close T3.8

Its blocked half is four probes from **another device on the LAN**, not from `localhost`:

```bash
# 1. reboot the PC, do NOT log in, wait 90s
python server/probe.py --host <pc-ip> --expect down
# 2. log in, wait 60s
python server/probe.py --host <pc-ip> --expect up
# 3. LOCK the PC (Win+L), wait 15s
python server/probe.py --host <pc-ip> --expect up
# 4. log OFF, wait 30s
python server/probe.py --host <pc-ip> --expect down
```

If that session happens anyway, run them and T3.8 stops being blocked. Step 1 is the invariant;
step 3 is the mistake in the other direction. The full task file is
[`tasks/T3.8-windows-autostart.md`](tasks/T3.8-windows-autostart.md).
