#!/usr/bin/env python3
"""SXT-012: deterministic generator for the versioned event-sequence library.

Writes one JSON file per sequence into fixtures/sequences/. The committed JSON
files are the source of truth for rendering; this generator is retained for
provenance and review. Regenerating with different content requires new
sequence ids (-v2), never in-place edits of a -v1 file.

All times are integer sample indices at 48 kHz. Ids are stable:
seq-<family>-<descriptor>-vN.
"""

import json
import os

SR = 48000
SEQ_DIR = os.path.dirname(os.path.abspath(__file__))

SCHEMA_VERSION = 1

# Shared timing vocabulary (samples at 48 kHz)
MS = lambda ms: int(round(SR * ms / 1000))  # noqa: E731
SHORT_HOLD = MS(200)
LONG_HOLD = MS(1200)
NOTE_GAP = MS(175)
VELOCITY_SOFT = 30
VELOCITY_MEDIUM = 70
VELOCITY_HARD = 120
NOTE_LOW = 36   # C2
NOTE_MID = 60   # C4
NOTE_HIGH = 84  # C6


def seq(
    seq_id,
    description,
    coverage,
    events,
    tail_s=2.5,
    settle_s=0.25,
    notes="",
    tempo_events_applied_by_renderer=True,
):
    events = [e for _, e in sorted(enumerate(events), key=lambda p: (p[1]["t"], p[0]))]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": seq_id,
        "sample_rate": SR,
        "description": description,
        "coverage": coverage,
        "events": events,
        "tail_s": tail_s,
        "settle_s": settle_s,
        "tempo_events_renderable": tempo_events_applied_by_renderer,
        "notes": notes,
    }


def note_on(t, note, velocity, channel=0):
    return {"t": t, "type": "note_on", "channel": channel, "note": note, "velocity": velocity}


def note_off(t, note, velocity=0, channel=0):
    return {"t": t, "type": "note_off", "channel": channel, "note": note, "velocity": velocity}


def cc(t, controller, value, channel=0):
    return {"t": t, "type": "cc", "channel": channel, "controller": controller, "value": value}


def bend(t, value, channel=0):
    return {"t": t, "type": "pitch_bend", "channel": channel, "value": value}


def pressure(t, value, channel=0):
    return {"t": t, "type": "channel_pressure", "channel": channel, "value": value}


def tempo(t, bpm):
    return {"t": t, "type": "tempo", "bpm": bpm}


def build_sequences():
    out = []

    # 1. Registers x velocities, short holds, releases --------------------
    ev = []
    for i, (note, vel) in enumerate(
        [
            (n, v)
            for n in (NOTE_LOW, NOTE_MID, NOTE_HIGH)
            for v in (VELOCITY_SOFT, VELOCITY_MEDIUM, VELOCITY_HARD)
        ]
    ):
        ev.append(note_on(i * (SHORT_HOLD + NOTE_GAP), note, vel))
        ev.append(note_off(i * (SHORT_HOLD + NOTE_GAP) + SHORT_HOLD, note))
    out.append(
        seq(
            "seq-notes-coverage-v1",
            "Low/mid/high registers x soft/medium/hard velocities; short holds "
            "(200 ms) with released notes and inter-note gaps for release tails.",
            ["register:low", "register:mid", "register:high",
             "velocity:soft", "velocity:medium", "velocity:hard",
             "hold:short", "release:note-off"],
            ev,
        )
    )

    # 2. Short vs long holds, incl. release velocity ----------------------
    ev = [
        note_on(0, NOTE_MID, VELOCITY_MEDIUM),
        note_off(SHORT_HOLD, NOTE_MID),
        note_on(MS(500), NOTE_MID, VELOCITY_MEDIUM),
        note_off(MS(500) + LONG_HOLD, NOTE_MID),
        note_on(MS(2000), NOTE_MID, VELOCITY_MEDIUM),
        note_off(MS(2000) + SHORT_HOLD, NOTE_MID),
        note_on(MS(2500), NOTE_MID, VELOCITY_MEDIUM),
        note_off(MS(2500) + LONG_HOLD, NOTE_MID, velocity=100),
    ]
    out.append(
        seq(
            "seq-notes-holds-v1",
            "Short (200 ms) vs long (1200 ms) holds at mid register; final "
            "note-off carries release velocity 100 to exercise release-velocity paths.",
            ["hold:short", "hold:long", "release:note-off", "release:release-velocity"],
            ev,
        )
    )

    # 3. Repeated notes ---------------------------------------------------
    ev = [
        note_on(0, NOTE_MID, VELOCITY_HARD), note_off(MS(60), NOTE_MID),
        note_on(MS(100), NOTE_MID, VELOCITY_HARD), note_off(MS(160), NOTE_MID),
        note_on(MS(200), NOTE_MID, VELOCITY_HARD), note_off(MS(260), NOTE_MID),
        note_on(MS(300), NOTE_MID, VELOCITY_HARD), note_off(MS(360), NOTE_MID),
        note_on(MS(500), NOTE_MID, VELOCITY_HARD), note_off(MS(700), NOTE_MID),
        note_on(MS(800), NOTE_MID, VELOCITY_HARD), note_off(MS(1000), NOTE_MID),
        note_on(MS(1100), NOTE_MID, VELOCITY_HARD), note_off(MS(1300), NOTE_MID),
        note_on(MS(1400), NOTE_MID, VELOCITY_HARD), note_off(MS(1600), NOTE_MID),
    ]
    out.append(
        seq(
            "seq-notes-repeated-v1",
            "Repeated same-pitch notes: four fast retriggers (100 ms spacing, "
            "60 ms holds) then four moderate repeats (300 ms spacing, 200 ms holds).",
            ["repeated-notes", "release:note-off"],
            ev,
        )
    )

    # 4. Declared polyphony: 8 simultaneous voices ------------------------
    chord = [43, 50, 55, 59, 62, 67, 71, 74]
    ev = [note_on(0, n, VELOCITY_MEDIUM) for n in chord]
    ev += [note_off(LONG_HOLD, n) for n in chord]
    out.append(
        seq(
            "seq-poly-8-v1",
            "Declared fixture polyphony: eight simultaneous voices held for "
            "1200 ms, then released together. Plan section 3 hypothesis is "
            "eight allocated scene voices; patches whose own polyphony limit "
            "is lower will silently voice fewer notes (recorded in metadata).",
            ["polyphony:8"],
            ev,
            notes="Fixture polyphony target is 8 simultaneous voices (plan "
                  "section 3). Per-preset audible polyphony is bounded by the "
                  "preset's own polyphony limit.",
        )
    )

    # 5. Tempo changes ----------------------------------------------------
    ev = [tempo(0, 120), tempo(MS(1000), 90), tempo(MS(2000), 150)]
    for i in range(12):
        t = i * MS(250)
        ev.append(note_on(t, NOTE_MID, 90))
        ev.append(note_off(t + MS(200), NOTE_MID))
    out.append(
        seq(
            "seq-tempo-change-v1",
            "Tempo steps 120 -> 90 -> 150 BPM against evenly spaced repeated "
            "notes; exercises temposync'd LFO/FX clocks where the preset uses them.",
            ["tempo:change", "repeated-notes"],
            ev,
            tempo_events_applied_by_renderer=False,
            notes="surgepy exposes no transport-tempo setter (engine time_data "
                  "is not bound); the surgepy renderer records tempo events but "
                  "cannot apply them mid-render and renders at the pinned "
                  "120 BPM. Renderable only by a tempo-capable harness "
                  "(documented limitation, SXT-012 evidence).",
        )
    )

    # 6. Sustain pedal ----------------------------------------------------
    ev = [
        note_on(0, NOTE_MID, VELOCITY_MEDIUM),
        cc(MS(100), 64, 127),
        note_off(MS(300), NOTE_MID),
        note_on(MS(600), 64, VELOCITY_MEDIUM),
        note_off(MS(800), 64),
        cc(MS(1200), 64, 0),
    ]
    out.append(
        seq(
            "seq-sustain-pedal-v1",
            "Sustain pedal (CC64) down before note-offs: two notes released "
            "while the pedal holds them; pedal up releases both.",
            ["sustain-pedal", "release:pedal"],
            ev,
        )
    )

    # 7. Pitch bend -------------------------------------------------------
    ev = [
        note_on(MS(100), NOTE_MID, VELOCITY_MEDIUM),
        bend(MS(400), 8191),
        bend(MS(800), -8192),
        bend(MS(1200), 0),
        note_off(MS(1600), NOTE_MID),
    ]
    out.append(
        seq(
            "seq-pitchbend-v1",
            "Pitch bend to full up (+8191), full down (-8192), centered; "
            "bend range is the preset's own (Surge default 2 semitones).",
            ["pitch-bend"],
            ev,
        )
    )

    # 8. Modulation wheel -------------------------------------------------
    ev = [note_on(MS(100), NOTE_MID, VELOCITY_MEDIUM)]
    for i, v in enumerate((32, 64, 96, 127)):
        ev.append(cc(MS(200) + i * MS(100), 1, v))
    ev += [cc(MS(700), 1, 0), note_off(MS(1300), NOTE_MID)]
    out.append(
        seq(
            "seq-modwheel-v1",
            "Modulation wheel (CC1) staircase 0 -> 127 -> 0 under a held note.",
            ["mod-wheel"],
            ev,
        )
    )

    # 9. Channel pressure -------------------------------------------------
    ev = [
        note_on(MS(100), NOTE_MID, VELOCITY_MEDIUM),
        note_on(MS(100), 64, VELOCITY_MEDIUM),
        pressure(MS(200), 42),
        pressure(MS(300), 84),
        pressure(MS(400), 127),
        pressure(MS(500), 0),
        note_off(MS(1300), NOTE_MID),
        note_off(MS(1300), 64),
    ]
    out.append(
        seq(
            "seq-pressure-v1",
            "Channel pressure (aftertouch) staircase 0 -> 127 -> 0 under a "
            "two-note chord; audible only where the preset routes aftertouch.",
            ["channel-pressure"],
            ev,
            notes="Polyphonic pressure is not part of this sequence; the "
                  "library ships channel pressure per the SXT-012 deliverable.",
        )
    )

    # 10. Macro sweeps -----------------------------------------------------
    ev = [note_on(MS(100), NOTE_MID, VELOCITY_MEDIUM)]
    for i, v in enumerate((32, 64, 96, 127)):
        ev.append(cc(MS(200) + i * MS(100), 41, v))  # macro 1 (default CC 41)
    ev.append(cc(MS(700), 41, 0))
    for i, v in enumerate((32, 64, 96, 127)):
        ev.append(cc(MS(800) + i * MS(100), 42, v))  # macro 2 (default CC 42)
    ev += [cc(MS(1300), 42, 0), note_off(MS(1700), NOTE_MID)]
    out.append(
        seq(
            "seq-macro-sweep-v1",
            "Macro 1 then Macro 2 swept 0 -> 127 -> 0 (default macro CCs 41/42 "
            "for a fresh pinned instance); audible only where the preset "
            "routes macros.",
            ["macro-sweep"],
            ev,
            notes="Macro CC binding comes from engine defaults (SurgeStorage "
                  "controllers[i] = 41 + i); a user config could remap them, "
                  "but the pinned oracle runs with default settings.",
        )
    )

    return out


def main():
    os.makedirs(SEQ_DIR, exist_ok=True)
    for s in build_sequences():
        path = os.path.join(SEQ_DIR, s["id"] + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, sort_keys=True)
            f.write("\n")
        print("wrote", path)
    # sanity: last event time and duration
    for s in build_sequences():
        last = max(e["t"] for e in s["events"])
        dur = (last + int(s["tail_s"] * SR)) / SR
        print(f"{s['id']}: last_event={last} ({last/SR:.3f}s) rendered={dur:.3f}s")


if __name__ == "__main__":
    main()
