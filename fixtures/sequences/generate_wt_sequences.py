#!/usr/bin/env python3
"""SXT-026 fixture sequences (schema_version 1, same contract as SXT-012).

seq-wt-base-v1          C4 hold + release; the workhorse for morph/mip and
                        the original-preset reference render.
seq-wt-pitch-extremes-v1 MIDI 24 / 96 / 108 short holds: drives wavetable
                        mip selection from mip 0 (low) to mip 6 (high) and
                        the AA behavior at both extremes.
seq-wt-unison16-v1      short C3/C4 for the MAX_UNISON (16) fixture; kept
                        short because 16 unison voices are the worst-case
                        schedule for the RTL testbench.

Deterministic: retrigger is a patch property (Kick.fxp WT osc has it on),
all events are note on/off only; no CC (no modulation is routed to the WT
osc in this slice).
"""
import json
import os

DIR = os.path.dirname(os.path.abspath(__file__))


def seq(id_, description, coverage, events, tail_s=1.5):
    events = sorted(events, key=lambda e: (e["t"],))
    return {
        "schema_version": 1,
        "id": id_,
        "description": description,
        "coverage": coverage,
        "tail_s": tail_s,
        "events": events,
    }


def note(t, on, n=60, vel=32):
    return {"type": "note_on" if on else "note_off", "t": t, "channel": 0,
            "note": n, "velocity": 32 if on else 0}


SEQS = [
    seq("seq-wt-base-v1",
        "C4 hold (1 s) + release; the wavetable workhorse fixture",
        ["hold:long", "release:note-off", "wt:mip-mid"],
        [note(0, True, 60), note(48000, False, 60)]),
    seq("seq-wt-pitch-extremes-v1",
        "MIDI 60 / 96 / 120 short holds: with the preset's stored osc "
        "octave (-3) this spans osc pitches 24..84 (wavetable mip 0..4)",
        ["pitch:extreme-low", "pitch:extreme-high", "wt:mip-sweep"],
        [note(0, True, 60), note(12000, False, 60),
         note(24000, True, 96), note(36000, False, 96),
         note(48000, True, 120), note(60000, False, 120)],
        tail_s=1.0),
    seq("seq-wt-pitch-extremes-hi-v1",
        "MIDI 24 / 96 / 120 with the declared octave-0 fixture: osc pitches "
        "24..120, reaching wavetable mip 5 and mip 6",
        ["pitch:extreme-high", "wt:mip5", "wt:mip6"],
        [note(0, True, 24), note(12000, False, 24),
         note(24000, True, 96), note(36000, False, 96),
         note(48000, True, 120), note(60000, False, 120)],
        tail_s=1.0),
    seq("seq-wt-unison16-v1",
        "short C4 + D4 for the MAX_UNISON=16 fixture (worst-case schedule; "
        "notes chosen so osc pitch = note - 36 stays in [24, 148])",
        ["unison:max-16", "poly:2-overlap"],
        [note(0, True, 60), note(8000, True, 72),
         note(24000, False, 60), note(24000, False, 72)],
        tail_s=1.0),
]

for s in SEQS:
    p = os.path.join(DIR, s["id"] + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1, sort_keys=True)
        f.write("\n")
    print("wrote", p)
