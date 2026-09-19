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

## The measurement that reframes all of this (2026-09-19)

Before choosing any of the options below, read the number this desk actually reports:

```
Max charging current: 100000      # 100 mA
level 22 at 12:44  ->  level 20 at 13:11
```

**The port negotiates 100 mA.** The panel with its screen on draws several times that, so the
phone loses about 4.4% an hour *while the framework reports `status: 2`, charging*. It is not
cycling; it is a slow one-way discharge whenever anybody is looking at the panel.

Nothing in software fixes that, and the options below do not either — they are about *cycling*,
which is a different problem. **A port or charger that will negotiate more than 100 mA is the
single change that turns the sign of the equation.** Check it after changing anything:
`adb shell dumpsys battery | grep 'Max charging current'`.

Note what this does *not* cost: the panel's data path is Wi-Fi to the PC's LAN address, not the
USB cable. The cable carries power and adb, nothing else — so the phone can move to a wall
charger without changing a line of code or a byte of config. What it gives up is adb over the
cable, which T7.2 (wireless adb) exists for, and the `ACTION_POWER_CONNECTED` fast path in
T5.6, which stops mattering because a properly charged phone never goes dormant.

## Radios that are switched off on this desk

Measured and turned off 2026-09-19. None of them is large, and together they are worth perhaps
15–20 mA against a deficit of about 220 mA — hygiene, not a fix. Recorded because a factory
reset or a new phone starts with all of them back on:

| Setting | Value | Why |
|---|---|---|
| `bluetooth_on` | 0 | Nothing in the panel uses Bluetooth |
| `location_mode` | 0 | The weather city is server config; the device never needs a fix |
| `wifi_scan_always_enabled` | 0 | Scans for location even with location off |
| `ble_scan_always_enabled` | 0 | Same, over BLE |

**Wi-Fi itself must stay on.** It is the panel's only transport — `/ping` every 2s is the login
signal (invariant 2). Turning it off does not save power, it ends the product.

**Battery saver does not stay on, and that is the platform's choice, not a setting.** It can be
enabled (`adb shell cmd power set-mode 1`) and it holds while the phone reports discharging —
but Android disables it the moment the phone reports charging, which on this desk is almost
always. Measured: enabled at 14:04, `low_power=1`; `dumpsys battery reset` at 14:05 and
`low_power=0` without anybody touching it. Worth knowing that it does *not* defer T5.6's alarm
(`battery_saver=-4s` on the policy line) once the app is battery-optimisation exempt — the
concern there was misplaced. It simply will not stay on.

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
