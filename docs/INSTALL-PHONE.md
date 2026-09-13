# Installing on the phone

Target device: Redmi Note 10, Android 12, MIUI 14.0.9. AMOLED, 2400x1080, used in landscape.

## Installing without a cable

The PC server serves the APK. From the phone's browser:

```
http://<pc-ip>:8777/app
```

Download, then install. MIUI will ask you to allow installs from the browser once.

This deliberately avoids `adb install` over USB, which on MIUI requires enabling "USB debugging
(Security settings)" — a separate toggle from the standard one that wants a Xiaomi account and
sometimes imposes a waiting period on new accounts. The browser route sidesteps all of it.

## MIUI settings that decide whether this works at all

These are not optional polish. Without them MIUI will kill the app within hours and it will
look like a bug in the code.

1. **Autostart** — Settings → Apps → Manage apps → desk-panel → **Autostart on**.
   Without it the app does not come back after a reboot.
2. **Battery saver → No restrictions** — same screen, Battery saver → **No restrictions**.
   This is the one that matters most. MIUI's battery manager will otherwise freeze the Activity
   and the panel silently stops updating.
3. **Lock in recents** — open the app switcher, pull the app card down to lock it. Reduces the
   chance of MIUI reclaiming it under memory pressure.
4. **Stay awake while charging** — Developer options → **Stay awake**. A useful belt-and-braces
   measure alongside the app's own screen handling.
5. **Auto-rotate off**, phone in landscape. The app locks orientation itself, but this avoids
   fighting the system during setup.

Verify with a reboot: the panel should return to the foreground on its own within about two
minutes, untouched.

## Wireless debugging (development only)

Android 12 supports it, so no cable is needed for the development loop either.

Developer options → **Wireless debugging** → *Pair device with pairing code*. Then:

```bash
adb pair <ip>:<pair-port>      # enter the 6-digit code
adb connect <ip>:<port>
adb logcat -s DeskPanel
```

Whether this works from inside the build container is not something the Android docs cover —
pairing uses mDNS, which may not cross the container boundary. If it does not, extract
`platform-tools` into `tools/platform-tools/` in this repo and run adb from the host. It is a
zip with no installer, `tools/` is gitignored, and deleting the folder removes it completely —
so the "nothing installed on Windows" promise holds either way.

## Battery

Before leaving this running permanently, read [DEVICE-CARE.md](DEVICE-CARE.md). The short
version: disable ErP Ready in the BIOS so USB power drops with the PC, and let the phone cycle
instead of floating at 100% forever.
