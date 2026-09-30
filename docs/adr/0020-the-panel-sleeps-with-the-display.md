# 0020 — The panel sleeps with the PC's display, not only with the login

Status: accepted · 2026-09-30 (T4.6)
Amends [ADR 0004](0004-server-is-login-signal-and-proxy.md), which made "the server answers" the
whole signal, and [ADR 0016](0016-more-than-one-pc.md), whose "online means some host answered"
now reads "some host answered with its display on".

## Context

The panel is lit while somebody is logged in at the PC (invariant 2). A PC left logged in with
its monitor asleep, whether from the power plan's idle timer or put to sleep by hand, still
answers `/ping`. So the phone beside it stayed lit all night, in front of nobody. The owner asked
for the panel to go dark with the PC's screen.

Two ways to do that were on the table:

- **A timeout on the phone**, such as "no touch for N minutes". Invariant 3 forbids it: screen
  state is driven by PC state, never by a timeout. The phone also cannot see the owner at the PC.
- **The PC reports its display.** The PC already decides when its own monitor sleeps, from the
  owner's power plan. The panel following that decision is invariant 3 applied, not bent.

Invariant 2 makes the second one possible. The server runs inside the owner's graphical session,
so it can ask that session about its display. A Windows Service, a systemd system unit or a
LaunchDaemon could not; they have no display to ask about. This is one more reason the class
ADR 0010 forbids is wrong.

## Decision

- **`/ping` carries the display**: `{"ok": true, "display": "on" | "off" | "unknown"}`.
  Answering still means somebody is logged in; `display` says whether anybody is looking.
  `server/display.py` reads it:
  - **Windows:** `GUID_CONSOLE_DISPLAY_STATE`, received as `WM_POWERBROADCAST` on a hidden
    window with its own message loop. Windows announces this state rather than answering a
    query. Dimmed counts as on.
  - **macOS:** `CGDisplayIsAsleep` over every online display. It is off only when all of them
    sleep, so a laptop open beside a sleeping monitor still counts as a person at a screen.
  - **Linux:** GNOME Mutter's `PowerSaveMode` over D-Bus, then X11 DPMS through `xset q`.
    These readers are subprocesses, so they run on a thread of their own and `/ping` reads the
    last value without waiting. The phone allows `/ping` 1500 ms, and a slow fork must never
    look like a logout.
- **"unknown" is the default and the landing place for every failure.** The phone treats only
  `"off"` as idle. That covers a server from before this ADR (no key), a platform with no reader,
  a compositor this does not know, and an API that errors. In every one of those cases the panel
  behaves as it did before. Being wrong that way costs a lit screen. Being wrong the other way
  would put the panel dark in front of somebody using the PC.
- **The phone has a third state, `IDLE`**, with its own marker `state=idle`.
  - The screen, the data poll and the wake lock take the offline path unchanged.
  - The cadence stays the online one. The PC is up, so the monitor coming back is noticed
    within one 2 s poll, not after a backoff that has climbed to 15 s.
  - IDLE on battery is dormant, exactly like offline on battery (T5.6). A monitor left off
    overnight must not hold a 2 s probe under a wake lock on a phone that is not charging.
- **With more than one PC, a dark PC does not end the cycle.** Another listed PC may have
  somebody at it, and that one wins. The cycle is idle only when no PC answers with its display
  on, and it stays on the active PC if that one is idle, so two dark PCs do not flap either.
- **`follow_display = false`** in `config.toml` turns it off, per PC. The server then answers
  `"unknown"`.

## Consequences

- `state=offline` no longer means every case in which the panel is dark. Read `screen=sleep`
  for "dark", and `state=` for why: `offline` (nobody logged in) or `idle` (logged in, display
  off).
- A locked session with its monitor still on keeps the panel lit. The owner asked about the
  display, and locking is a separate fact that the server does not read today. Adding it later
  belongs in `display.py` and in this ADR.
- `/ping` now says one more thing to anyone on the LAN who asks: whether the owner's monitor is
  on. It is the same kind of fact `/ping` already gave away (somebody is logged in), and
  [T9.4](../../tasks/T9.4-private-panel-traffic.md) decides what `/ping` should reveal at all.
- The macOS reader was measured on the owner's Mac. The phone half was measured on the Redmi
  against a server whose display answer was controlled. The Windows and Linux readers are written
  from Microsoft's and GNOME's documentation, and their decoding is unit-tested, but no real
  event has reached them yet. That check is in T4.6's manual section.
