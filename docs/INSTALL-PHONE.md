# Installing on the Redmi, under MIUI

**This is one vendor's recipe on one phone.** Target device: Redmi Note 10, Android 12,
MIUI 14.0.9, AMOLED 2400x1080, used in landscape.

The platform half — what the panel asks of Android, why, and how to verify each grant from
`adb` — is [PHONE-SETUP.md](PHONE-SETUP.md), and it is the one to read first and the one to hand
to somebody with a different phone. Everything below is either a menu path that exists only in
this skin, or a number read off this device. Where a step has a platform equivalent, it links to
it rather than explaining it again.

Read the two together. Roughly: the other document says *what* has to be true, this one says
where the switch is on a Xiaomi.

## Installing without a cable

The PC server serves the APK. From the phone's browser:

```
http://<pc-ip>:8777/
```

That page has one link, which is `/app` — worth a bookmark, because a host and a port is less
to type on a phone than a host, a port and a path. `/app` serves **the newest `.apk` in
`out/`**, by modification time: `out/` holds `app-debug.apk` and `desk-panel-release.apk` side
by side, and the one you want is whichever was built last, not whichever sorts first. If
nothing has been built the route answers 404 with the build command in it, rather than an empty
page that reads like the server is broken.

Download, then install. The browser asks for permission to install once.

**Vendor detail:** this deliberately avoids `adb install` over USB, which on this skin requires
enabling *USB debugging (Security settings)* — a separate toggle from the standard one, which
wants a Xiaomi account and sometimes imposes a waiting period on new accounts. The browser route
sidesteps all of it. On a stock Android build neither toggle exists and either route is fine.

## The APK is built for one PC address

Unchanged from [PHONE-SETUP.md](PHONE-SETUP.md#the-apk-is-built-for-one-pc-address), and worth
repeating only for the check: the phone and the PC need not share a subnet — on the development
network they do not, and routing between them works. `adb shell ping -c 3 <PC_IP>` is the test.

## The settings that decide whether this works at all

These are not optional polish. Without them the system will kill the app within hours and it
will look like a bug in the code.

1. **Autostart** — Settings → Apps → Manage apps → desk-panel → **Autostart on**.
   Without it the app does not come back after a reboot. **This list is the vendor's and has no
   AOSP equivalent**; the app declares no boot receiver of its own, so on a phone without such a
   list you open the app by hand after a reboot.

2. **Battery saver → No restrictions** — same screen, Battery saver → **No restrictions**.
   The vendor battery manager will otherwise freeze the Activity and the panel silently stops
   updating. **This is the vendor's own list and it is not Android's** — see step 6, which is a
   different exemption on a different list and is the one the sparse offline alarm depends on.
   Doing this one does not do that one, and they are confused constantly.

3. **Lock in recents** — open the app switcher, pull the app card down to lock it. Reduces the
   chance of the system reclaiming it under memory pressure. Vendor behaviour.

4. **Show on Lock screen** — same screen, Other permissions → **Show on Lock screen**, and
   **Display pop-up windows while running in the background** with it. Both are vendor
   permissions with no AOSP equivalent.

   This is what lets the panel come back on its own. When the PC returns, the service raises the
   Activity so `setTurnScreenOn` can fire ([ADR 0014](adr/0014-poll-loop-outlives-the-screen.md));
   without this permission the system refuses it and says so in logcat —
   `MIUILOG- Show when locked PermissionDenied pkg : dev.bosco.deskpanel` — while everything
   else looks perfect: `state=online` and `screen=wake` are both logged, and the screen stays
   dark. Measured on the device, 2026-09-19.

5. **Stay awake OFF** — Developer options → **Stay awake** must be **off**. This one *is*
   Android's, and [PHONE-SETUP.md](PHONE-SETUP.md#developer-options-and-adb-over-wi-fi) says why
   it matters. It is on by default on a phone that has been used for development.

   ```bash
   adb shell settings get global stay_on_while_plugged_in   # must be 0
   ```

   An earlier version of this document recommended turning it **on**. That advice belonged to
   the abandoned design where the screen never slept and offline was faked with
   `screenBrightness = 0f`, and it is wrong now.

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
   dormant exactly as designed, and then nothing ever wakes it. Step 2 does not cover it — the
   vendor's *No restrictions* left the app absent from `deviceidle whitelist` on this phone.
   Check it the same way after every `adb install -r`, alongside the app-ops in step 4.

7. **Auto-rotate off**, phone in landscape. The app locks orientation itself, but this avoids
   fighting the system during setup.

Verify with a reboot: the panel should return to the foreground on its own within about two
minutes, untouched.

### These settings do not survive a reinstall

The two permissions in step 4 are vendor app-ops, and `adb install -r` resets them to denied.
That is worth knowing because nothing announces it: the panel keeps logging `screen=wake`
perfectly and simply stops turning the screen on. After every install, either set them again in
the UI or from the host:

```bash
adb shell appops set dev.bosco.deskpanel 10020 allow   # Show on Lock screen
adb shell appops set dev.bosco.deskpanel 10008 allow   # background pop-up
adb shell appops get dev.bosco.deskpanel | grep MIUIOP
```

**The numeric ops are the vendor's own and Xiaomi documents none of them; they were read off
this device.** They are not stable across skins or versions, and on a stock Android build the
numbers mean something else entirely or nothing at all — which is why they are here and not in
the platform document. Setting them in the Settings UI is the durable route, and the one to use
on the phone that is actually going to live on the desk.

## Wireless debugging (development only)

The pairing flow itself is Android's and is in
[PHONE-SETUP.md](PHONE-SETUP.md#developer-options-and-adb-over-wi-fi). What belongs here is where
`adb` should run from:

**Run adb on the host, not inside the build container.** The container does ship `adb` — the
image installs `platform-tools` — but it should not be the thing that owns the phone, and the
reason is measured rather than assumed:

- The container reaches the host by `host.docker.internal`, which is **invented by Docker
  Desktop and absent on Docker Engine**, i.e. on Linux. `docker/compose.yml` now maps it with
  `extra_hosts: host.docker.internal:host-gateway`; without that line the name does not resolve
  at all and the only symptom is a Gradle task that cannot find a device.
- For the container to use the host's adb server, that server has to accept a connection from
  the bridge — and **adb cannot listen on one interface**. `adb -a -L tcp:172.17.0.1:5037
  nodaemon server` exits with `could not install *smartsocket* listener: listening on specified
  hostname currently unsupported`. The only thing that works is `adb -a`, which binds
  `0.0.0.0:5037` and hands **anyone on the LAN full adb control of the phone**, with no
  authentication in front of it. That is a large price for tidiness.

So: pair and connect from the host, and let the container build. On Windows that means
extracting `platform-tools` into `tools/platform-tools/` in this repo rather than installing
anything — a zip with no installer, `tools/` is gitignored, and deleting the folder removes it
completely, so the "nothing installed on Windows" promise ([ADR 0003](adr/0003-containerized-toolchain.md))
holds either way.

## Battery

Before leaving this running permanently, read [DEVICE-CARE.md](DEVICE-CARE.md). The short
version: disable ErP Ready in the BIOS so USB power drops with the PC, and let the phone cycle
instead of floating at 100% forever.
