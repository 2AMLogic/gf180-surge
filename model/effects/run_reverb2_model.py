#!/usr/bin/env python3
"""SXT-028f: run the frozen Reverb 2 model over a fixture's reference buses.

DECLARED INPUT BOUNDARY (fail-closed, issue #126 / finding F-028f-1)
--------------------------------------------------------------------
This leaf measures the **Reverb 2 class**, not a stack of sibling models.
The model input is therefore taken from the pinned engine itself, via the
per-slot bypass leg of the same fixture bundle
(`tools/render_reverb2_fixtures.py`):

    wet    = clip8( A * Reverb2(X) )        the ORIGINAL unmodified chain
    bypass = clip8( A * X )                 the same chain with ONLY the
                                            Reverb 2 slot set to Off

where `A = db_to_linear(volume)` is the converged master amplitude and `X`
is exactly the signal the engine feeds the Reverb 2 instance. That identity
holds **only** when the Reverb 2 slot is the LAST active FX slot and sits in
a global role, so nothing downstream of it can differ between the two legs.
Any other topology is REFUSED here rather than approximated: a send-slot
Reverb 2 with a downstream global effect (e.g. the issue-named `novuo`
carrier, whose chain ends in an unlanded Distortion) cannot be isolated this
way, and this tool will not pretend otherwise.

So the model render is

    model = A * Reverb2Model( quantize_Q10.21( bypass / A ) )

run through the same 375-block (0.25 s) silent settle the fixture harness
uses, so the control ramps, LFO and tank state evolve exactly as they do on
the engine side before the first scheduled event.

Declared boundary error (absorbed by the [PROPOSED] budgets, never hidden):
the bypass bus is stored as float32 and divided by `A` in double before the
single Q10.21 quantization, i.e. <= 1/2 LSB at 2^-21 (~ -132 dBFS class) on
top of the model's own declared deviations (reverb2_model.py / README).

The frozen model file itself is byte-pinned (docs/byte-frozen-sources.json);
this runner imports it and does not modify it.

Outputs (under --out-dir):
  model__<slug>__<seq>.f32.wav   model wet bus (stereo float32)
  model__<slug>__<seq>.json      run manifest (boundary, revision, peaks)

Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-reverb 2"))

import numpy as np  # noqa: E402

from model.effects.qmath import FRAC, to_q  # noqa: E402
from model.effects.delay.delay_model import db_to_linear_d, A_FMT, BLOCK  # noqa: E402
from reverb2_model import (  # noqa: E402
    ENGINE_PROFILE, Reverb2Model, Reverb2Params, model_revision,
)
from render_fx_fixtures import write_wav_stereo_f32  # noqa: E402
from run_fx_model import read_wav_stereo_f32  # noqa: E402

SETTLE_BLOCKS = 375          # int(0.25 s * 48 kHz) / 32, the fixture settle
HARDCLIP8 = 8 << FRAC[A_FMT]
A_SCALE = float(1 << FRAC[A_FMT])


class Refuse(Exception):
    pass


def declared_boundary(cfg):
    """Fail-closed check that the bypass identity above actually holds."""
    inst = cfg["instances"]
    if len(inst) != 1:
        raise Refuse(
            "the declared bypass input boundary is defined for exactly one "
            "Reverb 2 instance; this carrier has %d" % len(inst))
    e = inst[0]
    if not str(e["role"]).startswith("global"):
        raise Refuse(
            "Reverb 2 is in role %r, not a global slot: the per-slot bypass "
            "bus is then not the instance's input (fail-closed)" % e["role"])
    active = [c["slot"] for c in cfg["chain"]]
    if max(active) != e["slot"]:
        raise Refuse(
            "Reverb 2 is in slot %d but slot %d is also active downstream: "
            "the wet and bypass legs differ by more than the Reverb 2 "
            "(fail-closed)" % (e["slot"], max(active)))
    p = e["params"]
    if p.get("ts_predelay") is None:
        raise Refuse(
            "rev2_predelay temposync flag is UNRESOLVED (null): the frozen "
            "model refuses to assume one (fail-closed)")
    if cfg.get("volume_f") is None:
        raise Refuse("no master volume readback in the input record")
    if cfg.get("drift_asserted") != 0:
        raise Refuse(
            "drift_asserted is %r, not 0: the SXT-012 3x bit-identical "
            "determinism gate did not pass for this carrier"
            % cfg.get("drift_asserted"))
    return e


def prepare(slug, seq, cfg, fixtures_dir):
    """Build the declared model input from the committed fixture bundle.

    Shared by the model render and by the reference-bundle negative
    controls (tools/reverb2_reference_controls.py), so a control is driven
    by exactly the same input as the thing it controls.
    """
    inst = declared_boundary(cfg)
    slot = inst["slot"]
    side_path = os.path.join(fixtures_dir, f"{slug}__{seq}.json")
    with open(side_path) as f:
        side = json.load(f)
    bp = side["bypass"].get(f"fx{slot}")
    if bp is None:
        raise Refuse(f"fixture bundle has no bypass leg for slot {slot}")
    bypass, sr = read_wav_stereo_f32(os.path.join(REPO, bp["wav"]))
    wet_frames = int(side["wet"]["frames"])
    if sr != 48000 or bypass.shape[1] != wet_frames:
        raise Refuse("bypass leg does not match the declared wet render "
                     "(sr=%r frames=%r vs %r)" % (sr, bypass.shape[1],
                                                  wet_frames))

    a_d = db_to_linear_d(float(cfg["volume_f"]))
    in_l_f = bypass[0] / a_d
    in_r_f = bypass[1] / a_d
    peak_in = float(max(np.max(np.abs(in_l_f)), np.max(np.abs(in_r_f))))
    if peak_in >= 7.9:
        raise Refuse("input peak %r too close to the master hardclip; the "
                     "declared inactive-clip boundary is violated" % peak_in)

    frames = bypass.shape[1]
    n_blocks = SETTLE_BLOCKS + (-(-frames // BLOCK))
    padded = n_blocks * BLOCK
    zeros = [0] * (SETTLE_BLOCKS * BLOCK)
    tail_pad = padded - SETTLE_BLOCKS * BLOCK - frames
    in_l = zeros + [to_q(float(x), A_FMT) for x in in_l_f] + [0] * tail_pad
    in_r = zeros + [to_q(float(x), A_FMT) for x in in_r_f] + [0] * tail_pad
    return {
        "inst": inst, "slot": slot, "side": side, "bypass_entry": bp,
        "bypass": bypass, "a_d": a_d, "a_q": to_q(a_d, "Q13.18"),
        "in_l": in_l, "in_r": in_r, "frames": frames, "n_blocks": n_blocks,
        "input_peak_post_deamp": peak_in,
    }


def render_with(model, prep):
    """Run any Reverb-2-shaped model over the prepared input and re-apply
    the master amplitude + hardclip, returning (body, clipped_samples)."""
    from model.effects.qmath import qmul  # noqa: PLC0415

    n_blocks, a_q = prep["n_blocks"], prep["a_q"]
    in_l, in_r = prep["in_l"], prep["in_r"]
    out = np.zeros((2, n_blocks * BLOCK), dtype=np.float32)
    clipped = 0
    for b in range(n_blocks):
        s0, s1 = b * BLOCK, (b + 1) * BLOCK
        ol, orr = model.process_block(in_l[s0:s1], in_r[s0:s1])
        for ch, vals in ((0, ol), (1, orr)):
            row = []
            for v in vals:
                y = qmul(a_q, v, "Q13.18", A_FMT, A_FMT)
                if y > HARDCLIP8 or y < -HARDCLIP8:
                    clipped += 1
                    y = min(HARDCLIP8, max(-HARDCLIP8, y))
                row.append(y / A_SCALE)
            out[ch, s0:s1] = row
    start = SETTLE_BLOCKS * BLOCK
    return out[:, start:start + prep["frames"]], clipped


def frozen_model(prep):
    m = Reverb2Model(Reverb2Params(prep["inst"]["params"]),
                     "g%d" % prep["slot"], ENGINE_PROFILE)
    m.initialize()
    return m


def run(slug, seq, cfg, fixtures_dir, out_dir):
    prep = prepare(slug, seq, cfg, fixtures_dir)
    inst, slot, side, bp = (prep["inst"], prep["slot"], prep["side"],
                            prep["bypass_entry"])
    a_d, frames, n_blocks = prep["a_d"], prep["frames"], prep["n_blocks"]
    peak_in = prep["input_peak_post_deamp"]
    body, clipped = render_with(frozen_model(prep), prep)

    os.makedirs(out_dir, exist_ok=True)
    wav_path = os.path.join(out_dir, f"model__{slug}__{seq}.f32.wav")
    write_wav_stereo_f32(wav_path, body)

    manifest = {
        "schema_version": 1,
        "leaf": "SXT-028f",
        "follow_up": "F-028f-1 (#126)",
        "slug": slug,
        "sequence": seq,
        "claim_scope": "model-vs-pinned-engine input for the fx:Reverb 2 "
                       "class only; establishes no preset-support, coverage "
                       "or musical-quality claim",
        "model_revision": model_revision(),
        "alloc_profile": ENGINE_PROFILE.name,
        "input_boundary": {
            "kind": "per-slot-bypass (global-last)",
            "bypass_wav": bp["wav"],
            "bypass_sha256": bp["sha256"],
            "wet_wav": side["wet"]["wav"],
            "wet_sha256": side["wet"]["sha256"],
            "reverb2_slot": slot,
            "role": inst["role"],
            "master_volume_db": cfg["volume_f"],
            "master_amplitude": a_d,
            "deamp_then_quantize": "bypass / A in double, then one Q10.21 "
                                   "round-half-up (<= 1/2 LSB, ~ -132 dBFS "
                                   "class, declared)",
        },
        "params": inst["params"],
        "settle_blocks": SETTLE_BLOCKS,
        "blocks_total": n_blocks,
        "render_frames": frames,
        "input_peak_post_deamp": peak_in,
        "master_hardclip_samples": clipped,
        "model_peak_abs": float(np.max(np.abs(body))) if body.size else 0.0,
        "model_wav": os.path.relpath(wav_path, REPO),
    }
    mp = os.path.join(out_dir, f"model__{slug}__{seq}.json")
    with open(mp, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({k: manifest[k] for k in (
        "slug", "sequence", "blocks_total", "input_peak_post_deamp",
        "model_peak_abs", "master_hardclip_samples", "model_wav")}, indent=2))
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", default="seq-notes-coverage-v1")
    ap.add_argument("--fixtures-dir",
                    default=os.path.join(REPO, "reports", "SXT-028f", "fixtures"))
    ap.add_argument("--inputs-dir",
                    default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "SXT-028f", "artifacts"))
    args = ap.parse_args()
    with open(os.path.join(args.inputs_dir,
                           f"type-reverb 2-{args.slug}.json")) as f:
        cfg = json.load(f)
    run(args.slug, args.seq, cfg, args.fixtures_dir, args.out_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
