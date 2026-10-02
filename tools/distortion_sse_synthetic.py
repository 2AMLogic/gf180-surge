#!/usr/bin/env python3
"""SXT-028e-sse: the DECLARED SYNTHETIC reference carriers (issue #136).

READ THIS FIRST — WHAT THESE ARE NOT
====================================
These carriers are **constructed in the pinned engine**, not loaded from the
corpus. They are a *declared synthetic* instrument for the
model-vs-pinned-engine leg and they carry **no corpus reach and no
preset-support claim whatsoever**. A number measured on a synthetic carrier
says "the frozen model reproduces the pinned engine for this shaper at this
declared operating point"; it says nothing about how many presets use the
shaper, and nothing about whether any preset sounds right.

WHY THEY EXIST
==============
#121 selected one corpus carrier per reachable FX model from
`corpus/normalized/graphs.jsonl` for *inventory*. Under the SXT-012/023
render policies that this leaf's reference leg must obey, every one of those
carriers is **refused**, measured on the oracle host (see
`reports/SXT-028e-sse/artifacts/render-refusals.txt`):

  * `Damon Armani/Drums/Reverse Crash.fxp` (model 3) — FAILS the 3x
    bit-identical render determinism gate.
  * `Damon Armani/Plucks/Trance Pluck.fxp` (model 4) — `drift = 1.0` (not
    0), a non-muted oscillator with retrigger off, modulation routed into FX
    parameters (`FX S1 Drive`, `FX A1 Mix`), and an unlanded `Conditioner`
    in the active chain.
  * `Kinsey Dulcet/Guitars/Mutant Lo-Fi Acoustic Guitar Workstation.fxp`
    (model 5) — modulation routed into `FX S1 Drive`, a non-muted oscillator
    with retrigger off, and FAILS the 3x determinism gate.
  * FX models 6 and 7 — no usable corpus carrier at all (F-028e-sse-5).

So the corpus-carrier reference leg is **NOT_RUN** and says so. The issue
(#136) explicitly sanctions a declared synthetic pinned-engine patch for the
models with no carrier; this module applies the same, clearly-labelled
instrument to all five shapers so the five legs are comparable.

CONSTRUCTION (declared, deterministic, read back and refused on mismatch)
========================================================================
Base patch: `patches_factory/Basses/FM Combo.fxp` — census blob
`b50a3649…`, the SXT-028c Chorus carrier whose committed wet bus this host
re-renders byte-identically (that equality is the harness/host control for
this whole leg). Its scene A has `drift = 0`, every non-muted oscillator
retriggers, there is no modulation route into any FX parameter, and its own
dry bus is non-silent in **every** block of the render.

Mutations applied to a fresh instance, before the settle:

  1. all 16 FX slot types -> Off, then slot 0 (`ains1`) and slot 4 (`send1`)
     -> `fxt_distortion`;
  2. ONE 32-sample block is processed so the engine's deferred FX rebuild
     applies the type change (`setParamVal` on an FX type is picked up by
     the audio thread, not synchronously), and the types are **read back**;
  3. the twelve Distortion parameters of each slot are set from the declared
     parameter sets below — a DIFFERENT set per slot, so the two instances
     carry genuinely different histories and a shared-state substitute has
     something to fail against — with `model` = the shaper under test and
     the three `extend_range` flags explicitly cleared;
  4. scene A send-1 level -> `SEND1_LEVEL`;
  5. the remaining `settle_blocks - 1` settle blocks are processed, so the
     total settle is exactly the SXT-012 0.25 s, and every parameter is read
     back and refused on mismatch.

Declared deviation from the SXT-012 settle policy: one of the 375 settle
blocks is processed before the Distortion parameters are written (it is the
block that materialises the effect instances). Nothing else differs.

The operating point (drive, feedback, gains) was fixed ONCE, before any
comparison was computed, by one stated criterion: keep the engine's +-8
master hard-clip inactive on every leg for every shaper, so the measurement
reads the shaper and not a clipper. It was not adjusted afterwards and no
metric was used to choose it.

Original to this repository (Apache-2.0); drives the GPL engine at runtime
through its own `surgepy` binding only.
"""

import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))

from sse_tables import SSE_MODELS, SSE_SHAPER_OF, FXWS_NAMES  # noqa: E402

SYN_BASE = "resources/data/patches_factory/Basses/FM Combo.fxp"
SYN_BASE_CENSUS_SHA1 = "b50a36498d699f8ec409b7a5623ff516954cd242"

FX_SLOTS = 16
AINS1_SLOT = 0          # scene A insert 1
SEND1_SLOT = 4          # send 1
SYN_SLOTS = (AINS1_SLOT, SEND1_SLOT)
SEND1_LEVEL = 0.5       # scene A send-1 level (engine units; cubed by setvars)

# Distortion parameter order (DistortionEffect.h dist_params); index 11 is
# the model and is supplied per carrier.
PARAM_ORDER = ["preeq_gain_f", "preeq_freq_f", "preeq_bw_f",
               "preeq_highcut_f", "drive_f", "feedback_f",
               "posteq_gain_f", "posteq_freq_f", "posteq_bw_f",
               "posteq_highcut_f", "gain_f"]
EXTEND_PARAM_INDICES = (0, 4, 6)   # preeq_gain, drive, posteq_gain

# Two declared parameter sets. The pre/post peak-EQ frequency/bandwidth and
# high-cut values are the ones the model-3 corpus carrier happens to carry
# (so the EQ sections sit at a realistic, non-degenerate operating point);
# the gains, drive and feedback are this module's own declared choice.
_EQ_SHAPE = {
    "preeq_freq_f": 3.81785988807678,
    "preeq_bw_f": 1.9446439743042,
    "preeq_highcut_f": 38.42144775390625,
    "posteq_freq_f": 3.0,
    "posteq_bw_f": 2.03125,
    "posteq_highcut_f": 30.53573608398438,
}
INSTANCE_A = dict(_EQ_SHAPE, preeq_gain_f=0.0, drive_f=12.0,
                  feedback_f=0.0, posteq_gain_f=0.0, gain_f=-6.0)
INSTANCE_B = dict(_EQ_SHAPE, preeq_gain_f=-3.0, drive_f=6.0,
                  feedback_f=-0.5, posteq_gain_f=-6.0, gain_f=-6.0)
ROLE_OF_SLOT = {AINS1_SLOT: "ains1", SEND1_SLOT: "send1"}

# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
# A carrier is {slug: {"model": m, "slots": {slot: param-dict}}}.
#
#  syn-m3 .. syn-m7      the PRIMARY carriers: one per shaper, TWO instances
#                        (ains1 open-loop at drive 12 dB, send1 inside its own
#                        feedback loop at drive 6 dB). The two-instance shape
#                        is what makes the per-slot bypass legs and the
#                        shared-vs-per-instance state control meaningful.
#
#  syn-d{0,6,12,18}-m3   the DECLARED DRIVE-SENSITIVITY family: one instance
#                        (ains1), model 3, identical in everything but drive.
#                        `syn-d0-m3` doubles as the HARNESS ANCHOR: at drive
#                        0 dB the shaper is nearly transparent, so whatever
#                        residual it shows is the chain wiring, the dry-bus
#                        de-amp boundary, the hard-clips and the halfband
#                        path — NOT the shaper. A large residual there would
#                        mean the harness is wrong and nothing else in this
#                        leg could be believed.
PRIMARY_CARRIERS = {
    f"syn-m{m}": {"model": m, "slots": {AINS1_SLOT: dict(INSTANCE_A),
                                        SEND1_SLOT: dict(INSTANCE_B)}}
    for m in sorted(SSE_MODELS)
}
DRIVE_SWEEP_DB = (0.0, 6.0, 12.0, 18.0)
DRIVE_SWEEP_MODEL = 3
DRIVE_CARRIERS = {
    f"syn-d{int(d)}-m{DRIVE_SWEEP_MODEL}": {
        "model": DRIVE_SWEEP_MODEL,
        "slots": {AINS1_SLOT: dict(INSTANCE_A, drive_f=d, gain_f=0.0)},
    }
    for d in DRIVE_SWEEP_DB
}
ANCHOR_SLUG = f"syn-d0-m{DRIVE_SWEEP_MODEL}"
CARRIERS = dict(PRIMARY_CARRIERS, **DRIVE_CARRIERS)

# Which sequences each carrier is rendered against. The primary carriers get
# both library sequences (a mono-ish note sweep and an 8-note polyphonic
# chord), so a verdict that depended on the stimulus would show up as a
# disagreement between them. The drive-sensitivity family is a probe of one
# shaper against drive, not a second fidelity claim, so it gets the shorter
# sequence only -- stated here rather than left to whoever runs the tool.
SEQUENCES_FOR = dict(
    {slug: ("seq-notes-coverage-v1", "seq-poly-8-v1")
     for slug in PRIMARY_CARRIERS},
    **{slug: ("seq-poly-8-v1",) for slug in DRIVE_CARRIERS})


def carrier_slots(slug):
    return tuple(sorted(CARRIERS[slug]["slots"]))


def carrier_legs(slug):
    """The fixture legs of a bundle.

    `original` is the unmodified synthetic wet reference; each `bypass-fxN`
    switches exactly ONE Distortion slot to Off and leaves the original wet
    reference untouched (it is an ADDITIONAL reference bus, never a
    replacement); `dry` is all 16 slots Off. A one-instance carrier has no
    distinct bypass leg — its bypass IS the dry bus — so none is written for
    it rather than committing a duplicate under a second name.
    """
    slots = carrier_slots(slug)
    legs = ["original"]
    if len(slots) > 1:
        legs += [f"bypass-fx{s}" for s in slots]
    legs.append("dry")
    return tuple(legs)


def leg_active_slots(slug, leg):
    """Which Distortion slots are active for a fixture leg."""
    slots = carrier_slots(slug)
    if leg == "original":
        return slots
    if leg == "dry":
        return ()
    if leg.startswith("bypass-fx"):
        off = int(leg[len("bypass-fx"):])
        if off not in slots:
            raise ValueError(f"{slug}/{leg}: slot {off} is not a carrier slot")
        return tuple(s for s in slots if s != off)
    raise ValueError(f"unknown fixture leg {leg!r}")


def _f32_bits(x):
    """The IEEE-754 binary32 bit pattern of a double (the engine's precision)."""
    return struct.unpack("<I", struct.pack("<f", float(x)))[0]


def _f32_ulps(a, b):
    """Distance in binary32 ULPs between two values of the same sign."""
    ia, ib = _f32_bits(a), _f32_bits(b)
    if (ia >> 31) != (ib >> 31):
        return None          # different signs: not comparable in ULPs
    return abs(ia - ib)


# `setParamVal` writes through the parameter's normalized 0..1 representation
# and converts back, so a read-back can sit a small number of binary32 ULPs
# away from the double that was written. The READ-BACK is what the engine
# holds and what the frozen model is handed, so it is the value recorded; this
# bound only asserts that the write landed on the value asked for rather than
# on some other value. Measured distance for the declared parameter sets: 1
# ULP worst case, recorded per carrier as `max_setparam_ulps`.
SETPARAM_ULP_BOUND = 4


class SyntheticRefused(RuntimeError):
    """A synthetic construction whose read-back did not match what was set."""


def construct(s, slug, active_slots, settle_blocks):
    """Apply the declared synthetic construction to a freshly-loaded patch.

    `s` must already have the base patch loaded and the controllers reset.
    Processes exactly `settle_blocks` blocks in total (1 FX-rebuild block +
    `settle_blocks - 1` settle blocks) and read-back-verifies everything it
    sets. Returns the read-back record.
    """
    import surgepy.constants as C

    if slug not in CARRIERS:
        raise SyntheticRefused(f"unknown synthetic carrier {slug!r}")
    model_i = CARRIERS[slug]["model"]
    params_of = CARRIERS[slug]["slots"]
    if model_i not in SSE_MODELS:
        raise SyntheticRefused(f"FX model {model_i} is not in this leaf's branch")
    if settle_blocks < 2:
        raise SyntheticRefused("settle_blocks must leave room for the rebuild block")

    want_types = [C.fxt_distortion if i in active_slots else C.fxt_off
                  for i in range(FX_SLOTS)]
    for i in range(FX_SLOTS):
        s.setParamVal(s.getPatch()["fx"][i]["type"], want_types[i])
    s.processMultiBlock(s.createMultiBlock(1))
    got_types = [int(s.getParamVal(s.getPatch()["fx"][i]["type"]))
                 for i in range(FX_SLOTS)]
    if got_types != want_types:
        raise SyntheticRefused(
            f"FX types did not read back: want {want_types}, got {got_types}")

    for slot in active_slots:
        fx = s.getPatch()["fx"][slot]
        pset = params_of[slot]
        for j, key in enumerate(PARAM_ORDER):
            s.setParamVal(fx["p"][j], pset[key])
        s.setParamVal(fx["p"][11], float(model_i))
        for j in EXTEND_PARAM_INDICES:
            s.setExtend(fx["p"][j], False)
    s.setParamVal(s.getPatch()["scene"][0]["send_level"][0], SEND1_LEVEL)

    s.processMultiBlock(s.createMultiBlock(settle_blocks - 1))

    readback = {"fx_types": got_types, "slots": {}, "max_setparam_ulps": 0}
    for slot in active_slots:
        fx = s.getPatch()["fx"][slot]
        pset = params_of[slot]
        vals = {}
        for j, key in enumerate(PARAM_ORDER):
            got = float(s.getParamVal(fx["p"][j]))
            # The engine stores FX parameters as float32, so the read-back is
            # the double nearest the float32 nearest what was written. The
            # RECORDED value is the read-back (what the engine actually holds,
            # and what the frozen model is then handed); the assertion is
            # agreement at float32 precision, which is the only precision the
            # engine has. A wider disagreement means the write did not land.
            ulps = _f32_ulps(got, float(pset[key]))
            if ulps is None or ulps > SETPARAM_ULP_BOUND:
                raise SyntheticRefused(
                    f"slot {slot} {key}: set {pset[key]}, read back {got} "
                    f"({ulps} binary32 ULPs away, bound "
                    f"{SETPARAM_ULP_BOUND})")
            readback["max_setparam_ulps"] = max(
                readback["max_setparam_ulps"], ulps)
            vals[key] = got
        got_model = int(s.getParamVal(fx["p"][11]))
        if got_model != model_i:
            raise SyntheticRefused(
                f"slot {slot} model: set {model_i}, read back {got_model}")
        vals["model_i"] = got_model
        for j in EXTEND_PARAM_INDICES:
            if bool(s.getExtend(fx["p"][j])):
                raise SyntheticRefused(
                    f"slot {slot} p{j}: extend_range did not clear")
        readback["slots"][str(slot)] = {
            "role": ROLE_OF_SLOT[slot],
            "quad_waveshaper": SSE_SHAPER_OF[model_i],
            "fxws_name": FXWS_NAMES[model_i],
            "params": vals,
            "return_f": float(s.getParamVal(fx["return_level"])),
        }
    got_send = float(s.getParamVal(s.getPatch()["scene"][0]["send_level"][0]))
    if got_send != SEND1_LEVEL:
        raise SyntheticRefused(
            f"scene A send1 level: set {SEND1_LEVEL}, read back {got_send}")
    readback["send1_level_f"] = got_send
    readback["volume_f"] = float(s.getParamVal(s.getPatch()["volume"]))
    return readback


DECLARATION = (
    "DECLARED SYNTHETIC carrier: constructed in the pinned engine from "
    f"{SYN_BASE} by setting all 16 FX slot types Off except slots "
    f"{AINS1_SLOT} (ains1) and {SEND1_SLOT} (send1) = Distortion, writing a "
    "declared parameter set into each and clearing the three extend_range "
    "flags. NOT a corpus preset. Carries NO corpus reach, NO preset-support "
    "claim and NO musical-quality claim; it is an instrument for the "
    "model-vs-pinned-engine numeric leg only."
)
