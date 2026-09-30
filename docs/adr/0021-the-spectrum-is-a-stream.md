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
- **Not yet measured:** the Windows helper on a Windows PC (it compiles as C# 5, and nothing
  more is known), `parec` against PipeWire on CachyOS (measured against PulseAudio only), and
  private mode end to end on the device, which has unit coverage only.
