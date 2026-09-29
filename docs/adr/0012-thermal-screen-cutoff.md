# 0012 — Temperature is the second authority over the screen

Status: accepted · 2026-09-16 · implemented in T5.5 (`ThermalState.BLANK_AT_C = 45.0`,
`CLEAR_AT_C = 38.0`); T4.4 kept real sleep, so point 2's distinction stands

## Context

Invariant 3 has one sentence and one driver: *screen state is driven by PC state, never by a
timeout*. Online holds `FLAG_KEEP_SCREEN_ON`; offline releases it and lets the phone sleep.
One input, one output, nothing to arbitrate.

ADR 0008 lists what the app can do about ageing the device, and heat is the first item on it —
"heat is what kills lithium cells; better to read the number than discover it by bulge". But
everything 0008 proposes about heat is **passive**: show the number, warn above 40 degrees, and
hope somebody looks. The panel spends its life plugged in, in a stand that restricts airflow,
painting a bright image for hours. The largest heat source it controls is the screen it is
holding on, and the current design has no way to act on the one measurement it already takes.

Android throttles thermally and will shut down somewhere near 50-60 degrees, so there is a net.
It is a hard net, well past where a lithium cell starts losing life.

## Decision

**Temperature becomes a second authority over the screen, ranking above PC state.** The screen
is on only when the PC is online **and** the device is not too hot. Either condition alone can
turn it off; both must hold to keep it on.

This is a real amendment to invariant 3, which is why it is an ADR and not a task note. The
invariant now reads: *screen state is driven by PC state and device temperature, never by a
timeout.* The "never by a timeout" half is untouched and still the point — a temperature is a
measured condition, not elapsed time, and it is read from a push broadcast rather than polled
(T5.4, step 5).

### Hysteresis is not optional

A single threshold makes the panel oscillate, and the oscillation is self-driving: turning the
screen on generates the heat that turns it off. Two thresholds, far enough apart that the device
has actually cooled before the screen returns:

| | |
| --- | --- |
| Screen off at | **45 degrees** |
| Screen back on at | **38 degrees** |
| Existing warning from T5.4 | 40 degrees |

The warning at 40 sits inside the gap on purpose: it fires while the panel is still lit, so the
first thing that happens is visible, and the blanking is the second.

### The failure mode this must not create

A black screen already means one thing in this project: *the PC is off*. That is the whole
product. A second cause of black is the most expensive confusion available here — the owner
looks over, sees nothing, and concludes the PC died or the app broke.

Three things keep them apart:

1. **The colour ramp warns first.** The temperature reading on the DEVICE card goes from its
   normal colour through yellow to red as it climbs toward the cutoff. By the time the screen
   blanks, it has been visibly reddening for a while. This is the decisive piece: the state is
   legible *before* it is silent.
2. **Thermal blanking uses the ADR 0005 fallback, not real sleep.** `screenBrightness = 0f` with
   a black render, rather than releasing `FLAG_KEEP_SCREEN_ON`. The app stays foreground and
   keeps reading the broadcast, so it can bring the screen back by itself. Real sleep is for the
   PC-offline case, where waking is driven from outside.
3. **A distinct logcat marker.** `screen=sleep` is PC-driven. Thermal blanking emits
   `screen=thermal` and `screen=thermal-clear`, so the E2E suite and any future diagnosis can
   tell the two apart. Renaming or merging these breaks that distinction — see ADR 0009 on why
   markers are the only screen-state signal this project trusts.

### Yellow and red are a third and fourth exception to the palette

The panel is pink on black, with green already admitted as an exception for gains because it is
semantic and conventional rather than decorative. Yellow and red enter on exactly that
argument, and no wider one: they mean *approaching a limit* and *at a limit*, they are the
universal convention for it, and nothing else on the panel uses them.

## Consequences

- The screen-state machine gains a second input. It must be written so both inputs are explicit
  and the arbitration is one place, not two conditionals that happen to agree.
- **This lands after T4.3 and T4.4.** Those tasks build the screen-state machinery and decide
  whether ADR 0005 keeps its primary mechanism or falls back to brightness zero. Adding a second
  authority before the first one exists is how unreproducible bugs get made. T5.5 carries the
  work and declares them as prerequisites.
- `PcState` stays pure and stays about the PC. The thermal decision is separate state; combining
  them into one class would make the PC poller depend on a battery broadcast for no reason.
- The thresholds are constants, not config. They are about the hardware's tolerance, not about
  what the owner wants displayed, and the config file is documented as the place where display
  choices live.
- If T4.4 concludes that MIUI cannot be trusted to wake the screen, the brightness-zero fallback
  becomes the mechanism for both cases and point 2 above stops being a distinction. That is
  acceptable; the marker in point 3 still separates them.

## Alternatives rejected

**Leave it to Android's thermal throttling.** It acts near 50-60 degrees, well past where cell
life is affected, and it acts on the whole device rather than on the one thing this app
controls. It is a net, not a policy.

**Warn only, never act** — which is what ADR 0008 currently implies. It requires somebody to be
looking at the panel at the moment it matters, and the panel exists precisely to be glanced at
rather than watched.

**One threshold.** Rejected above: the screen is itself the heat source, so a single threshold
oscillates by construction.

**Reduce brightness instead of blanking.** Tempting, and it may well be the right first step
inside the ramp, but it is not a substitute for a cutoff: a dim screen still draws power and
still paints. T5.5 may implement dimming as an intermediate stage; the cutoff stays.
