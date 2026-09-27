# Setting up the phone, on any Android

This is the device-neutral half. It says **what the panel asks of Android and why**, and how to
check from `adb` that it was granted — every claim here carries a link to the platform
documentation, and where the platform documentation does not say it, the page says instead that
the behaviour was *measured on one device* and gives the command that measures it.

The other half, [INSTALL-PHONE.md](INSTALL-PHONE.md), is one vendor's recipe on one phone: the
exact menus, the vendor-only lists that have no platform equivalent, and numbers read off that
device. If you are holding a Pixel, a Galaxy or anything else, this page is yours and that one
is a worked example of the kind of thing your vendor will also have.

A panel is an unusual thing to ask a phone to be, and every section below exists because the
platform's defaults are right for a phone in a pocket and wrong for a screen on a desk.

## What the app asks for, and what it does not

Five permissions, and the list is short on purpose — the panel reads nothing personal and writes
nothing to the device.

| Permission | Why |
|---|---|
| `INTERNET` | Native Java does every request; the WebView makes none ([ADR 0002](adr/0002-native-owns-network-io.md)) |
| `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_SPECIAL_USE` | The poll loop has to outlive the screen ([ADR 0014](adr/0014-poll-loop-outlives-the-screen.md)). `specialUse` is the honest type: this is not media, not a download, not a location fix |
| `WAKE_LOCK` | A `PARTIAL_WAKE_LOCK` held **only while the PC is away**, so the device can suspend the screen and still notice a login |
| `POST_NOTIFICATIONS` | The foreground service's own notification. See the note below — on API 33 and up this one is not granted by declaring it |

There is **no `RECEIVE_BOOT_COMPLETED` receiver** in this app. Coming back after a reboot is not
something it arranges for itself; on the development device it is a vendor autostart list that
does it, and that is in the other document. If your phone has no such list, expect to open the
app once after a reboot.

**`POST_NOTIFICATIONS` is a runtime permission on API 33+**, and nothing in the app requests it
yet — the development device is API 31, where the notification simply appears. On Android 13 or
newer, grant it by hand the first time or the service loses its notification and the system
eventually loses the service:

```bash
adb shell pm grant dev.bosco.deskpanel android.permission.POST_NOTIFICATIONS
adb shell dumpsys package dev.bosco.deskpanel | grep POST_NOTIFICATIONS
```

## Installing the APK without a cable

The PC server serves it. Point the phone's browser at `http://<pc-ip>:8777/`, follow the single
link, download, install. Android will ask once whether this browser may install applications;
that prompt is the platform's *Install unknown apps* permission, and it is per-source.

This route is deliberate. `adb install` over USB works too, and on some vendor builds it needs a
second developer toggle and an account; the browser needs neither.

## The APK is built for one PC address

The app is allowed to speak cleartext `http` to **exactly one host**, and that permission is
compiled into the APK from `PC_IP` in the gitignored `.env`
([ADR 0013](adr/0013-local-configuration-boundaries.md)). Everything else is refused by Android's
[network security configuration](https://developer.android.com/privacy-and-security/security-config),
which is where that list lives.

**If the PC's address changes, editing a file is not enough — the APK has to be rebuilt and
reinstalled**, because the permission is a property of the APK rather than of the server. Nothing
else in this project behaves that way, and the symptom is a panel that reports *offline* for ever
while the network is fine. Give the PC a static DHCP reservation and this never comes up. Every
build prints the address it pinned; see [BUILD.md](BUILD.md).

Never put an API token in `.env`. Anything Gradle reads is compiled into the APK, and an APK is a
zip file. Tokens, tickers, the city and the intervals live in `server/config.toml` on the PC.

## Keeping the screen on while the PC is there

The panel holds
[`FLAG_KEEP_SCREEN_ON`](https://developer.android.com/reference/android/view/WindowManager.LayoutParams)
on its window. Two things about that flag are worth knowing before you debug anything:

- **It is not a wake lock.** It keeps the display on *while that window is visible*, and it needs
  no permission. If the window goes away, so does the effect — which is why this app also runs a
  service, and why a frozen Activity looks exactly like a broken one.
- **It does not stop a battery manager freezing the process.** The screen stays lit, the clock
  stops ticking, and nothing in the log says why. That is the single most confusing failure in
  this project, and the battery section below is the fix.

## Letting it sleep, and waking it again

This is the project's whole point, so it gets its own section: **the screen follows the PC, never
a timeout** ([ADR 0005](adr/0005-real-screen-sleep.md),
[ADR 0008](adr/0008-device-longevity.md)).

- **PC online** → the flag above is held, and the display stays on.
- **PC offline** → the flag is cleared and Android is allowed to do what it would normally do:
  dim, then sleep. The panel does not fight it.
- **PC returns** → the service raises the Activity, which calls `setShowWhenLocked(true)` and
  `setTurnScreenOn(true)` — the two [`Activity`](https://developer.android.com/reference/android/app/Activity)
  methods that replaced the deprecated window flags in **API 27**. They are what turns the
  display back on from a cold, locked screen without a wake lock and without unlocking anything.

Three commands tell you which of the three states you are in. None of them is documented as an
API — they read the platform's own dump output, which changes between releases:

```bash
adb shell dumpsys power | grep -E 'mWakefulness|mHoldingDisplay'
adb shell dumpsys window | grep -i 'keep screen on'
adb logcat -s DeskPanel        # the app's own state= and screen= markers
```

The app emits its own markers precisely because the first two are not a contract
([ADR 0009](adr/0009-testing-strategy.md)). Trust the third when they disagree.

**A vendor skin is allowed to override all of this**, and one of them does: a permission to show
a window over the lock screen may be refused, in which case `setTurnScreenOn` is called, reports
success, and the screen stays dark. If the markers say the app tried and the display disagrees,
that is where to look — and it is the other document.

## The battery optimisation exemption

Android puts an idle app into
[Doze and App Standby](https://developer.android.com/training/monitoring-device-state/doze-standby),
which defers its alarms. This panel sleeps on purpose when the PC is away and wakes itself with a
sparse alarm to ask again, so a deferred alarm is not a slow panel — it is a panel that never
comes back.

Measured on the development device: an allow-while-idle alarm asked for **15 minutes** was
deferred to **three days**. The alarm is still listed as armed the whole time, so a check that
only looks for its presence passes while recovery is three days away.

The exemption is a **user decision** by design — an app may ask with
[`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`](https://developer.android.com/reference/android/provider/Settings),
and Google Play restricts which apps may even ask. Grant it in Settings → Apps → Desk Panel →
Battery → *Unrestricted*, or from the host:

```bash
adb shell dumpsys deviceidle whitelist +dev.bosco.deskpanel
adb shell dumpsys deviceidle whitelist | grep -q dev.bosco.deskpanel && echo exempt
```

What it does **not** exempt: network access while dozing is still metered by the platform, and it
is not a licence to run in the background — the foreground service is what keeps the process
alive. It exempts the *alarm* from deferral, which is the one thing needed here.

Your vendor may also have a battery list of its own. That is a different list, granting it does
not grant this one, and the two are confused constantly.

## Developer options and adb over Wi-Fi

No cable is needed for the development loop either.
[Wireless debugging](https://developer.android.com/tools/adb) arrived in Android 11: enable
*Developer options* (tap the build number seven times), then *Wireless debugging* → *Pair device
with pairing code*.

```bash
adb pair <ip>:<pair-port>      # the six-digit code from the phone
adb connect <ip>:<port>
adb logcat -s DeskPanel
```

Pairing is one-time per host. Some access points block mDNS, so the phone may never *find* the
host — the explicit `adb pair` above needs no discovery at all.

**One developer option to turn off:** *Stay awake*, which holds the screen on whenever the device
is charging. On a desk that is always, so it silently defeats the entire design above: the panel
logs `screen=sleep` and the display stays lit.

```bash
adb shell settings get global stay_on_while_plugged_in   # must be 0
```

## Grants do not survive a reinstall

`adb install -r` resets permissions the app did not declare as install-time ones — and on some
vendor builds it resets that vendor's own grants too, silently. Nothing announces it: the panel
keeps logging that it tried, and simply stops working.

After **every** install, re-check the things you granted:

```bash
adb shell dumpsys deviceidle whitelist | grep dev.bosco.deskpanel
adb shell appops get dev.bosco.deskpanel
adb shell settings get global stay_on_while_plugged_in
```

This is the most expensive lesson in this repository, learned twice. The verification commands
matter more than the granting: a reader who knows them can diagnose a failed grant without
asking anybody.

## Then what

Reboot the phone and leave it. The panel should be on screen, in landscape, within about two
minutes of the PC being logged in, untouched.

If it is not, the order to check is: the app is running at all (`adb logcat -s DeskPanel`), the
PC answers (`adb shell ping -c 3 <PC_IP>`), and only then anything in this document. Two thirds
of the failures on this desk were one of those two.

Before leaving it plugged in permanently, read [DEVICE-CARE.md](DEVICE-CARE.md) — a phone held at
100% for months is a phone with a swollen battery.
