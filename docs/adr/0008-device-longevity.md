# 0008 — Device longevity: what the app controls, and what it cannot

Status: accepted · 2026-09-13

## Context

The phone sits on a desk, plugged into USB, indefinitely. Two things age it: a lithium cell
held at 100% while warm, and an OLED panel showing a static image. A swollen battery on a desk
is a real outcome, not a theoretical one.

The instinct is "make the app stop charging at 80%". That instinct needs to be settled once and
recorded, because it will come back.

## Decision

**Android provides no public API to limit or stop charging.** `BatteryManager` is read-only.
Store apps claiming otherwise either require root or merely notify. This is not a gap to work
around in code — it is out of reach, and this ADR exists so nobody spends a session
rediscovering that.

What the app **does** own:

| Measure | Effect |
|---|---|
| Screen genuinely sleeps when the PC is off (ADR 0005) | The largest single win; removes most of the daily display-on hours |
| Adaptive polling: 2s online, backing off to 15s offline, data polling paused entirely | Less radio and CPU precisely when nobody is looking |
| Night profile: reduced brightness on a schedule | Less heat, less panel wear |
| Layout shifted a few pixels every few minutes | Burn-in mitigation. Neon on black already helps, since most pixels are off |
| Battery level and temperature on the panel, warning above 40 degrees | Heat is what kills lithium cells; better to read the number than discover it by bulge |

What actually solves the charging problem sits **outside the code**:

1. **Disable ErP Ready / USB power in S5 in the BIOS.** USB then dies with the PC, so the phone
   discharges while the PC is off and recharges while it is on. Natural cycling, avoiding the
   worst case of floating at 100% and warm around the clock. Costs nothing. This is the primary
   recommendation.
2. Check whether MIUI 14 on this device exposes battery protection or optimised charging, and
   enable it if present. Not guaranteed on this model, hence a check rather than an assumption.
3. A scheduled smart plug, for anyone unwilling to touch the BIOS.

## Consequences

- Expectations are set honestly: the app mitigates, it does not control charging.
- **Accepted consequence of recommendation 1:** with ErP disabled, the phone runs on its own
  battery whenever the PC is off. That promotes adaptive polling and real screen sleep from
  polish to requirement — without them the device is flat by morning.
- `docs/DEVICE-CARE.md` carries the user-facing version of all this.
