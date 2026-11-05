# 0025 — The app starts itself at boot

Status: accepted · 2026-11-04 (T4.14)
Amends [ADR 0023](0023-a-watchdog-brings-the-service-back.md), which left the return after a
reboot to whatever `INSTALL-PHONE.md` said brings it back, and did not measure it.

## Context

The app had no boot receiver, by choice. `PHONE-SETUP.md` and `INSTALL-PHONE.md` said that on
the development phone MIUI's Autostart list brings the app back after a reboot, and that the
panel would be on screen within about two minutes. T2.4, the task that would have measured it,
has been `blocked` since 2026-09-16.

On 2026-11-04 the phone shut down (`sys.boot.reason` `shutdown,userrequested`) and booted at
about 12:25. That was the same minute the owner logged into the PC. The server was up at
12:25:02. Three minutes later the app had no process, the resumed activity was the MIUI
launcher, the app was not in recents, and the log had no line from it since the boot. Autostart
was granted (`MIUIOP(10008): allow`). The panel stayed dark with the PC logged in.

Autostart is a permission. It lets MIUI deliver `BOOT_COMPLETED` and other background starts
to the app. It does not start an app that has nothing listening.

## Decision

- **`BootReceiver` listens for `BOOT_COMPLETED`** and starts `PanelService`. It does not start
  the Activity. After a boot the service is the one that watches the PC, and it raises the
  panel when the PC answers, the same way a watchdog revival does (ADR 0023). A boot with the
  PC away leaves the phone dark, which is the right state.
- **The receiver is not exported.** The system reaches it anyway, and no other app can start
  the service through it. It also checks the action, so a hand-sent broadcast with another
  action does nothing.
- **`RECEIVE_BOOT_COMPLETED`** is a normal permission, granted at install.
- **The start is tagged `ACTION_BOOT`** so the service logs `service started at boot`. That is
  plain text, like `service revived by watchdog`, because no state changed.
- Starting a foreground service from `BOOT_COMPLETED` is one of Android 12's documented
  exemptions from the background-start restrictions. Android 15 forbids some foreground
  service types from a boot receiver (`dataSync`, `camera`, `mediaPlayback`, `phoneCall`,
  `mediaProjection`, `microphone`). `specialUse` is not one of them. Raising the panel
  afterwards is not covered by any exemption. It still needs "Display over other apps", the
  same grant the watchdog revival needs.

## Consequences

- After a reboot the panel returns without opening the app, provided that Autostart is on
  (MIUI does not deliver the broadcast otherwise) and "Display over other apps" is granted.
  Without the second one, the service runs, logs `state=online`, `screen=wake` and
  `overlay=denied`, and the wake retry (ADR 0024) keeps asking until the grant returns.
- The watchdog chain is armed at boot as well, because the start goes through
  `onStartCommand`.
- A phone without a vendor Autostart list no longer needs the app opened by hand after a
  reboot.
- **A force-stopped app gets no `BOOT_COMPLETED`.** `am force-stop`, *Force stop* in
  Settings, and MIUI's recents "clear" or its cleaner put the package in Android's stopped
  state, and it stays there until it is opened by hand. A reboot after that leaves the panel
  dark with Autostart on, which looks exactly like the bug this ADR fixes. `dumpsys package
  dev.bosco.deskpanel` shows `stopped=true` in that case.
- An update (`adb install -r`) kills the process, and nothing here restarts it. There is no
  `MY_PACKAGE_REPLACED` receiver. That gap predates this ADR and is left as it is: an install
  is done by hand, and the hand opens the app.
- **On a phone with a PIN, the panel returns at the first unlock, not at the boot.**
  `BOOT_COMPLETED` is sent only once the user's storage is unlocked, and the development phone
  has a PIN. Measured on 2026-11-05: after a reboot the user stayed `RUNNING_LOCKED` and the
  app did not run. At the unlock the broadcast went out at 09:29:45, and the receiver was
  reached 42 s later, at the back of MIUI's boot queue. `service started at boot`,
  `state=online` and `screen=wake` followed within 2 s, with `MainActivity` resumed.
  `LOCKED_BOOT_COMPLETED` would not help. The app is not direct-boot aware, and its WebView and
  preferences live in storage that is not readable before the unlock. A panel that comes back
  with no hand at all needs the lock screen without a PIN. That is the owner's call about the
  phone, not the app's.
- Before this ADR, unlocking after a reboot did not help either: nothing started the app until
  it was opened by hand.
