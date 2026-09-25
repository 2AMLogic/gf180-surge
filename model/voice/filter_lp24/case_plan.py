#!/usr/bin/env python3
"""SXT-038 case plan: the ONE control plane + stimulus both legs consume.

A "case" is a committed JSON file (reports/SXT-038/artifacts/cases/*.json)
written by `extract_inputs.py` from the committed normalized graph corpus.
This module turns a case into

  * `build_plan(case)`  — the per-block control plane
                          [{seg, note, sub, reset, cut, res}, ...]
  * `load_stimulus(case)` — the per-OS-sample input signal as Q10.21 ints

Both the pinned-code reference renderer (`tools/render_lp24_reference.py`)
and the frozen model runner (`run_filter_leg.py`) import this module, so the
two legs are driven by BIT-IDENTICAL inputs by construction: control words
are rounded to float32 here (the engine's parameter word), and every input
sample is an integer whose float32 image is exact.

Declared control-plane boundary (same class as the landed SXT-037 leaf):
the SurgeVoice control arithmetic
    cutoff_a = cutoff + keytrack * (note - keytrack_root) + envmod * FEG
lives OUTSIDE this leaf; this module evaluates it to produce the leaf's
block-rate inputs.  The FEG trajectory is a DECLARED FIXTURE TRAJECTORY
(constants below), NOT the carrier preset's own filter envelope: the
preset's ADSR state is not in the SXT-011 normalized graph schema and is
reachable only through the pinned engine, which is not available in this
environment (see reports/SXT-038/EVIDENCE.md, finding F-038-1).  It is fed
identically to both legs, so it never flatters either one.

Block rate: one engine block is BLOCK_SIZE = 32 samples at 48 kHz = 64 OS
samples at 96 kHz, i.e. 1500 blocks/second.
"""

import json
import math
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402

BLOCK_OS = 64                 # BLOCK_SIZE_OS
BLOCK_RATE = 48000.0 / 32.0   # 1500 engine blocks per second
FQ = vm.FQ

# Declared FEG fixture trajectory defaults (overridable per case).
FEG_DEFAULT = {
    "attack_s": 0.020,
    "decay_s": 0.100,
    "sustain": 0.5,
    "release_s": 0.150,
    "note_off_frac": 0.7,
}


class Refuse(Exception):
    """Fail-closed: a case that cannot be honoured exactly is refused."""


def f32(x):
    """Round a Python float to float32 (the engine's parameter word)."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def load_case(path):
    with open(path, encoding="utf-8") as f:
        case = json.load(f)
    if case.get("schema") != "sxt-038-case/1":
        raise Refuse(f"{path}: unknown case schema {case.get('schema')!r}")
    return case


def _sequence_notes(seq_id):
    path = os.path.join(REPO, "fixtures", "sequences", f"{seq_id}.json")
    if not os.path.exists(path):
        raise Refuse(f"sequence fixture {seq_id} not found at {path}")
    with open(path, encoding="utf-8") as f:
        seq = json.load(f)
    notes = [int(e["note"]) for e in seq["events"] if e["type"] == "note_on"]
    if not notes:
        raise Refuse(f"sequence {seq_id} has no note_on events")
    return notes


def feg_value(t, seg_s, p):
    """Declared FEG fixture trajectory in [0, 1] at time t within a segment."""
    a, d, s, r = p["attack_s"], p["decay_s"], p["sustain"], p["release_s"]
    t_off = p["note_off_frac"] * seg_s
    if t < a:
        return t / a if a > 0 else 1.0
    if t < a + d:
        return 1.0 + (s - 1.0) * ((t - a) / d) if d > 0 else s
    if t < t_off:
        return s
    if r <= 0:
        return 0.0
    return max(0.0, s * (1.0 - (t - t_off) / r))


def build_plan(case):
    """Per-block control plane; identical for the model and reference legs."""
    filt = case["filter"]
    ov = case.get("overrides", {})
    cut0 = float(ov.get("cut", filt["cut"]))
    res0 = float(ov.get("res", filt["res"]))
    sub0 = int(ov.get("subtype", filt["subtype"]))
    sub1 = int(ov.get("toggle_subtype", sub0))
    toggle_seg = ov.get("toggle_from_segment")
    kt = float(filt["kt"])
    em = float(filt["em"])
    kt_root = float(filt["ktR"])
    if int(filt["type"]) != 2:
        raise Refuse(f"case {case['case']}: filter type {filt['type']} is not fut_lp24 (2)")
    if not (0.0 <= res0 <= 1.0):
        raise Refuse(f"case {case['case']}: resonance {res0} outside [0, 1]")

    blocks = int(case["stimulus"]["blocks"])
    notes = _sequence_notes(case["sequence"])
    nseg = min(len(notes), blocks)
    seg_len = blocks // nseg
    if seg_len < 4:
        raise Refuse(f"case {case['case']}: fewer than 4 blocks per note segment")
    p = dict(FEG_DEFAULT)
    p.update(case.get("feg", {}))

    plan = []
    for seg in range(nseg):
        note = notes[seg]
        length = seg_len if seg < nseg - 1 else blocks - seg_len * (nseg - 1)
        seg_s = length / BLOCK_RATE
        sub = sub1 if (toggle_seg is not None and seg >= int(toggle_seg)) else sub0
        for i in range(length):
            feg = feg_value(i / BLOCK_RATE, seg_s, p)
            cut = f32(cut0 + kt * (note - kt_root) + em * feg)
            plan.append({
                "seg": seg,
                "note": note,
                "sub": sub,
                # A fresh voice (engine: FBP zero + CM.Reset()).  A subtype
                # change also forces this path at the pin, so the toggle case
                # lands on a segment boundary by construction.
                "reset": i == 0,
                "cut": cut,
                "res": f32(res0),
            })
    if len(plan) != blocks:
        raise Refuse("internal: plan length does not match the stimulus block count")
    return plan


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_stimulus(case):
    """Input signal as Q10.21 ints; every word's float32 image is exact."""
    spec = case["stimulus"]
    blocks = int(spec["blocks"])
    want = blocks * BLOCK_OS
    src = spec["source"]
    if src == "sxt037-tap":
        path = os.path.join(REPO, spec["bundle"], "units.bin")
        if not os.path.exists(path):
            raise Refuse(f"stimulus bundle missing: {path}")
        got = _sha256(path)
        if got != spec["sha256"]:
            raise Refuse(f"stimulus {path}: sha256 {got} != declared {spec['sha256']}")
        size = struct.calcsize("<IIIff")
        raw = open(path, "rb").read()
        n = len(raw) // size
        vals = []
        for i in range(n):
            tag, lane, _seq, fin, _fout = struct.unpack_from("<IIIff", raw, i * size)
            if tag != int(spec.get("tag", 0)) or lane != int(spec.get("lane", 0)):
                continue
            vals.append(fin)
            if len(vals) == want:
                break
        if len(vals) < want:
            raise Refuse(f"stimulus {path}: {len(vals)} samples, {want} required")
    elif src == "synthetic-v1":
        vals = _synthetic(want, spec)
    else:
        raise Refuse(f"unknown stimulus source {src!r}")

    out = []
    for v in vals:
        q = vm.sat(int(math.floor(v * (1 << FQ) + 0.5)))
        if abs(q) >= (1 << 24):
            raise Refuse("stimulus word not exactly representable in float32 "
                         f"(|q| = {abs(q)} >= 2^24)")
        out.append(q)
    return out


def _synthetic(n, spec):
    """Declared deterministic stimulus (no engine input): log chirp + ticks.

    Amplitude and shape are frozen constants; the signal exists to excite the
    whole band including the resonance corner, and is quantization-exact by
    construction (all words are multiples of 2^-14).
    """
    amp = float(spec.get("amp", 0.125))
    f0, f1 = 20.0, 18000.0
    out = []
    for i in range(n):
        t = i / 96000.0
        frac = i / max(1, n - 1)
        f = f0 * (f1 / f0) ** frac
        v = amp * math.sin(2 * math.pi * f * t)
        if i % 24000 == 0:
            v = amp
        out.append(math.floor(v * (1 << 14)) / (1 << 14))
    return out
