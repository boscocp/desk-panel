# Device care

A phone living on a desk, plugged in permanently, ages in two ways: the lithium cell degrades
when held at 100% while warm, and the OLED panel burns in when it shows a static image. Both
are manageable. One of them is not manageable from inside the app.

## What the app cannot do

**It cannot limit charging to 80%.** Android exposes no public API to stop or throttle
charging; `BatteryManager` is read-only. Apps that claim this either require root or simply
send you a notification. This is settled and recorded in
[ADR 0008](adr/0008-device-longevity.md) so it does not get re-litigated in six months.

## What the app does

| Measure | Effect |
|---|---|
| The screen genuinely sleeps when the PC is off | Removes most of the day's display-on hours. The biggest single win |
| Polling backs off from 2s to 15s when offline, and data polling stops entirely | Less radio and CPU exactly when nobody is looking |
| Night profile lowers brightness on a schedule | Less heat, less panel wear |
| Layout shifts a few pixels every few minutes | Burn-in mitigation. Neon on black already helps, since most pixels are simply off |
| Battery level and temperature shown, with a warning above 40 degrees | Heat is what kills lithium cells. Better to watch the number than discover the problem as a bulge |

## What actually solves the charging problem

### 1. Disable ErP Ready in the BIOS — recommended

Look for *ErP Ready*, *EuP*, or *USB power in S5*, and turn it off. USB then loses power along
with the PC.

The phone discharges while the PC is off and recharges while it is on. That is natural cycling,
and it avoids the worst case for a lithium cell: sitting at 100% and warm, permanently. It costs
nothing, needs no code, and fits the design — the screen is asleep during those hours anyway.

**Accepted consequence:** the phone then runs on its own battery whenever the PC is off. This is
why real screen sleep and adaptive polling are requirements rather than polish. Without them the
device is flat by morning.

### 2. Check MIUI for battery protection

Settings → Battery. If MIUI 14 on this device offers battery protection or optimised charging,
enable it. Not guaranteed to exist on this model, so check rather than assume.

### 3. A scheduled smart plug

If you would rather not touch the BIOS, a smart plug on a timer achieves the same cycling.

## Watch for

- **Swelling.** If the back cover starts to lift or the screen sits proud of the frame, stop
  using the device and dispose of the battery properly. This is the failure mode being designed
  against.
- **Sustained heat.** The panel warns above 40 degrees. Persistent warnings mean something is
  wrong — poor ventilation, direct sun, or a charger delivering more than needed.
- **Burn-in.** Neon on black is close to the best case, but check occasionally for ghosting of
  the clock. If it appears, shorten the layout shift interval.
