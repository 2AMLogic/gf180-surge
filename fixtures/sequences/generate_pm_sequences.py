#!/usr/bin/env python3
"""SXT-043 leaf sequence generator (playmode submode pm_mono_st_fp).

The three sequences issue #77 names (`seq-notes-coverage-v1`,
`seq-notes-repeated-v1`, `seq-notes-holds-v1`) are all strictly
NON-OVERLAPPING: every note-off precedes the next note-on.  Under
pm_mono_st_fp they exercise the submode's *fingered-portamento anchoring*
(a fresh note-on must NOT glide, where Poly and pm_mono_st both do) and its
*voice reuse / reclaim* behavior -- but they can never reach a legato
transition, because a legato needs two keys down at once.

This generator adds the missing stimulus, as a declared leaf fixture in the
same schema, so the frozen model and the RTL are exercised over the whole
submode rather than half of it:

  `seq-mono-fingered-v1`
    1. 36 -> +48 -> +60 held together: two LEGATO-UP transitions, the second
       arriving MID-GLIDE (portaphase < 1), which is the pinned
       `SurgeVoice::legato` re-anchor branch;
    2. releases from the top down: each note-off hands the mono voice to a
       still-held key (`releaseNotePostHoldCheck`, priority-mode scan),
       ending in a real release when the last key lifts;
    3. a wide downward legato (72 -> 36) after the glide has completed
       (portaphase > 1: the other `legato` branch), followed by a note-off
       for a key the voice no longer holds (a declared no-op path);
    4. a legato down to a LOWER held key (67 released while 60 is held);
    5. a same-key legato (55 pressed twice while held), which drives the
       `floor(pkey + 0.5)` / `priorpkey` bookkeeping with a zero interval.

  `seq-mono-reclaim-v1`
    The named sequences also never reach the RECLAIM path: their inter-note
    gaps are longer than the carriers' amp-envelope release, so by the time
    the next note-on arrives there is no voice left to reclaim and the
    engine simply constructs a new one.  This sequence re-presses inside the
    release tail (15 ms gaps against a ~30 ms release), which is what makes
    `monoVoiceEnvelopeMode` observable: `RESTART_FROM_LATEST` reclaims the
    dying voice (`reclaimVoiceFor` -> `restartAEGFEGAttack(level)`,
    `resetVelocity`, and -- for a Sine slot -- NO oscillator re-init), while
    `RESTART_FROM_ZERO` would uber-release it and build a new one.  The
    velocity changes across the repeats so the SLOW_EXP velocity smoother
    the reclaim path re-targets is exercised too.

Written with the same schema and conventions as
`fixtures/sequences/generate_sequences.py` (schema_version 1, 48 kHz,
integer-sample timestamps, `settle_s` 0.25, `tail_s` 2.5).
"""

import json
import os

SR = 48000
SEQ_DIR = os.path.dirname(os.path.abspath(__file__))
SETTLE_S = 0.25
TAIL_S = 2.5


def MS(ms):
    return int(round(ms * SR / 1000.0))


def note_on(t, note, velocity, channel=0):
    return {"channel": channel, "note": note, "t": t, "type": "note_on",
            "velocity": velocity}


def note_off(t, note, velocity=0, channel=0):
    return {"channel": channel, "note": note, "t": t, "type": "note_off",
            "velocity": velocity}


def build_sequences():
    ev = [
        # 1. legato up, the second one mid-glide
        note_on(MS(0), 36, 100),
        note_on(MS(100), 48, 100),
        note_on(MS(150), 60, 100),
        # 2. hand the mono voice back down, key by key, then release
        note_off(MS(300), 60),
        note_off(MS(400), 48),
        note_off(MS(600), 36),
        # 3. wide downward legato after the glide completed, then a note-off
        #    for a key the voice has already legato'd away from
        note_on(MS(900), 72, 90),
        note_on(MS(1100), 36, 90),
        note_off(MS(1200), 72),
        note_off(MS(1400), 36),
        # 4. legato down to a lower held key
        note_on(MS(1700), 60, 70),
        note_on(MS(1800), 67, 70),
        note_off(MS(1900), 67),
        note_off(MS(2100), 60),
        # 5. same-key legato (zero interval)
        note_on(MS(2400), 55, 110),
        note_on(MS(2500), 55, 110),
        note_off(MS(2600), 55),
    ]
    ev_reclaim = [
        note_on(MS(0), 60, 30),
        note_off(MS(40), 60),
        note_on(MS(55), 60, 120),       # reclaim, same key, velocity jump
        note_off(MS(95), 60),
        note_on(MS(110), 67, 120),      # reclaim, key up (fingered: no glide)
        note_off(MS(150), 67),
        note_on(MS(165), 48, 60),       # reclaim, wide key down
        note_off(MS(205), 48),
        note_on(MS(400), 60, 100),      # tail fully decayed: fresh create
        note_off(MS(440), 60),
    ]
    return [{
        "id": "seq-mono-fingered-v1",
        "schema_version": 1,
        "sample_rate": SR,
        "description": (
            "Overlapping (fingered) note stimulus for the mono playmode "
            "submodes: legato up (incl. one arriving mid-glide), note-off "
            "hand-over to still-held keys, a wide downward legato after the "
            "glide completed, a note-off for a key the voice already left, "
            "a legato down to a lower held key, and a same-key legato."),
        "notes": (
            "Added by SXT-043 (issue #77). The three seq-notes-* sequences "
            "are strictly non-overlapping and therefore cannot reach a "
            "legato transition at all; this sequence supplies the missing "
            "half of the submode's stimulus. No CC, aftertouch, pitch-bend "
            "or pedal events: every modulation source the carriers route "
            "from stays identically zero, as the fixture configuration "
            "declares."),
        "coverage": [
            "legato:up", "legato:down", "legato:mid-glide",
            "legato:same-key", "legato:release-handover",
            "portamento:fingered", "release:note-off",
        ],
        "settle_s": SETTLE_S,
        "tail_s": TAIL_S,
        "tempo_events_renderable": True,
        "events": ev,
    }, {
        "id": "seq-mono-reclaim-v1",
        "schema_version": 1,
        "sample_rate": SR,
        "description": (
            "Re-pressed notes INSIDE the amp-envelope release tail (15 ms "
            "gaps against a ~30 ms release), with changing velocity and key, "
            "then one repeat after the tail has fully decayed. Makes the "
            "mono reclaim path and monoVoiceEnvelopeMode observable."),
        "notes": (
            "Added by SXT-043 (issue #77). The seq-notes-* gaps all exceed "
            "the carriers' release time, so none of them can reach the "
            "reclaim path at all. No CC, aftertouch, pitch-bend or pedal "
            "events."),
        "coverage": [
            "reclaim:same-key", "reclaim:key-change",
            "reclaim:velocity-change", "repeated-notes",
            "release:note-off",
        ],
        "settle_s": SETTLE_S,
        "tail_s": TAIL_S,
        "tempo_events_renderable": True,
        "events": ev_reclaim,
    }]


def main():
    for s in build_sequences():
        path = os.path.join(SEQ_DIR, s["id"] + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, sort_keys=True)
            f.write("\n")
        print("wrote", path)
        last = max(e["t"] for e in s["events"])
        dur = (last + int(s["tail_s"] * SR)) / SR
        print(f"{s['id']}: last_event={last} ({last / SR:.3f}s) "
              f"rendered={dur:.3f}s")


if __name__ == "__main__":
    main()
