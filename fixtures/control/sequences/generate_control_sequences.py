#!/usr/bin/env python3
"""Generate the SXT-021 control-fixture input sequences.

fixtures/control/sequences/*.json are the source of truth (versioned ids,
`-vN` suffix rule per the SXT-012 library convention); re-running this
generator must reproduce them byte-for-byte. These are CONTROL-PLANE input
sequences: they contain no audio and make no DSP or fidelity claim.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def doc(name, d):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        json.dump(d, f, sort_keys=True, indent=1, separators=(",", ": "))
        f.write("\n")
    print("wrote", name)


def main():
    # 1. notes + steals + full control-event coverage (derived from
    #    seq-poly-8-v1's 8-voice block, SXT-012) --------------------------
    ev = [{"t": 0, "type": "note_on", "p1": n, "p2": 70}
          for n in (43, 50, 55, 59, 62, 67, 71, 74)]
    ev += [
        {"t": 28800, "type": "note_on", "p1": 48, "p2": 100},
        {"t": 28800, "type": "cc", "p1": 64, "p2": 127},
        {"t": 30000, "type": "pitch_bend", "p1": 8192 + 2000, "p2": 0},
        {"t": 32000, "type": "channel_pressure", "p1": 90, "p2": 0},
        {"t": 40000, "type": "cc", "p1": 1, "p2": 90},
        {"t": 41000, "type": "tempo", "p1": 500000 & 0xFFFF,
         "p2": 500000 >> 16},
        {"t": 44000, "type": "note_off", "p1": 50, "p2": 0},
    ]
    ev += [{"t": 57600, "type": "note_off", "p1": n, "p2": 0}
           for n in (50, 55, 59, 62, 67, 71, 74)]
    doc("ctl-notes-steal-v1.json", {
        "id": "ctl-notes-steal-v1", "schema_version": 1,
        "sample_rate": 48000, "block_size": 32, "voice_pool": 8,
        "blocks": 1805,
        "description": "Eight simultaneous voices (seq-poly-8-v1 chord, "
                       "SXT-012) then steals, sustain/modwheel CC, pitch "
                       "bend, channel pressure, tempo; releases. Exercises "
                       "allocation, oldest-active stealing, recorded control "
                       "events, and quantize-up latency (events off the "
                       "32-sample grid).",
        "derived_from": "fixtures/sequences/seq-poly-8-v1.json (chord t=0)",
        "coverage": ["poly:8", "steal:oldest", "cc:sustain+modwheel",
                     "pitch_bend", "channel_pressure", "tempo",
                     "latency:off-grid"],
        "events": ev})

    # 2. patch change: hard switch mid-notes + boundary-aligned switch ----
    ev = [
        {"t": 0, "type": "note_on", "p1": 60, "p2": 80},
        {"t": 33, "type": "note_on", "p1": 64, "p2": 80},
        {"t": 100, "type": "cc", "p1": 11, "p2": 70},
        {"t": 5000, "type": "patch_change", "p1": 3, "p2": 0},
        {"t": 5100, "type": "note_on", "p1": 72, "p2": 100},
        {"t": 20000, "type": "note_off", "p1": 72, "p2": 0},
        {"t": 64000, "type": "patch_change", "p1": 9, "p2": 0},
        {"t": 64000, "type": "note_on", "p1": 55, "p2": 64},
        {"t": 90000, "type": "note_off", "p1": 55, "p2": 0},
    ]
    doc("ctl-patch-change-v1.json", {
        "id": "ctl-patch-change-v1", "schema_version": 1,
        "sample_rate": 48000, "block_size": 32, "voice_pool": 8,
        "blocks": 2820,
        "description": "Two patch changes under the declared v1 HARD-SWITCH "
                       "semantics: a mid-notes switch clears all voices and "
                       "flushes queued events (recorded); a boundary-aligned "
                       "switch follows. Determinism of reset/patch-load "
                       "state.",
        "coverage": ["patch_change:hard_switch", "queue_flush",
                     "reset_determinism", "latency:off-grid"],
        "events": ev})

    # 3. burst exceeding the declared per-block reserve -------------------
    ev = [{"t": 0, "type": "note_on", "p1": 36 + i, "p2": 100}
          for i in range(12)]
    ev += [{"t": 64000, "type": "note_off", "p1": 36 + i, "p2": 0}
           for i in range(12)]
    doc("ctl-burst-overload-v1.json", {
        "id": "ctl-burst-overload-v1", "schema_version": 1,
        "sample_rate": 48000, "block_size": 32, "voice_pool": 8,
        "blocks": 2005,
        "description": "NEGATIVE-CONTROL SUPPORT: 12 coincident note-ons at t=0 "
                       "exceed the declared 8-events-per-block schedule "
                       "reserve (12 <= 16 queue capacity, so nothing drops). "
                       "The block is flagged event_reserve_exceeded, the "
                       "surplus spills to the next block with grown (bounded) "
                       "latency, and the render's worst-case schedule "
                       "accounting does NOT close. Detected, bounded, never "
                       "silent.",
        "coverage": ["overload:reserve_exceeded", "spill:bounded",
                     "no_drops"],
        "events": ev})

    # 4. burst exceeding queue capacity: explicit detected drops ----------
    ev = [{"t": 0, "type": "note_on", "p1": 36 + i, "p2": 100}
          for i in range(30)]
    ev += [{"t": 64000, "type": "note_off", "p1": 36 + i, "p2": 0}
           for i in range(16)]
    doc("ctl-queue-overflow-v1.json", {
        "id": "ctl-queue-overflow-v1", "schema_version": 1,
        "sample_rate": 48000, "block_size": 32, "voice_pool": 8,
        "blocks": 2005,
        "description": "NEGATIVE CONTROL (issue #14 acceptance): 30 "
                       "coincident events exceed the declared reserve AND "
                       "the 16-deep queue: events are dropped with explicit "
                       "queue_overflow records (in-model and in-DUT), never "
                       "silently. Bounded overload detection.",
        "coverage": ["overload:queue_overflow", "drops:explicit", "bounded"],
        "events": ev})


if __name__ == "__main__":
    main()
