# 0015 — The panel can act on the PC, and the id is the whole interface

Status: accepted · 2026-09-26 (T8.1) · amended twice the same day — see *A `POST`-only rule
is not enough* and *Toggles, and the state is measured rather than guessed*

## Context

Every route this server has answered so far answers a question. `/ping` says the desktop session
is alive, `/quotes` and `/weather` proxy upstreams the phone is not allowed to call directly
(invariant 1, [ADR 0002](0002-native-owns-network-io.md)). None of them changes the machine.

`POST /action/{id}` does. It mutes the speakers and the microphone of the PC it runs on, which
means for the first time the panel is an input device for the desktop and not only a display.

The server has **no authentication**, and that is a decision this project already made on
purpose. It binds to the LAN, it is started by and dies with a human's graphical session
([ADR 0004](0004-server-is-login-signal-and-proxy.md), [ADR 0010](0010-login-signal-is-session-scoped.md)),
and the phone talks to it over plain HTTP with a pinned address. Adding a token would mean the
token lives in the APK, which is the thing `.env` and `config.toml` exist to prevent
([ADR 0013](0013-local-configuration-boundaries.md)), and it would not help: anyone who can
reach the port can read the APK off `/app`.

Those two facts — no authentication, LAN-reachable — were compatible while the worst a stranger
on the Wi-Fi could do was read a stock price. They stop being obviously compatible the moment a
request changes the machine, so this record states what the endpoint may do and what it may
never do, before there is code to argue with.

## Decision

### An action is a name, and the name is the entire request

T3.7 wrote the constraint down before anything existed and it holds:

> the request carries an id and **nothing else** — never a command, path or argument

`/action/mute-audio` is the whole vocabulary. There is no body, no query string, no header that
changes behaviour. The id is matched against a set of literal strings the server already knows;
it is **never interpolated into a command line, a path, or an argument**, and it never selects a
file. A request either names something already in the table or it names nothing.

This is not a sanitising rule. There is no input to sanitise — the id is a key in a lookup, and
a key that misses returns 404 without running anything at all.

### The catalogue is in code; config only says which entries are enabled

`server/actions.py` holds the closed catalogue: id → per-platform argument list.
`config.toml` holds `actions = ["mute-audio", "mute-mic"]`, a list of names.

The direction matters. The owner can turn an action **off** by editing a text file; they cannot
turn a new one **on** by editing a text file, because there is nothing to write there that the
catalogue does not already contain. A config that could name a command would be a remote shell
with extra steps for anyone who can write that file, and — worse — it would move the security
argument out of the reviewed repository and into an untracked file nobody reads.

A name in `actions` that the catalogue does not know is a **fatal config error at load**, with
the name in the message. Not a 404 at request time: a typo has to be found by the person
restarting the server, with a console in front of them, rather than by someone at the desk
pressing a button that does nothing.

### Only actions that are safe to repeat

An attacker on the LAN can do **exactly the actions the owner enabled, as many times as they
like**. That is the honest threat model and there is no mitigation inside this design — so the
mitigation is the catalogue.

Every entry must be safe to repeat and safe to have happen at the wrong moment. `mute-audio`
and `mute-mic` are toggles: worst case somebody's music goes on and off, and the person sitting
at the machine undoes it with the keyboard in one second.

`shutdown`, `sleep`, `lock`, `reboot` and anything that writes a file are **deliberately absent
and stay absent**. They are not repeatable — the second `shutdown` lands on a machine that is
already gone, and the first one can lose work. An action that is destructive once is not made
acceptable by an allowlist; it is the allowlist's job to not contain it.

Adding an entry to the catalogue is a change to this record. If the new action is not
repeatable, the answer is no.

### Toggles, and the state is measured rather than guessed

The actions toggle, because the panel has no reliable way to know what the PC is doing and a
button that only mutes is half a button.

**Amended 2026-09-26, asked for from the chair**, after T8.2 shipped the buttons. The original
text said the response reports "the state the command itself observed", and on Linux that is
nothing at all: `wpctl` and `pactl` toggle in silence, so every press answered `unknown` and the
panel could draw no state. The ask was for the icon to carry a cross when the PC is muted.

A cross drawn on an inference would be exactly what the paragraph below forbids. So the state is
**measured**: after a toggle that says nothing, the server runs a second, **read-only** command
— `wpctl get-volume`, `pactl get-sink-mute` — and reports what the mixer actually holds. macOS
and Windows need none: their toggles already end on a word.

Three limits, and they are in the code rather than only here:

- **It is the last known state, not a live one.** Somebody at the keyboard can mute after the
  panel last asked and nothing tells the phone. The accessible name says "muted when last asked"
  rather than "muted", which is the same bargain the stale badge makes for a price.
- **A failed press does not move it.** The last thing the PC said is still the best thing known,
  and inventing a flip after a failure is precisely how a panel ends up claiming a microphone is
  off while it is live.
- **A read-back that fails is not a failed action.** The toggle already worked and the caller is
  owed its 200; all the read-back decides is whether a cross is drawn, and `unknown` is an answer
  the page knows how to render as "no claim".

A button that displays a state it is guessing is worse than a button that displays nothing: one
that says the microphone is live when it is not is a privacy failure, not a cosmetic one. That
rule is unchanged. What changed is that the panel stopped having to guess.

**"The microphone" means every input, not the default one.** Added 2026-09-26, after the first
press on the Windows box: three live inputs, the button muted the default while the owner was
talking into a headset, and the panel drew a cross over an open microphone. The state was
measured, and it was the wrong device's. On Windows the default input decides the direction and
every active capture endpoint follows it, so one press never leaves some muted and some live.
The speakers stay default-only, because sound from the wrong one is audible and a microphone
left open is not. Linux and macOS still toggle the default alone; that is T8.3.

### `POST` only, and no shell

`GET` is out, because a `GET` that changes the machine is one browser prefetch or one link
preview away from muting the PC by accident.

`subprocess.run` with an argument **list** and a timeout, never a shell, never a string. There
is no interpolation anywhere in the path from request to command, which is what makes the first
section of this record true in practice rather than in intent. The repository asserts it through
the AST rather than by grepping for the keyword, because a grep for it passes against the same
thing written with spaces around the equals sign.

One exception, named so it is not a surprise: the **macOS microphone** command is an AppleScript
literal that calls `do shell script` to read and write the remembered input level in
`dev.bosco.deskpanel`'s preferences. It is a constant in `server/actions.py` from end to end; the
only value concatenated into it is an integer AppleScript itself read from the audio API, and it
exists because the alternative — two commands per press, sequenced by a state machine in Python
— is more moving parts guarding the same constant. Nothing from the request is anywhere near it,
which is the property that matters.

### A `POST`-only rule is not enough, and this record said otherwise for an afternoon

**Amended 2026-09-26, found by review of the implementation this record governs.**

The section above rules out `GET` because a prefetch could fire it, and then the consequences
below called the endpoint "as trustworthy as the LAN". Both sentences were written on the belief
that requiring `POST` keeps a web page out. It does not.

A cross-origin form is a CORS **simple request** when its `enctype` is `text/plain`:

```html
<form method="post" enctype="text/plain"
      action="http://192.168.15.3:8777/action/mute-audio">
```

No preflight is sent, so nothing on this server is ever asked whether it consents. The attacker
cannot *read* the response — and does not need to, because the microphone is already muted. The
real reach of the endpoint was therefore not "anyone on the LAN" but **anyone whose page the
owner opens**, from anywhere.

The defence is not a token. A token would have to ship inside the APK, which is the thing
[ADR 0013](0013-local-configuration-boundaries.md) exists to prevent, and it would be readable
off `/app` anyway. It is that **a browser announces itself**: the Fetch standard requires an
`Origin` header on every non-`GET` request, and `Sec-Fetch-Site` rides along on the engines that
implement it. `POST /action/<id>` refuses with **403** when either is present.

The panel's own client is Java's `HttpURLConnection`, which sends neither. Nor do `curl` and
`probe.py`, which is what keeps T8.1's acceptance line meaning what it says, and what makes this
check free rather than a thing every future client has to remember.

A LAN attacker holding a socket can of course omit both headers. That is unchanged, and it is
the threat model this record already states. What is closed is the far wider hole of **not
needing to be on the LAN at all**.

The check sits *after* the allowlist, so an unknown id is still 404 whether a browser sent it or
not: it runs nothing either way, and ordering it first would only change what a probe means.

## Consequences

- **The server keeps no authentication.** This record is what makes that defensible, and it is
  defensible only while every catalogue entry stays repeatable and harmless. The day someone
  wants `lock`, the authentication question reopens — it does not get waived because an
  allowlist exists.
- **The endpoint is as trustworthy as the LAN, and only because of the browser check above.**
  `docs/SERVER-SETUP.md` already assumes a home network the owner controls; this makes that
  assumption load-bearing rather than incidental. On a shared or untrusted network,
  `actions = []` is the correct configuration and is the default. Without the `Origin` /
  `Sec-Fetch-Site` refusal this sentence would be false: the reach would be every website the
  owner visits, not every machine on their network.
- **`actions` changes shape.** It was a reserved empty table (`[actions]`); it is a list of names
  now. An empty table is still read as "nothing enabled", because that is what shipped in
  `config.example.toml` and in installed configs, and an update that refuses to start is a worse
  failure than a shape change (T3.13).
- **Every press is two commands on Linux**, a toggle and a read-only question. That is one extra
  local process per button press, on a machine with a person sitting at it, and it buys the only
  honest way to draw the cross.
- **Platform coverage is uneven and says so.** Linux (PipeWire, falling back to PulseAudio),
  macOS (`osascript`) and Windows (PowerShell against Core Audio, no third-party download) are
  implemented; anything else answers **501**, which is "this machine cannot", not "you asked
  wrongly".
- **A request carrying `Origin` or `Sec-Fetch-Site` is 403**, and any future client has to be
  one that does not set them — which every non-browser HTTP client already is. T8.2's bridge
  goes through Java for a different reason (invariant 1) and inherits this one for free.
- **Failure never leaks.** A non-zero exit or a timeout is a 500 with a short body; the command's
  stderr goes to the server log, where the owner can read it, and never into the response.

## References

- [ADR 0004](0004-server-is-login-signal-and-proxy.md) — why the server has no authentication.
- [ADR 0010](0010-login-signal-is-session-scoped.md) — why it is bound to a graphical session.
- [ADR 0013](0013-local-configuration-boundaries.md) — why nothing secret rides in the APK.
- `tasks/T3.7-action-stub.md` — the route reserved, and the constraint quoted above.
- `tasks/T8.1-actions-execute.md` — this decision's implementation.
