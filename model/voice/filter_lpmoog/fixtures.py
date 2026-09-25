#!/usr/bin/env python3
"""SXT-039 fixture definitions: control planes + stimulus for the LP Legacy
Ladder leaf.

ONE definition, consumed by BOTH sides of the reference leg:

  * the frozen model runner (`run_filter_leg.py`) quantizes the fixture's
    float32 control words and input samples once into Q10.21 and runs the
    frozen model / emits the RTL stimulus;
  * the pinned-kernel reference renderer (`tools/render_lpmoog_reference.py`)
    feeds the identical float32 values to the pinned filter code built
    OUTSIDE this repository (DR-0009).

so that the two legs can never silently diverge in their inputs.

Fixture ingredients and their provenance (all committed, all reproducible
without the oracle host):

  control plane   the carriers' real normalized filter-unit parameters
                  (cut / res / keytrack / envmod / subtype, scene keytrack
                  root) read from `corpus/normalized/graphs.jsonl`
                  (sha256 c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715)
  note plane      the issue's declared sequences
                  (`fixtures/sequences/seq-notes-*.json`): per-block MIDI
                  pitch for the keytrack term and the voice-creation resets
  filter EG       a DECLARED piecewise-linear trajectory (below), NOT an
                  engine readback: the filter-envelope definition state is
                  absent from normalized schema rev 1.0.0 and reading it
                  requires the pinned engine.  Every artifact records
                  `fenv_source: declared-trajectory` so no reader can mistake
                  it for engine state.  The env-mod ARITHMETIC is referenced;
                  the carriers' real envelope SHAPES are not (see the
                  engine-integrated leg, recorded NOT_RUN in
                  reports/SXT-039/EVIDENCE.md).
  stimulus        the committed SXT-037 tap bundles' filter-unit INPUT
                  streams (real pinned-engine voice audio at the filter-stage
                  boundary, reports/sxt-037/artifacts/bundle-*/units.bin),
                  optionally with a declared gain, plus deterministic
                  synthetic drives for the corner cases.  Only the bundles'
                  INPUT column is used; their LP 12 dB output column is never
                  read here and is not a reference for this leaf.

Test configurations, never adapted presets: nothing in this file promotes any
preset to supported.
"""

import json
import math
import os
import struct

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
BUNDLE_ROOT = os.path.join(REPO, "reports", "sxt-037", "artifacts")
SEQ_DIR = os.path.join(REPO, "fixtures", "sequences")

BLOCK_SIZE = 32            # engine block (48 kHz samples)
BLOCK_SIZE_OS = 64         # OS samples per block
FUT_LPMOOG = 3


class Refuse(Exception):
    """Fail-closed fixture boundary."""


def f32(x):
    """Round a Python float to float32 (both legs see identical values)."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


# ------------------------------------------------------------- carriers
# Carrier instances are resolved from the committed normalized graphs at run
# time (never hand-copied numbers): (path, scene, unit).
CARRIERS = {
    "king-b1": ("resources/data/patches_3rdparty/Bluelight/Pads/King.fxp", 1, 0),
    "king-b2": ("resources/data/patches_3rdparty/Bluelight/Pads/King.fxp", 1, 1),
    "chords": ("resources/data/patches_3rdparty/Damon Armani/Pads/House Of Chords.fxp", 0, 1),
    "disturb": ("resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Disturbances.fxp", 0, 0),
}


def load_carrier(name):
    """Read one carrier's LP Legacy Ladder unit from the committed graphs."""
    rel, scene_i, unit_i = CARRIERS[name]
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("p") != rel:
                continue
            scene = rec["g"]["sc"][scene_i]
            fu = scene["fu"][unit_i]
            if fu["t"] != FUT_LPMOOG:
                raise Refuse(f"{name}: unit {unit_i} of scene {scene_i} is type "
                             f"{fu['t']} ({fu.get('tn')}), not fut_lpmoog")
            return {
                "rel": rel,
                "blob": rec.get("sha"),
                "scene": scene_i,
                "unit": unit_i,
                "cut": f32(fu["cut"]),
                "reso": f32(fu["res"]),
                "keytrack": f32(fu["kt"]),
                "envmod": f32(fu["em"]),
                "subtype": int(fu["st"]),
                "subtype_name": fu.get("stn"),
                "keytrack_root": f32(scene["ktR"]),
            }
    raise Refuse(f"{name}: carrier {rel} not found in {GRAPHS}")


# ------------------------------------------------------------ note plane
def note_plane(sequence, n_blocks):
    """Per-block (pitch, gate, reset) from a declared sequence file.

    Dispatch rule (landed SXT-022 convention): an event at sample t fires in
    block ceil(t / 32).  A note_on creates the voice -> the filter unit's
    registers are zeroed and its coefficient maker takes the FirstRun path
    (SurgeVoice.cpp memset(&FBP.FU[u]) + CM[u].Reset()).  Monophonic fixture
    convention: one voice at a time (the leaf models ONE filter instance; a
    second overlapping voice would be a second instance, covered by the
    two-instance carrier fixture pair king-b1 / king-b2).
    """
    with open(os.path.join(SEQ_DIR, sequence + ".json"), encoding="utf-8") as f:
        seq = json.load(f)
    events = sorted(seq["events"], key=lambda e: (e["t"], e["type"] != "note_on"))
    plane = []
    pitch = 60.0
    gate = False
    gate_block = 0
    rel_block = 0
    for b in range(n_blocks):
        reset = False
        for ev in events:
            if -(-ev["t"] // BLOCK_SIZE) != b:
                continue
            if ev["type"] == "note_on":
                pitch = float(ev["note"])
                gate = True
                gate_block = b
                reset = True
            elif ev["type"] == "note_off" and gate:
                gate = False
                rel_block = b
        plane.append({"pitch": f32(pitch), "gate": gate, "reset": reset,
                      "since": b - (gate_block if gate else rel_block),
                      "gate_block": gate_block})
    return plane


# DECLARED filter-EG trajectory (NOT an engine readback): piecewise linear,
# attack 24 blocks 0 -> 1, decay 48 blocks 1 -> 0.4 sustain, release 64 blocks
# sustain -> 0 from note-off.  Shape and constants are declared here and
# recorded in every artifact.
FENV_ATTACK_BLOCKS = 24
FENV_DECAY_BLOCKS = 48
FENV_SUSTAIN = 0.4
FENV_RELEASE_BLOCKS = 64


def fenv_declared(entry):
    """Declared filter-EG output for one block of the note plane."""
    n = entry["since"]
    if entry["gate"]:
        if n < FENV_ATTACK_BLOCKS:
            return f32(n / float(FENV_ATTACK_BLOCKS))
        n -= FENV_ATTACK_BLOCKS
        if n < FENV_DECAY_BLOCKS:
            return f32(1.0 + (FENV_SUSTAIN - 1.0) * (n / float(FENV_DECAY_BLOCKS)))
        return f32(FENV_SUSTAIN)
    if n >= FENV_RELEASE_BLOCKS:
        return f32(0.0)
    return f32(FENV_SUSTAIN * (1.0 - n / float(FENV_RELEASE_BLOCKS)))


# -------------------------------------------------------------- stimulus
def _bundle_input(case, n_samples, offset=0):
    """Filter-unit INPUT stream of a committed SXT-037 tap bundle.

    Real pinned-engine voice audio captured at the filter-stage boundary.
    Only the input column is read: the bundle's LP 12 dB output column is a
    different algorithm and is NEVER used as a reference for this leaf.
    """
    path = os.path.join(BUNDLE_ROOT, "bundle-" + case, "units.bin")
    if not os.path.exists(path):
        raise Refuse(f"stimulus bundle missing: {path}")
    size = struct.calcsize("<IIIff")
    vals = []
    first_key = None
    with open(path, "rb") as f:
        while len(vals) < n_samples + offset:
            buf = f.read(size)
            if len(buf) != size:
                break
            tag, lane, _seq, fin, _fout = struct.unpack("<IIIff", buf)
            if first_key is None:
                first_key = (tag, lane)
            if (tag, lane) != first_key:
                continue
            vals.append(fin)
    vals = vals[offset:offset + n_samples]
    if len(vals) < n_samples:
        raise Refuse(f"stimulus bundle {case}: {len(vals)} samples, {n_samples} needed")
    return vals


def _synth(kind, n_samples):
    """Deterministic synthetic drives (documented formulas, float32)."""
    out = []
    if kind == "chirp":
        # log sweep 100 Hz -> 20 kHz over the fixture at the 96 kHz OS rate
        phase = 0.0
        for i in range(n_samples):
            t = i / float(n_samples)
            fr = 100.0 * (200.0 ** t)
            phase += 2.0 * math.pi * fr / 96000.0
            out.append(f32(0.5 * math.sin(phase)))
    elif kind == "steps":
        # alternating +/- steps every 512 OS samples (transient/settling drive)
        for i in range(n_samples):
            out.append(f32(0.75 if (i // 512) % 2 == 0 else -0.75))
    elif kind == "hot":
        # deliberately over-unity drive into the softclip8 stage
        phase = 0.0
        for i in range(n_samples):
            phase += 2.0 * math.pi * 220.0 / 96000.0
            out.append(f32(9.0 * math.sin(phase)))
    else:
        raise Refuse(f"unknown synthetic stimulus {kind}")
    return out


def stimulus(spec_stim, n_samples):
    src = spec_stim["source"]
    gain = float(spec_stim.get("gain", 1.0))
    if src.startswith("bundle:"):
        vals = _bundle_input(src.split(":", 1)[1], n_samples,
                             int(spec_stim.get("offset", 0)))
    elif src.startswith("synth:"):
        vals = _synth(src.split(":", 1)[1], n_samples)
    else:
        raise Refuse(f"unknown stimulus source {src}")
    return [f32(v * gain) for v in vals]


# --------------------------------------------------------------- fixtures
# Every case: carrier control plane (or a declared corner override), the note
# plane driving keytrack + voice resets, the declared filter-EG trajectory,
# and a stimulus.  `override` fields are DECLARED corner values, recorded as
# such in the artifacts (never presented as carrier state).
CASES = {
    # --- carrier cases (real corpus parameters) --------------------------
    "king-b1": {
        "carrier": "king-b1", "sequence": "seq-notes-repeated-v1",
        "blocks": 256, "stimulus": {"source": "bundle:badnews", "gain": 32.0},
        "note": "King scene B filter 1: 24 dB, live keytrack (0.829) and "
                "env-mod (-8.74), resonance 0.378",
    },
    "king-b2": {
        "carrier": "king-b2", "sequence": "seq-notes-repeated-v1",
        "blocks": 256, "stimulus": {"source": "bundle:badnews", "gain": 32.0,
                                    "offset": 4096},
        "note": "King scene B filter 2: 24 dB, high resonance (0.828), no "
                "keytrack/env-mod - the second per-instance register set",
    },
    "chords": {
        "carrier": "chords", "sequence": "seq-notes-coverage-v1",
        "blocks": 320, "stimulus": {"source": "bundle:rainy", "gain": 1.0},
        "note": "House Of Chords scene A filter 2: 24 dB at the gg clamp "
                "(cutoff 70 st), resonance 0",
    },
    "disturb": {
        "carrier": "disturb", "sequence": "seq-notes-coverage-v1",
        "blocks": 320, "stimulus": {"source": "bundle:t9", "gain": 1.0},
        "note": "Disturbances scene A filter 1: 6 dB subtype, live keytrack "
                "(0.415, root 94) and env-mod (+18.75)",
    },
    # --- declared subtype coverage (the corpus carriers cover 0 and 3) ---
    "sub12db": {
        "carrier": "king-b1", "sequence": "seq-notes-repeated-v1",
        "blocks": 192, "stimulus": {"source": "synth:chirp"},
        "override": {"subtype": 1},
        "note": "declared corner: subtype 12 dB (tap R[1]) on the King-B1 "
                "control plane, chirp drive",
    },
    "sub18db": {
        "carrier": "king-b1", "sequence": "seq-notes-repeated-v1",
        "blocks": 192, "stimulus": {"source": "synth:chirp"},
        "override": {"subtype": 2},
        "note": "declared corner: subtype 18 dB (tap R[2])",
    },
    # --- declared parameter corners --------------------------------------
    "reso1": {
        "carrier": "king-b1", "sequence": "seq-notes-repeated-v1",
        "blocks": 192, "stimulus": {"source": "synth:steps"},
        "override": {"reso": 1.0},
        "note": "declared corner: resonance 1.0 (q = 2.15 ceiling) with step "
                "drive - the self-oscillation neighbourhood",
    },
    "cut-hi": {
        "carrier": "king-b1", "sequence": "seq-notes-repeated-v1",
        "blocks": 192, "stimulus": {"source": "synth:chirp"},
        "override": {"cut": 96.0},
        "note": "declared corner: cutoff above the pinned gg clamp (0.187)",
    },
    "cut-lo": {
        "carrier": "king-b1", "sequence": "seq-notes-repeated-v1",
        "blocks": 192, "stimulus": {"source": "synth:chirp"},
        "override": {"cut": -96.0},
        "note": "declared corner: cutoff far below the audible span "
                "(t_b1 -> 0, the 0.5/t_b1^4 resonance guard branch)",
    },
    "hot": {
        "carrier": "king-b2", "sequence": "seq-notes-repeated-v1",
        "blocks": 192, "stimulus": {"source": "synth:hot"},
        "note": "declared corner: over-unity drive exercising the pinned "
                "softclip8 first stage",
    },
    "toggle": {
        "carrier": "king-b1", "sequence": "seq-notes-repeated-v1",
        "blocks": 192, "stimulus": {"source": "synth:chirp"},
        "subtype_schedule": [[0, 3], [64, 0], [128, 2]],
        "note": "declared corner: subtype changes mid-render (engine "
                "memset(&FBP.FU[u]) + CM.Reset() path)",
    },
}


def build(case):
    """Build the full fixture spec (control plane + stimulus) for one case."""
    if case not in CASES:
        raise Refuse(f"unknown fixture case {case}")
    cfg = CASES[case]
    carrier = load_carrier(cfg["carrier"])
    over = cfg.get("override", {})
    n_blocks = int(cfg["blocks"])
    plane = note_plane(cfg["sequence"], n_blocks)
    cut = f32(over.get("cut", carrier["cut"]))
    reso = f32(over.get("reso", carrier["reso"]))
    subtype = int(over.get("subtype", carrier["subtype"]))
    schedule = cfg.get("subtype_schedule")
    blocks = []
    for b, entry in enumerate(plane):
        sub = subtype
        sub_change = False
        if schedule:
            for start, s in schedule:
                if b >= start:
                    sub = s
            prev = None
            for start, s in schedule:
                if b > start:
                    prev = s
                elif b == start:
                    sub_change = prev is not None and prev != s
        blocks.append({
            "cut": cut,
            "reso": reso,
            "keytrack": carrier["keytrack"],
            "keytrack_root": carrier["keytrack_root"],
            "envmod": carrier["envmod"],
            "pitch": entry["pitch"],
            "fenv": fenv_declared(entry),
            "subtype": sub,
            # a voice creation OR a type/subtype change resets the registers
            # and the coefficient maker (pinned SurgeVoice.cpp paths)
            "reset": bool(entry["reset"] or sub_change),
        })
    stim = stimulus(cfg["stimulus"], n_blocks * BLOCK_SIZE_OS)
    return {
        "schema_version": 1,
        "issue": "SXT-039",
        "case": case,
        "type": FUT_LPMOOG,
        "type_name": "LP Legacy Ladder",
        "samplerate_os": 96000,
        "block_size_os": BLOCK_SIZE_OS,
        "carrier": carrier,
        "override": over,
        "subtype_schedule": schedule,
        "sequence": cfg["sequence"],
        "stimulus": dict(cfg["stimulus"]),
        "fenv_source": "declared-trajectory",
        "fenv_params": {"attack_blocks": FENV_ATTACK_BLOCKS,
                        "decay_blocks": FENV_DECAY_BLOCKS,
                        "sustain": FENV_SUSTAIN,
                        "release_blocks": FENV_RELEASE_BLOCKS},
        "note": cfg["note"],
        "n_blocks": n_blocks,
        "blocks": blocks,
        "input": stim,
    }


def write_spec(case, out_dir):
    """Write spec JSON + raw float32 stimulus for the external reference tool."""
    spec = build(case)
    os.makedirs(out_dir, exist_ok=True)
    stim_path = os.path.join(out_dir, f"stim-{case}.f32")
    with open(stim_path, "wb") as f:
        f.write(struct.pack(f"<{len(spec['input'])}f", *spec["input"]))
    meta = {k: v for k, v in spec.items() if k != "input"}
    meta["input_file"] = os.path.basename(stim_path)
    meta["input_samples"] = len(spec["input"])
    spec_path = os.path.join(out_dir, f"spec-{case}.json")
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
        f.write("\n")
    return spec_path, stim_path


if __name__ == "__main__":
    import sys
    for name in (sys.argv[1:] or sorted(CASES)):
        s = build(name)
        print(f"{name}: blocks={s['n_blocks']} subtype(s)="
              f"{sorted({b['subtype'] for b in s['blocks']})} "
              f"cut={s['blocks'][0]['cut']} reso={s['blocks'][0]['reso']} "
              f"resets={sum(1 for b in s['blocks'] if b['reset'])} "
              f"peak_in={max(abs(v) for v in s['input']):.4f}")
