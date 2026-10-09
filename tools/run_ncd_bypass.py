#!/usr/bin/env python3
"""SXT-023 NC-d re-run (issue #16): bypass transparency of the revised runner.

Drives model/effects/run_fx_model.run_chain with an EMPTY chain (no inserts,
no sends) and master amplitude A = 1.0 (volume 0 dB, fm_bass_1's declared
volume) over the fm_bass_1 dry fixture, preceded by the revised runner's
SETTLE_BLOCKS silent pre-roll. out = clip8(A * x) must equal the quantized
Q10.21 input bit-for-bit on both channels for every sample.

Discrimination check (the comparison must be able to fail): the same input
through A = 1.0 - 1 LSB (Q13.18) must produce mismatches; if it does not, the
record is NO_VERDICT rather than PASS.

Writes reports/sxt-023/negative-controls/nc-d-bypass-rerun-issue16.json
(the PR #44 nc-d-bypass.json record is kept unedited). Model-side only; no
engine or RTL leg.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from model.effects.qmath import to_q  # noqa: E402
from model.effects.delay.delay_model import A_FMT, G_FMT, BLOCK  # noqa: E402
from model.effects.run_fx_model import (  # noqa: E402
    SETTLE_BLOCKS, check_settle_against_sidecar, db_to_linear_d,
    read_wav_stereo_f32, run_chain,
)

SLUG = "fm_bass_1"
OUT = os.path.join(REPO, "reports", "sxt-023", "negative-controls",
                   "nc-d-bypass-rerun-issue16.json")


def count_mismatches(in_l, in_r, n_blocks, a_q):
    mism = 0
    for b in range(n_blocks):
        il = in_l[b * BLOCK:(b + 1) * BLOCK]
        ir = in_r[b * BLOCK:(b + 1) * BLOCK]
        ol, orr, _ = run_chain([], [], il, ir, a_q)
        mism += sum(o != i for o, i in zip(ol, il))
        mism += sum(o != i for o, i in zip(orr, ir))
    return mism


def main():
    fx = os.path.join(REPO, "reports", "sxt-023", "fixtures")
    cfg = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs", f"{SLUG}.json")))
    check_settle_against_sidecar(os.path.join(fx, f"{SLUG}__seq-notes-coverage-v1.json"))
    a_d = db_to_linear_d(cfg["volume_f"])
    if a_d != 1.0:
        raise ValueError(f"{SLUG} volume {cfg['volume_f']} dB is not A=1.0")
    dry, _sr = read_wav_stereo_f32(os.path.join(fx, f"{SLUG}__seq-notes-coverage-v1-dry.f32.wav"))
    frames = dry.shape[1]
    n_blocks = SETTLE_BLOCKS + (-(-frames // BLOCK))
    pad = n_blocks * BLOCK - SETTLE_BLOCKS * BLOCK - frames
    zeros = [0] * (SETTLE_BLOCKS * BLOCK)
    in_l = zeros + [to_q(float(x), A_FMT) for x in dry[0]] + [0] * pad
    in_r = zeros + [to_q(float(x), A_FMT) for x in dry[1]] + [0] * pad

    a_q = to_q(1.0, G_FMT)
    mism = count_mismatches(in_l, in_r, n_blocks, a_q)
    mism_disc = count_mismatches(in_l, in_r, n_blocks, a_q - 1)
    samples = 2 * n_blocks * BLOCK
    if mism_disc == 0:
        verdict = "NO_VERDICT"
    else:
        verdict = "PASS" if mism == 0 else "FAIL"
    rec = {
        "bypass": "empty chain, A=1.0 (volume 0 dB); out = clip8(A*x) must equal x bit-for-bit",
        "slug": SLUG,
        "settle_blocks": SETTLE_BLOCKS,
        "blocks": n_blocks,
        "samples": samples,
        "samples_note": "L+R over settle pre-roll + fixture content (padded to whole blocks)",
        "mismatches": mism,
        "bit_transparent": mism == 0,
        "discrimination_check": {
            "a_fixed": "A = 1.0 - 1 LSB (Q13.18)",
            "mismatches": mism_disc,
            "fires": mism_disc > 0,
        },
        "scope": "model-side only (run_fx_model.run_chain); no engine or RTL leg",
        "supersedes_for_revised_tree": "nc-d-bypass.json (PR #44, pre-revision runner; kept unedited)",
        "verdict": verdict,
    }
    with open(OUT, "w") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    print(json.dumps(rec))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
