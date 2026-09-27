#!/usr/bin/env python3
"""SXT-023 budget-diagnosis engine probe: render a DIAGNOSTIC variant of a
chosen preset on the pinned engine with the Delay LFO depth set to 0.

This is diagnosis tooling for the SXT-017 decision, NOT a fixture of record
and NOT a support/fidelity claim: it renders a MODIFIED preset state so the
static delay path (taps/filters/mix/width) can be compared against the model
with the modulation mechanism disabled on BOTH sides.

Policies inherited from tools/render_fx_fixtures.py (fresh instance, reset,
settle, block-quantized scheduling, identical tails, 3x bit-identical
determinism gate). The only difference is the declared param override after
loadPatch, applied via the engine's own setters on both delay instances.
"""
import argparse
import hashlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "fixtures"))

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402
import render_fixture as rf  # noqa: E402
import tools.render_fx_fixtures as rff  # noqa: E402

SR = 48000
PRESETS = {
    "metallic": "resources/data/patches_factory/Plucks/Metallic.fxp",
    "dexie": "resources/data/patches_3rdparty/John Valentine/Keys/Dexie Swirly E-Piano.fxp",
}
SEQ = "seq-notes-coverage-v1"


def sha256_buf(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def render_probe(surgepy, slug, rel_path, depth_override, rate_override=None):
    seq, seq_path, seq_sha = rf.load_sequence(SEQ)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    bufs, infos = [], []
    for _rep in range(3):
        s = surgepy.createSurge(float(SR))
        try:
            if not s.loadPatch(abs_path):
                raise RuntimeError("loadPatch failed")
            patch = s.getPatch()
            overridden = []
            for slot in range(16):
                fx = patch["fx"][slot]
                if int(s.getParamVal(fx["type"])) == 1:  # fxt_delay
                    s.setParamVal(fx["p"][7], depth_override)
                    if rate_override is not None:
                        s.setParamVal(fx["p"][6], rate_override)
                    overridden.append(slot)
            s.pitchBend(0, 0)
            s.channelController(0, 64, 0)
            s.channelController(0, 1, 0)
            s.channelController(0, 11, 0)
            s.channelAftertouch(0, 0)
            s.allNotesOff()
            bs = int(s.getBlockSize())
            settle_blocks = 240
            s.processMultiBlock(s.createMultiBlock(settle_blocks))
            events = seq["events"]
            last_t = max(e["t"] for e in events if e["type"] in ("note_on", "note_off"))
            total_samples = last_t + int(float(seq.get("tail_s", 2.5)) * SR)
            total_blocks = -(-total_samples // bs)
            buf = s.createMultiBlock(total_blocks)
            quant = lambda t: -(-t // bs)  # noqa: E731
            dispatched, b = 0, 0
            while b < total_blocks:
                nxt = rf.dispatch(s, events[dispatched:], b, quant) + dispatched
                seg = total_blocks if nxt >= len(events) else max(quant(events[nxt]["t"]), b + 1)
                s.processMultiBlock(buf, b, seg - b)
                b = seg
                dispatched = nxt
            stereo = np.asarray(buf, dtype=np.float32).copy()
            depths = [float(s.getParamVal(patch["fx"][i]["p"][7])) for i in overridden]
            bufs.append(stereo)
            infos.append({"blocks": total_blocks, "peak": float(np.abs(stereo).max()),
                          "overridden_slots": overridden, "depth_readback": depths})
        finally:
            del s
    hs = [sha256_buf(x) for x in bufs]
    if any(h != hs[0] for h in hs):
        raise RuntimeError(f"determinism gate failed: {hs}")
    return bufs[0], infos[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, choices=sorted(PRESETS))
    ap.add_argument("--depth", type=float, default=0.0)
    ap.add_argument("--rate", type=float, default=None)
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "sxt-023",
                                         "artifacts-followup", "budget-diagnosis"))
    args = ap.parse_args()
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    stereo, info = render_probe(surgepy, args.slug, PRESETS[args.slug], args.depth,
                                rate_override=args.rate)
    os.makedirs(args.out_dir, exist_ok=True)
    tag = (f"engprobe_d{args.depth}_r{args.rate}__{args.slug}"
           f"__seq-notes-coverage-v1.f32.wav")
    path = os.path.join(args.out_dir, tag)
    rff.write_wav_stereo_f32(path, stereo)
    meta = {
        "schema_version": 1,
        "kind": "sxt-023 budget-diagnosis engine probe (diagnostic, not a fixture of record)",
        "slug": args.slug,
        "preset": PRESETS[args.slug],
        "override": {"depth_p7": args.depth, "rate_p6": args.rate,
                     "slots": info["overridden_slots"], "depth_readback": info["depth_readback"]},
        "frames": int(stereo.shape[1]), "peak_abs_float": info["peak"],
        "determinism_gate": "3x bit-identical",
        "render_sha256": rf.sha256_file(path),
        "policies": "render_fx_fixtures.py (settle 240 blocks, block-quantized, tails)",
    }
    import json
    with open(path + ".json", "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
