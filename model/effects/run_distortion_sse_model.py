#!/usr/bin/env python3
"""SXT-028e-sse (#136): run the frozen SSE-branch chain over a fixture dry bus.

Boundary (declared; the `model/effects/run_chorus_model.py` / SXT-023
`run_fx_model.py` pattern, unchanged): the model input is the pinned engine's
**all-off DRY bus** (stereo float32 WAV) de-amped by the converged master
amplitude `A = db_to_linear(volume)` and quantized to Q10.21. The model then
reproduces

    scene-A insert chain  ->  scene hardclip  ->  scene sum
    -> per send: send-gain ramp * sceneA -> effect -> return ramp * out
    -> per global slot (G1..G4 order): effect
    -> master amplitude -> master hardclip

and the chain output is compared against the pinned engine's wet bus by
`tools/compare_distortion_sse_reference.py`.

PER-INSTANCE STATE IS THE POINT, NOT AN OPTIMISATION
====================================================
The declared synthetic carriers put a Distortion in `ains1` AND in `send1`.
Each gets its own `DistortionSSEModel` with its own `DistortionSSEState` —
its own feedback registers, its own biquads, its own halfband delay lines and
its own `QuadWaveshaperState`. `--share-state` substitutes ONE shared
instance for both (the "shared instead of per-instance" negative control) and
must FAIL the comparison.

THE SETTLE IS NOT PART OF THE EFFECT'S HISTORY (measured, #136)
===============================================================
The fixture render runs a 0.25 s (375-block) settle before the first note.
That settle belongs to the **synth** — oscillators, envelopes, the master
amplitude lag — and it is already baked into the all-off dry bus this runner
reads. It does **not** belong to the effect: measured on the pinned engine,
the Distortion instance enters the first audio block with its control plane
still in the `init()` state (`drive`/`outgain` lipols at 0, both peak-EQ
coefficient sets and both high-cut coefficient sets at 0), i.e. the
`setvars`/lipol ramps have not started. Three measurements establish that
boundary, none of them a guess (`artifacts/settle-boundary.json`):

  1. the engine's wet bus is **byte-identical** for a 375-block and a
     3750-block settle — the effect state provably does not evolve during a
     silent settle;
  2. the engine's wet bus is **byte-identical** whether the synthetic
     carrier is constructed in place or saved and re-loaded from a `.fxp`
     into a fresh instance — so this is the engine's behaviour for an
     ordinary loaded preset, not an artifact of the construction;
  3. running the frozen model with **no** silent pre-roll agrees with the
     engine to 10.5 LSB Q10.21 / −119.7 dBFS on the harness anchor, while a
     375-block silent pre-roll leaves a 0.75-per-block decaying transient
     (672,130 LSB / −46.1 dBFS) — the signature of the lipol ramp being
     pre-converged on the model side and not on the engine's.

So `--silent-preroll-blocks` defaults to **0**. The non-zero setting is kept
because the wrong boundary must stay testable: NC-C below drives this runner
with the 375-block pre-roll and MUST FAIL the comparison.

RING-OUT, AND WHY THIS RUNNER REFUSES RATHER THAN GUESSES
=========================================================
`DistortionEffect::process` scales its output gain by
`ringoutMul(ringout)` once the host stops handing the slot input
(`Effect::process_ringout`'s counter). This runner does NOT reproduce the
host's `indata_present` bookkeeping. It therefore REFUSES unless the
fixture's all-off dry bus is non-silent in **every** block of the render, in
which case the counter provably never leaves 0 and `ringoutMul == 1`
throughout. The tail measured here is the effect's ARITHMETIC tail (feedback
registers, biquads, halfband lines); the ring-out FADE is covered exactly, by
integer equality, by the RTL leg's `ringout-tail-*` cases
(`reports/SXT-028e-sse/EVIDENCE.md` section 6) — not here, and the record
says so rather than implying the fade was exercised.

Original to this repository (Apache-2.0). Imports no engine source.
"""

import argparse
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))

import numpy as np  # noqa: E402

from model.effects.qmath import to_q, qmul, qadd, FRAC  # noqa: E402
from model.effects.delay.delay_model import (  # noqa: E402
    db_to_linear_d, A_FMT, G_FMT, BLOCK,
)
from distortion_sse_model import (  # noqa: E402
    DistortionSSEModel, DistortionSSEParams, table_branch_shaper,
    model_revision,
)
from render_fx_fixtures import write_wav_stereo_f32  # noqa: E402
from run_fx_model import read_wav_stereo_f32  # noqa: E402

# The fixture's own synth settle, in blocks. It is NOT run through the
# effect (see the module docstring); it is kept here only so the NC-C
# negative control can reproduce the wrong boundary exactly.
FIXTURE_SETTLE_BLOCKS = 375      # int(0.25 s x 48 kHz) / 32
HARDCLIP8 = 8 << FRAC[A_FMT]
LEAF = "SXT-028e-sse"


class ModelRefused(RuntimeError):
    pass


def amp_to_linear_fixed(f):
    """Send/return level: the engine's `amp_to_linear` cube (setvars)."""
    return to_q(max(0.0, f) ** 3, G_FMT)


class GenericTanhSubstitute:
    """NC-A: a 'convenient generic' distortion, in the chain's place.

    Single-rate `tanh(drive * x)` with the output gain applied: no
    oversampling, no halfband decimation, no pre/post peak EQ, no feedback
    recurrence, no quad-waveshaper state, no DC-offset probe. This is exactly
    the substitution this project refuses under a support claim, and it must
    FAIL the reference comparison.
    """

    def __init__(self, params, name="nc-a-generic"):
        self.p = params
        self.name = name
        self.drive = db_to_linear_d(params.drive_f)
        self.gain = db_to_linear_d(params.gain_f)
        self.initialized = True

    def initialize(self):
        pass

    def process_block(self, in_l, in_r, ringout=0):
        sc = float(1 << FRAC[A_FMT])
        out_l, out_r = [], []
        for a, b in zip(in_l, in_r):
            out_l.append(to_q(math.tanh(self.drive * (a / sc)) * self.gain,
                              A_FMT))
            out_r.append(to_q(math.tanh(self.drive * (b / sc)) * self.gain,
                              A_FMT))
        return out_l, out_r


def build_instance(entry, substitute=None):
    """One chain occupant. `substitute` selects a negative-control variant."""
    params = DistortionSSEParams(entry["params"])
    name = f"d{entry['slot']}"
    if substitute == "nc-a":
        return GenericTanhSubstitute(params, name)
    if substitute == "nc-a2":
        # NC-A2: the SIBLING leaf's own `lookup_waveshape` table shaper in
        # place of `GetQuadWaveshaper`, chain otherwise untouched. The model's
        # `chain_probe_shaper` verification hook is the documented way to do
        # exactly this substitution.
        return DistortionSSEModel(params, name,
                                  chain_probe_shaper=table_branch_shaper(0))
    return DistortionSSEModel(params, name)


def build_chain(chain, substitute=None, share_state=False):
    shared = None

    def make(entry):
        nonlocal shared
        if share_state:
            if shared is None:
                shared = build_instance(entry, substitute)
            return shared
        return build_instance(entry, substitute)

    ains = [(e["type"], make(e)) for e in sorted(chain.get("ains", []),
                                                 key=lambda x: x["slot"])]
    sends = [(e["type"], make(e), e["send_slot"], e["send_gain_f"],
              e["return_f"])
             for e in sorted(chain.get("sends", []), key=lambda x: x["slot"])]
    globals_ = [(e["type"], make(e)) for e in sorted(chain.get("globals", []),
                                                     key=lambda x: x["slot"])]
    for _k, m in ains:
        m.initialize()
    for _k, m, _i, _s, _r in sends:
        m.initialize()
    for _k, m in globals_:
        m.initialize()
    return ains, sends, globals_


def run_chain(ains, sends, globals_, in_l, in_r, a_q):
    """One block through the declared chain; returns the output block."""
    wl, wr = list(in_l), list(in_r)
    for _kind, m in ains:
        wl, wr = m.process_block(wl, wr)
    wl = [min(HARDCLIP8, max(-HARDCLIP8, x)) for x in wl]
    wr = [min(HARDCLIP8, max(-HARDCLIP8, x)) for x in wr]
    out_l, out_r = wl, wr
    for _kind, m, _idx, sg_f, rl_f in sends:
        sg = amp_to_linear_fixed(sg_f)
        rl = amp_to_linear_fixed(rl_f)
        sl = [qmul(sg, x, G_FMT, A_FMT, A_FMT) for x in wl]
        sr = [qmul(sg, x, G_FMT, A_FMT, A_FMT) for x in wr]
        fl, fr = m.process_block(sl, sr)
        out_l = [qadd(a, qmul(rl, b, G_FMT, A_FMT, A_FMT), A_FMT)
                 for a, b in zip(out_l, fl)]
        out_r = [qadd(a, qmul(rl, b, G_FMT, A_FMT, A_FMT), A_FMT)
                 for a, b in zip(out_r, fr)]
    for _kind, m in globals_:
        out_l, out_r = m.process_block(out_l, out_r)
    out_l = [min(HARDCLIP8, max(-HARDCLIP8,
                                qmul(a_q, x, G_FMT, A_FMT, A_FMT)))
             for x in out_l]
    out_r = [min(HARDCLIP8, max(-HARDCLIP8,
                                qmul(a_q, x, G_FMT, A_FMT, A_FMT)))
             for x in out_r]
    return out_l, out_r


def leg_chain(chain, leg):
    """The chain as the named fixture leg has it (per-slot bypass)."""
    if leg in (None, "original"):
        return chain
    if not leg.startswith("bypass-fx"):
        raise ModelRefused(f"unknown leg {leg!r}")
    off = int(leg[len("bypass-fx"):])
    out = {k: v for k, v in chain.items()}
    for key in ("ains", "sends", "globals"):
        out[key] = [e for e in chain.get(key, []) if e["slot"] != off]
    return out


def run(slug, seq, fixtures_dir, inputs_dir, out_dir, leg="original",
        substitute=None, share_state=False, drop_tail_blocks=0,
        out_name=None, silent_preroll_blocks=0):
    cfg_path = os.path.join(inputs_dir, f"type-distortion-sse-{slug}.json")
    if not os.path.exists(cfg_path):
        raise ModelRefused(f"no input record at {cfg_path}")
    cfg = json.load(open(cfg_path))
    chain = cfg.get("chain_models")
    if not chain:
        raise ModelRefused(
            f"{slug}: the record carries no runnable chain "
            f"(unlanded classes: {cfg.get('unlanded_classes_in_chain')}). A "
            "complete-wet comparison is NOT_RUN for this carrier; nothing is "
            "substituted for the missing class.")
    # The dry bus comes from the fixture SIDECAR's declared `legs.dry.wav`
    # (it is shared across the five shapers; see the renderer), and its
    # declared sha256 is re-verified here so the model is never run against a
    # bus the sidecar does not describe.
    sidecar_path = os.path.join(fixtures_dir, f"{slug}__{seq}.json")
    if not os.path.exists(sidecar_path):
        raise ModelRefused(f"no fixture sidecar at {sidecar_path}")
    sidecar = json.load(open(sidecar_path))
    dry_decl = sidecar.get("legs", {}).get("dry") or {}
    if not dry_decl.get("wav"):
        raise ModelRefused(f"{sidecar_path} declares no legs.dry.wav")
    dry_path = os.path.join(REPO, dry_decl["wav"])
    if not os.path.exists(dry_path):
        raise ModelRefused(f"no dry fixture bus at {dry_path}")
    import hashlib
    h = hashlib.sha256()
    with open(dry_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != dry_decl.get("sha256"):
        raise ModelRefused(
            f"dry bus {dry_path} hashes to {h.hexdigest()[:16]}… but the "
            f"sidecar declares {str(dry_decl.get('sha256'))[:16]}…: STALE")
    dry, sr = read_wav_stereo_f32(dry_path)
    if sr != 48000:
        raise ModelRefused(f"dry bus sample rate {sr} != 48000")
    frames = dry.shape[1]

    a_d = db_to_linear_d(chain["volume_f"])
    a_q = to_q(a_d, G_FMT)
    if a_d <= 0:
        raise ModelRefused("master amplitude is zero; the dry bus cannot be "
                           "de-amped")

    # ring-out guard (see the module docstring): the host's indata_present
    # bookkeeping is NOT reproduced here, so refuse unless it provably never
    # fires.
    usable = (frames // BLOCK) * BLOCK
    per_block_peak = np.abs(dry[:, :usable]).max(axis=0).reshape(-1, BLOCK) \
                       .max(axis=1)
    silent_blocks = int((per_block_peak == 0.0).sum())
    if silent_blocks:
        raise ModelRefused(
            f"{slug}__{seq}: the all-off dry bus has {silent_blocks} "
            "all-zero block(s), so Effect::ringout would leave 0 during the "
            "render and this runner does not reproduce the host's "
            "indata_present bookkeeping. Refusing rather than guessing the "
            "ring-out schedule (the RTL leg covers the fade by integer "
            "equality instead).")

    in_l_f = dry[0] / a_d
    in_r_f = dry[1] / a_d
    peak_in = float(max(np.max(np.abs(in_l_f)), np.max(np.abs(in_r_f))))
    if peak_in >= 7.9:
        raise ModelRefused(
            f"{slug}__{seq}: de-amped input peak {peak_in} is at the scene "
            "hardclip; the declared inactive-clip boundary is violated")

    pre = int(silent_preroll_blocks)
    if pre < 0:
        raise ModelRefused("silent_preroll_blocks must be >= 0")
    n_total = pre + (-(-frames // BLOCK))
    frames_padded = n_total * BLOCK
    zeros = [0] * (pre * BLOCK)
    in_l = zeros + [to_q(float(x), A_FMT) for x in in_l_f] \
        + [0] * (frames_padded - pre * BLOCK - frames)
    in_r = zeros + [to_q(float(x), A_FMT) for x in in_r_f] \
        + [0] * (frames_padded - pre * BLOCK - frames)

    ains, sends, globals_ = build_chain(leg_chain(chain, leg), substitute,
                                        share_state)
    n_instances = len(ains) + len(sends) + len(globals_)
    if n_instances == 0:
        raise ModelRefused(f"{slug}: leg {leg} leaves no effect in the chain")

    model_out = np.zeros((2, frames_padded), dtype=np.float32)
    scale = float(1 << FRAC[A_FMT])
    for b in range(n_total):
        il = in_l[b * BLOCK:(b + 1) * BLOCK]
        ir = in_r[b * BLOCK:(b + 1) * BLOCK]
        ol, orr = run_chain(ains, sends, globals_, il, ir, a_q)
        model_out[0, b * BLOCK:(b + 1) * BLOCK] = [v / scale for v in ol]
        model_out[1, b * BLOCK:(b + 1) * BLOCK] = [v / scale for v in orr]

    out = model_out[:, pre * BLOCK:pre * BLOCK + frames]
    if drop_tail_blocks:
        # NC-B: drop the last N blocks of the render (zeroed), to prove the
        # declared-region tail gate rejects a truncated tail.
        n = min(drop_tail_blocks * BLOCK, out.shape[1])
        out = out.copy()
        out[:, out.shape[1] - n:] = 0.0

    os.makedirs(out_dir, exist_ok=True)
    name = out_name or f"model__{slug}__{seq}.f32.wav"
    wav_path = os.path.join(out_dir, name)
    write_wav_stereo_f32(wav_path, out)
    print(f"ran {slug}__{seq} leg={leg} substitute={substitute} "
          f"share_state={share_state} drop_tail={drop_tail_blocks} "
          f"preroll={pre} instances={n_instances} -> "
          f"{os.path.relpath(wav_path, REPO)} "
          f"peak={float(np.max(np.abs(out))):.5f}")
    return {
        "leaf": LEAF,
        "slug": slug,
        "sequence": seq,
        "leg": leg,
        "substitute": substitute,
        "share_state": share_state,
        "drop_tail_blocks": drop_tail_blocks,
        "instances": n_instances,
        "silent_preroll_blocks": pre,
        "fixture_settle_blocks": FIXTURE_SETTLE_BLOCKS,
        "settle_boundary": (
            "the fixture's 0.25 s synth settle is already baked into the "
            "dry bus and is NOT run through the effect: measured, the "
            "engine's Distortion enters the first audio block in its init() "
            "state (artifacts/settle-boundary.json). A non-zero "
            "silent_preroll_blocks is the NC-C negative control and must "
            "FAIL."),
        "frames": int(out.shape[1]),
        "a_fixed": a_q,
        "input_peak_post_deamp": peak_in,
        "dry_all_zero_blocks": silent_blocks,
        "ringout_counter_provably_zero": True,
        "model_revision": model_revision(),
        "wav": os.path.relpath(wav_path, REPO),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", default="seq-notes-coverage-v1")
    ap.add_argument("--fixtures-dir",
                    default=os.path.join(REPO, "reports", "SXT-028e-sse",
                                         "fixtures"))
    ap.add_argument("--inputs-dir",
                    default=os.path.join(REPO, "reports", "SXT-028e-sse",
                                         "artifacts", "synthetic"))
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "SXT-028e-sse",
                                         "artifacts"))
    ap.add_argument("--leg", default="original")
    ap.add_argument("--substitute", choices=("nc-a", "nc-a2"), default=None)
    ap.add_argument("--share-state", action="store_true")
    ap.add_argument("--drop-tail-blocks", type=int, default=0)
    ap.add_argument("--silent-preroll-blocks", type=int, default=0,
                    help="blocks of silence run through the effect before "
                         "the fixture audio. DECLARED 0 (see the module "
                         "docstring); the only sanctioned non-zero use is "
                         "the NC-C negative control, which must FAIL.")
    ap.add_argument("--out-name")
    ap.add_argument("--json")
    args = ap.parse_args()
    rec = run(args.slug, args.seq, args.fixtures_dir, args.inputs_dir,
              args.out_dir, args.leg, args.substitute, args.share_state,
              args.drop_tail_blocks, args.out_name,
              args.silent_preroll_blocks)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(rec, f, indent=2)
            f.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ModelRefused as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
