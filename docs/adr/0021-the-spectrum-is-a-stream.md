# 0021 — The spectrum bars are a stream, and capture runs only while the panel watches

Status: accepted · 2026-09-30 (T8.5)
Extends [ADR 0002](0002-native-owns-network-io.md), whose native network code only ever
asked and waited, and [ADR 0018](0018-the-panel-traffic-is-private.md), whose data routes gain
one more.

## Context

The owner asked for Winamp's spectrum analyser in the empty space over the two buttons, and for
it to follow what is actually playing on the PC. Everything the panel shows until now arrives by
polling: `/ping` every two seconds, the data every sixty. Bars that move with music need about
twenty updates a second. A poll at that rate would open twenty connections a second, and in
private mode each one would cost a TLS handshake.

The PC's audio is also a new kind of thing to capture. The mixer calls ADR 0015 allows read one
number when asked. This one listens continuously to whatever the machine is playing.

## Decision

- **One long-lived response.** `GET /spectrum` answers 200 and keeps writing one line per frame:
  sixteen bars, bass to treble, two hex digits each (`0..255`), about twenty frames a second,
  and only when a frame differs from the last. A keepalive re-sends the last frame every five
  seconds, so a phone that vanished without closing the socket is found by a failed write. The
  server ends a stream after fifteen minutes and the phone opens a new one.
- **Only bars leave the PC, never audio.** The FFT runs on the PC, in `server/spectrum.py`, in
  pure Python: about 1.2 ms a frame on this Mac. Sixteen levels a frame are about 660 bytes a
  second.
- **Capture runs only while somebody is watching.** The first stream starts the platform's
  source; the source stops five seconds after the last stream ends. The phone opens the stream
  only while the PC is `ONLINE`, beside the data poll, so a dark panel means nothing is being
  captured.
- **Off by default.** `spectrum = false` in `config.toml`. Turning it on is the owner's decision,
  on a machine they own, and on macOS the system asks as well.
- **One source per platform, one hub for all of them.** A source hands over mono 16-bit PCM,
  after a `rate=<hz>` line unless its arguments fix the rate. Everything after that is shared.
  - **macOS**: `server/mac/spectrum_tap.swift`, a Core Audio process tap (macOS 14.2+) on the
    global output mix, excluding nothing, feeding a private aggregate device that includes no
    speaker. With no speaker in it, switching outputs does not stop it. Swift because the tap
    API is not reachable from the standard library. Built by `install_agent.sh`.
  - **Windows**: `server/win/spectrum_tap.cs`, WASAPI loopback on the default output, compiled
    by `install_task.ps1` with the `csc.exe` every Windows ships (so C# 5). No permission is
    involved. It follows Microsoft's "Loopback Recording" and `IAudioClient::Initialize`
    pages:
    - an event-driven shared stream (Windows 10 1703+), with a 100 ms wait as the fallback;
    - `[STAThread]`, as the IAudioClient page asks;
    - `IMMNotificationClient` to notice a new default output, then exit so the hub restarts
      it on that output.

    The vtables were checked against Microsoft's own `windows-rs` bindings, because the
    reference pages list methods alphabetically. It is started with `CREATE_NO_WINDOW`,
    because under `pythonw` a console child opens a window.
  - **Linux**: `parec --device=@DEFAULT_MONITOR@` at a fixed 24 kHz mono, which PulseAudio and
    PipeWire's pulse layer both serve. No helper.

  The Python server stays standard-library only. Both helper binaries are gitignored.
- **It is a data route.** `/spectrum` sits beside `/quotes` and `/weather` in ADR 0018's check:
  over TLS with `X-Panel-Key` when the panel is private, 401 otherwise. It is 404 when the bars
  are off or this platform cannot capture, and the phone then asks again once a minute.
- **The page never trusts a frame.** `SpectrumFrame.java` accepts exactly 32 lowercase hex
  digits before `evaluateJavascript`, and `parseSpectrum` in `format.js` checks the same again.
  The bars are shown while frames arrive and hidden 15 s after the last.

## Consequences

- **macOS asks once for "System Audio Recording" for the server's Python**, and while the tap
  runs, the Control Center shows the audio-recording indicator. A Python that has been granted
  it can tap any process's audio, not only this server's. That is the permission's scope on
  macOS, and it is the reason the key is off by default.
- One server thread per open stream, for as long as it stays open. There is one panel per desk;
  ADR 0016's three PCs are three servers.
- The phone's radio carries a steady trickle while the panel is lit and the PC plays something.
  Silence sends only the five-second keepalive.
- **Not yet measured:** `parec` against PipeWire on CachyOS (measured against PulseAudio
  only), and private mode end to end on the device, which has unit coverage only. The Windows
  helper ran on the Windows PC on 2026-09-30 (wave 42), with real bars on the wire and no console
  window.

## Amendment, 2026-09-30 (T8.6): The volume rides the stream

The volume bar (T8.4) was told the PC's level only on `/quotes`, once a minute, and on Windows
behind a 120 s cache, because each read there is a PowerShell process. On the first Windows run
the owner turned the knob and the phone took up to three minutes to follow.

- **One more line type on the same stream:** `v=<0..100>`, in decimal, sent when a stream opens
  if the level is known, and on every change after that. A frame is still exactly 32 hex digits,
  so neither shape can be taken for the other. The keepalive is still the frame's: a volume line
  does not reset it.
- **The source reports the level, out of band.** The Windows helper reads
  `IAudioEndpointVolume` on the device it is capturing, at most every 100 ms, and writes
  `v=<level>` on **stderr**. stdout stays raw PCM. The hub drains stderr on a thread: `v=` lines
  are the level, and anything else is the helper's complaint, now logged instead of lost under
  `pythonw`.
- **Only with the `volume` action enabled.** Otherwise the hub writes no volume line, the same
  rule `/quotes` follows, where the bar is `null`.
- **One number everywhere.** The hub tells the App, so `/quotes` reports what the stream sent, and
  a set from the phone goes out on every open stream.
- **Checked twice, like a frame.** `SpectrumFrame.parseVolume` turns the line into an `int`
  before `evaluateJavascript`, and `parseVolume` in `format.js` checks it again.
- An APK from before this amendment drops the line, because it only ever took frames.
- **macOS and Linux are unchanged.** Their sources report no volume, so their bars still follow
  `/quotes`. The Swift helper could do the same read. `parec` cannot.
  - **Superseded for Linux** by the amendment below: `parec` still cannot, and it turned out not
    to have to.
  - **Superseded for macOS** by the T8.8 amendment: the Swift helper does the read.

## Amendment, 2026-10-01 (T8.7): Linux reports it too, from a second process

The bullet above read "`parec` cannot" and stopped there, which quietly made the level a
property of the capture process. It is not: it is a property of the sound server, and on Linux
that can be asked separately. Reported from the chair the same evening — the spectrum followed
the music and the bar did not follow the knob.

- **Two processes, one source.** `ParecSource` keeps `parec` for the PCM and adds
  `pactl subscribe`, which emits a line when anything in the sound server changes. On a line
  that means the output device (`on sink #N`, or `on server` for a change of default sink), it
  reads the level with `actions.read_volume` — the same `wpctl get-volume` `/quotes` already
  uses — and pushes it through the same `on_volume` the stderr drain owns. The hub, every open
  stream and `/quotes` therefore still end on one number.
- **An event, not a poll.** Nothing runs while nothing moves. A poll fast enough to feel
  instant would be five `wpctl` processes a second for as long as the panel is lit, which is
  the kind of idle cost this project refuses elsewhere.
- **`sink-input` is not `sink`.** One application's own slider must not redraw the panel's bar,
  and `is_sink_event` is where that distinction lives, pinned by its own tests.
- **Degrading is the old behaviour, not an error.** With no `pactl` on PATH the bars still work
  and the bar falls back to `/quotes`, with the reason logged once. `reports_volume` is the one
  place that says which platforms claim a level at all, so the hub is told rather than guessing.
- **macOS is still `/quotes`.** The Swift helper would need the CoreAudio read, and this change
  does not give it one.
  - **Superseded** by the amendment below.

## Amendment, 2026-10-09 (T8.8): macOS reports it from the helper

The Swift helper now does what the Windows one does: it reads the level itself and writes
`v=<level>` on stderr, once on starting and once per change. Nothing in the hub, the stream or
the phone changed; `reports_volume("darwin")` is now True and that is the whole Python side.

- **The same number `/quotes` reads.** The helper reads the default output's
  `kAudioHardwareServiceDeviceProperty_VirtualMainVolume`, which is what AppleScript's
  `output volume of (get volume settings)` reports. Measured side by side at 30, 55 and 80.
- **An event, not a poll**, as on Linux. Core Audio calls back when the volume moves and when
  the default output changes, and the helper follows the new output. Windows polls every 100 ms
  inside a loop it already runs; here there is no such loop to ride.
- **A device with no main volume sends nothing.** Some HDMI and USB outputs have no such
  control. The bar then keeps the level `/quotes` reads, which is the old behaviour.
- **An old helper is stale for up to 20 s, not wrong for good.** A `spectrum-tap` built before
  this change sends no `v=` line, so the hub keeps only the phone's last set, and a stream that
  opens later starts on it even if the Mac's keys moved since. `/quotes` corrects it within
  `VOLUME_TTL_S`. Re-running `install_agent.sh`, or the `swiftc` line, rebuilds it.
- **The selector is read through the AudioObject API.** `AudioHardwareService.h` documents
  `VirtualMainVolume` for the `AudioHardwareService*` functions, which are deprecated since
  macOS 10.11. Reading it with `AudioObjectGetPropertyData` and listening with
  `AudioObjectAddPropertyListenerBlock` is the path in common use, not the documented one. It
  was measured on macOS 26.5. If a later macOS drops it, the helper sends no line and the bar
  is back on `/quotes`.

