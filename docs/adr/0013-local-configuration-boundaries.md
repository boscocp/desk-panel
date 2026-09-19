# 0013 — Two kinds of local configuration, and the line between them

Status: accepted · 2026-09-16

## Context

Three things on this project are machine-specific and must never be committed: the brapi token,
the signing passwords, and the PC's LAN address. They arrived separately and ended up in three
unrelated places.

`server/config.json` was designed for the first, with `config.example.json` committed beside it
(T3.2). `keystore.properties` appeared for the second (T7.1). The third has no mechanism at all:
`res/xml/network_security_config.xml` carries a committed placeholder, `192.168.1.100`, and the
expectation was that an operator would edit that tracked file locally and remember never to
commit it.

That expectation broke the moment it met reality. The development machine is `192.168.15.3`, the
phone is on `192.168.3.100`, and the placeholder is on neither network — so the panel reports
offline for ever, which is exactly the failure the root `CLAUDE.md` warns about and which looks
like a bug in the app. Meanwhile "edit a tracked file and do not commit it" means the artefact
that gets tested is never the artefact that is committed, and this session has already swept
uncommitted work into unrelated commits twice with `git add -A`.

The obvious fix is a `.env`. The obvious fix is also how a token ends up inside an APK.

## Decision

**Two mechanisms, split by lifecycle, and the split is the point.**

| | `.env` | `server/config.json` |
| --- | --- | --- |
| Read at | **build time**, by Gradle | **run time**, by the server |
| Ends up | baked into the APK | on the PC only |
| Changing it needs | a rebuild and a reinstall | a server restart |
| Committed twin | `.env.example` | `server/config.example.json` |
| Holds | the PC's LAN address, signing passwords, the panel's orientation | the brapi token, tickers, city, intervals |

**API tokens never go in `.env`.** Not the brapi token, not any future one. The phone never talks
to a data provider — it talks to the PC, and the PC talks to the provider
([ADR 0004](0004-server-is-login-signal-and-proxy.md)). A token read by Gradle is a token
compiled into the APK, and an APK is a zip file. This is written into `.env.example` itself,
beside the keys, because the next person to add an integration will reach for `.env` by habit and
that habit is right everywhere except here.

**The test for which file something belongs in** is already a project rule, from
`server/CLAUDE.md`: *if a change to what the panel shows requires rebuilding the APK, the design
has been violated*. So anything the owner might want to change — tickers, city, intervals, the
night window — is runtime config by definition. `.env` is only for things that cannot be
anything else: the address the APK must be allowed to reach in cleartext, and the key it is
signed with.

**`PANEL_ORIENTATION` joined later (2026-09-19, T4.4)** and is worth recording as a test of the
rule above, because it does not look like an `.env` value at first. Which way up the panel sits
is not a secret and not an address — but it is decided once, when the phone goes into its stand,
by which side the cable leaves from, and the owner will never want to change it from a phone
they are looking at. It reached `.env` by failing the alternative rather than by fitting a
category: the manifest said `sensorLandscape`, the accelerometer re-decided on every Activity
creation, and once T4.4 made the wake relaunch the Activity the panel started coming back upside
down from a phone lying nearly flat. The direction had to stop being sensed. Once it stops being
sensed it has to be stored, and a property of one desk that is baked into the APK is precisely
what this ADR calls build-time config. Default `sensorLandscape`, so a fresh clone with no `.env`
behaves as it always did.

**`.env` absorbs `keystore.properties`.** Two build-time local files is one too many, and the
signing values fit the definition exactly. The `.env.example` names the keys with empty values;
`.gitignore` covers `.env` as it already covers `keystore.properties`.

**The committed placeholder stays.** `network_security_config.xml` keeps `192.168.1.100` in git
and Gradle substitutes the real address at build time from `.env`. T7.3's pre-public sweep,
which requires that no LAN address other than the placeholder appears in committed non-doc
source, keeps working unchanged — and now it is structurally true rather than true by the
operator remembering.

## Consequences

- A fresh clone builds without a `.env`, using the placeholder and debug signing, exactly as
  T7.1 already requires for signing. It produces an APK that installs and runs and cannot reach
  any PC — which is the honest outcome, and better than failing the build.
- The build must say which address it baked in. An APK silently built against the placeholder is
  indistinguishable from a network problem, and that ambiguity is the whole reason this ADR
  exists.
- T4.1's task file says the address comes from the reservation made in T3.8. That is still true;
  `.env` is where it is written down, not a replacement for making the reservation.
- Changing the PC's address now means editing `.env` and rebuilding. That is correct and
  unavoidable: cleartext permission is a property of the APK, not of the server.
- `keystore.properties` disappears. T7.1's acceptance greps for it by name, so that task's file
  is amended rather than left asserting the old layout.
- One more file joins the set a new machine needs before the project works end to end, alongside
  `server/config.json` and the keystore itself. `docs/INSTALL-PHONE.md` and `docs/BUILD.md` carry
  the list.

## Alternatives rejected

**A single `.env` for everything, including the token.** It is the conventional answer and it is
wrong here for one specific reason: Gradle reading a value means that value is in the APK.
Keeping the token in `server/config.json` is not tidiness, it is the mechanism by which the token
stays off the phone.

**Edit `network_security_config.xml` locally and do not commit it.** The status quo. It makes the
tested artefact differ from the committed one, relies on a human remembering under `git add -A`,
and this session demonstrated twice that the reliance is misplaced.

**Widen the cleartext exemption to the whole private range.** Removes the problem by removing the
protection. `android/CLAUDE.md` forbids it in as many words.

**Put the address in `server/config.json` and have the app fetch it.** Circular: the app cannot
reach the server to learn which server to reach.
