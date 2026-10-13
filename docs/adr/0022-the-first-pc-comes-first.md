# 0022 — The first PC listed comes first

Status: accepted · 2026-10-13 (T4.9)
Amends [ADR 0016](0016-more-than-one-pc.md), whose "no flapping" rule kept the panel on whichever
PC answered last until that one stopped answering.

## Context

Reported from the chair on 2026-10-12: the CachyOS PC was on and the panel was on it. The Mac
was switched on and logged into, and the panel stayed on the PC. Under ADR 0016 that was correct
behaviour. The panel moves only when the PC it is on stops answering. The owner does not want
that rule: "priority always PC, but if PC server went down, change to MAC if MAC is on."

## Decision

- **`PC_IP` is a priority order.** The first address is the PC. Any later one is where the
  panel goes while the PC is away.
- **The PC takes the panel back.** While the panel is on a lower host, one cycle in
  `PcHosts.PRIORITY_EVERY` (5) asks the hosts in listed order. If the PC answers with its
  display on, it ends the cycle and becomes the active host. At the 2 s online interval that is
  about 10 s.
- **The other cycles still ask the active host first.** A PC that is off does not refuse the
  connection. It times out, measured at 1.5 s from the phone to `192.168.15.3` on 2026-10-13.
  Asking it first on every cycle would take each 2 s cycle on the Mac to about 3.5 s.
- **A PC with its display off does not take the panel.** ADR 0020 already lets a dark host fall
  through to the next one, so a PC whose monitor has gone to sleep leaves the panel on the Mac.
  With every host that answers dark, the idle host is the first one found. On a priority cycle
  that is the PC, so two dark machines settle on the PC and do not alternate.

## Consequences

- With both machines in use the panel shows the PC, its data and its buttons. To see the Mac,
  the PC has to log out or its display has to sleep.
- After the PC leaves, the move to the Mac still happens on the next cycle. The fall-over path
  is unchanged.
- **A PC that misses a probe while both are on hands the panel to the Mac for up to five
  cycles.** That is the T4.7 shape: a game starving the server past the timeout. The state stays
  online, so the screen does not change, but presses, the volume and a data refresh in that
  window go to the Mac. Under ADR 0016 the panel moved once and stayed. Here it comes back.
- **The PC's display reader decides whether the Mac ever gets the panel while the PC is
  logged in.** `display.py` reads GNOME's Mutter and X11 DPMS. KWin and sway answer
  `"unknown"`, which counts as on. On a KDE session the PC therefore keeps the panel even with
  its monitor asleep. Which desktop this desk's CachyOS runs was not checked.
- One cycle in five on the Mac pays the PC's timeout, so `ping=` lines on the Mac arrive
  slightly less regularly. T5.3 counts cycles, not their spacing.
