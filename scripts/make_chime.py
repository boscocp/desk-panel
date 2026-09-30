#!/usr/bin/env python3
"""Write the panel's default meeting chime, web/sounds/chime.wav (T9.5).

    python scripts/make_chime.py                       # the committed sound
    python scripts/make_chime.py --notes 523.25,783.99 --out web/themes/mine/chime.wav

Synthesised rather than downloaded, so its licence is not a question: this
script is the source, and the sound is as CC0 as the rest of the repository
(no third-party recording is in it). A theme that wants a different sound drops
any WAV, OGG or MP3 into its own directory and names it in defineTheme --
docs/THEMING.md § Meeting alerts -- and a sound from a CC0 library (Kenney,
freesound.org's CC0 filter) is as good as this one.

The shape is a soft bell: each note is a fundamental with two quiet overtones,
an eight-millisecond attack so it never clicks, and an exponential decay. Two
notes a little apart, rising, which reads as "attention" rather than "error".
Mono, 22.05 kHz, 16-bit, peak at -6 dBFS; the volume the panel plays it at is
`agenda_chime_volume` on the PC.
"""
import argparse
import math
import struct
import sys
import wave
from pathlib import Path

RATE = 22050
OUT = Path(__file__).resolve().parent.parent / "web" / "sounds" / "chime.wav"
NOTES = (659.25, 987.77)        # E5, then B5: a fifth, rising
GAP_S = 0.18                    # between the two notes' onsets
LENGTH_S = 1.8
DECAY_S = 0.45                  # e-folding time of each note
ATTACK_S = 0.008
PARTIALS = ((1.0, 1.0), (2.0, 0.28), (3.0, 0.08))   # (frequency ratio, weight)
PEAK = 0.5                      # -6 dBFS


def samples(notes=NOTES, rate=RATE):
    """Pure: the chime as floats in [-PEAK, PEAK]."""
    total = int(LENGTH_S * rate)
    out = [0.0] * total
    for index, freq in enumerate(notes):
        onset = int(index * GAP_S * rate)
        for n in range(total - onset):
            t = n / rate
            envelope = min(1.0, t / ATTACK_S) * math.exp(-t / DECAY_S)
            value = sum(w * math.sin(2 * math.pi * freq * r * t) for r, w in PARTIALS)
            out[onset + n] += envelope * value
    top = max(abs(v) for v in out) or 1.0
    return [PEAK * v / top for v in out]


def write(path, notes=NOTES):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(struct.pack("<h", int(v * 32767)) for v in samples(notes))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(frames)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--notes", default=",".join(str(n) for n in NOTES),
                        help="comma-separated frequencies in Hz, one per note")
    args = parser.parse_args(argv)
    notes = tuple(float(n) for n in args.notes.split(",") if n.strip())
    write(args.out, notes)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
