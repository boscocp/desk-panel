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

## The APK is built for one PC address

The app is allowed to talk cleartext http to exactly one host, and that permission is baked
into the APK. It comes from `PC_IP` in the gitignored `.env` at the repository root — the file
`.env.example` describes, and which also holds the signing keys
([ADR 0013](adr/0013-local-configuration-boundaries.md)). **Never put an API token there:**
the phone never reaches a data provider, the PC does, and anything Gradle reads is compiled
into the APK, which is a zip file. Tokens, tickers, the city and the intervals live in
`server/config.json` on the PC instead.

So before building the APK you install here, set `PC_IP` to the PC's LAN address — the one from
its static DHCP reservation. **If that address ever changes, editing `.env` is not enough: the
APK has to be rebuilt and reinstalled**, because cleartext permission is a property of the APK,
not of the server. Nothing else in the project behaves that way.

Every build prints which address it used:

```
desk-panel: cleartext pinned to 192.168.15.3 (from .env)
desk-panel: cleartext pinned to 192.168.1.100 (placeholder — no .env, the panel will not reach any PC)
```

The second line means the APK will report "offline" for ever, whatever the network is doing.
That looks exactly like a bug in the app, which is why the line exists. See
[BUILD.md](BUILD.md).

The phone and the PC need not share a subnet — on the development network they do not, and
routing between them works. `adb shell ping -c 3 <PC_IP>` is the check.

## MIUI settings that decide whether this works at all

These are not optional polish. Without them MIUI will kill the app within hours and it will
look like a bug in the code.

1. **Autostart** — Settings → Apps → Manage apps → desk-panel → **Autostart on**.
   Without it the app does not come back after a reboot.
2. **Battery saver → No restrictions** — same screen, Battery saver → **No restrictions**.
   MIUI's battery manager will otherwise freeze the Activity and the panel silently stops
   updating. **This is MIUI's own list, and it is not Android's** — see step 6, which is a
   different exemption on a different list and is the one the sparse offline alarm depends on.
   Doing this one does not do that one.
3. **Lock in recents** — open the app switcher, pull the app card down to lock it. Reduces the
   chance of MIUI reclaiming it under memory pressure.
4. **Show on Lock screen** — same screen, Other permissions → **Show on Lock screen**, and
   **Display pop-up windows while running in the background** with it.
   This is what lets the panel come back on its own. When the PC returns, the service raises
   the Activity so `setTurnScreenOn` can fire (ADR 0014); without this permission MIUI refuses
   it and says so in logcat —
   `MIUILOG- Show when locked PermissionDenied pkg : dev.bosco.deskpanel` — while everything
   else looks perfect: `state=online` and `screen=wake` are both logged, and the screen stays
   dark. Measured on the device, 2026-09-19.
5. **Stay awake OFF** — Developer options → **Stay awake** must be **off**.
   It is on by default on a phone that has been used for development, and it holds the screen
   on for as long as the phone is charging — which, on this desk, is always. With it on the
   panel logs `screen=sleep` and the display stays lit, so the single largest longevity win in
   the project silently does not happen (ADR 0005, ADR 0008). Check it from the host with
   `adb shell settings get global stay_on_while_plugged_in`; the answer must be `0`.
   An earlier version of this document recommended turning it **on**. That advice belonged to
   the abandoned design where the screen never slept and offline was faked with
   `screenBrightness = 0f`, and it is wrong now.
6. **Auto-rotate off**, phone in landscape. The app locks orientation itself, but this avoids
   fighting the system during setup.

6. **Android's battery optimisation exemption** — Settings → Apps → desk-panel → Battery →
   **Unrestricted**, or from the host:

   ```bash
   adb shell dumpsys deviceidle whitelist +dev.bosco.deskpanel
   adb shell dumpsys deviceidle whitelist | grep -q dev.bosco.deskpanel
   ```

   **This is a different list from step 2 and it is the one T5.6's sparse offline alarm lives
   or dies on.** Without it, an `AlarmManager` allow-while-idle alarm requested for 15 minutes
   was deferred to **three days** on this device — measured 2026-09-19, and visible as
   `power_pending=+3d0h12m51s` on the alarm's `policyWhenElapsed` line while `requester` said
   `+12m51s`. The alarm is still *listed* as armed the whole time, so anything that checks only
   for its presence passes while recovery is three days away.

   The failure this produces is the project's worst shape: offline on battery, the panel goes
   dormant exactly as designed, and then nothing ever wakes it. Step 2 does not cover it —
   MIUI's "No restrictions" left the app absent from `deviceidle whitelist` on this phone.
   Check it the same way after every `adb install -r`, alongside the app-ops in step 4.

Verify with a reboot: the panel should return to the foreground on its own within about two
minutes, untouched.

### These settings do not survive a reinstall

The two permissions in step 4 are MIUI app-ops, and `adb install -r` resets them to denied.
That is worth knowing because nothing announces it: the panel keeps logging `screen=wake`
perfectly and simply stops turning the screen on. After every install, either set them again in
the UI or from the host:

```bash
adb shell appops set dev.bosco.deskpanel 10020 allow   # Show on Lock screen
adb shell appops set dev.bosco.deskpanel 10008 allow   # background pop-up
adb shell appops get dev.bosco.deskpanel | grep MIUIOP
```

The numeric ops are MIUI's own and are not documented by Xiaomi; they were read off this
device. Setting them in the Settings UI is the durable route, and the one to use on the phone
that is actually going to live on the desk.

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
