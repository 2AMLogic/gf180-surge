#!/usr/bin/env python3
"""SXT-023 NC-b runner: nearest-neighbor delay model vs pinned-engine wet bus.

Runs the committed NEGATIVE CONTROL model (model/effects/delay/
delay_model_nn.py — nearest-neighbor tap substitution, NOT the frozen sinc
model) over the committed fixture dry buses with the frozen chain wiring
(run_fx_model.run_chain), writes the NN wet render, and compares it against
the committed engine wet fixture with tools/compare_fx_reference.py budgets.

The control's acceptance is that it FAILS the proposed budget check grossly
(sinc interpolation is load-bearing). Its numbers must be reproducible from
committed inputs + committed scripts only (no engine at run time).
"""
import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from model.effects.run_fx_model import (  # noqa: E402
    SETTLE_BLOCKS, run_chain, read_wav_stereo_f32,
    db_to_linear_d,
)
from model.effects.qmath import to_q, FRAC  # noqa: E402
from model.effects.delay.delay_model_nn import DelayModel as NNDelayModel, DelayParams  # noqa: E402
from model.effects.eq.eq_model import EqModel, EqParams  # noqa: E402
from tools.render_fx_fixtures import write_wav_stereo_f32  # noqa: E402


def build_nn_models(cfg):
    ains = []
    for e in cfg["chain"]["ains"]:
        if e["type"] == "delay":
            ains.append(("delay", NNDelayModel(DelayParams(e["params"]), f"a{e['slot']}")))
        elif e["type"] == "eq":
            ains.append(("eq", EqModel(EqParams(e["params"]), f"a{e['slot']}")))
        else:
            raise ValueError(e["type"])
    sends = []
    for e in cfg["chain"]["sends"]:
        if e["type"] == "delay":
            sends.append(("delay", NNDelayModel(DelayParams(e["params"]), f"s{e['slot']}"),
                          e["send_slot"], e["send_gain_f"], e["return_f"]))
        elif e["type"] == "eq":
            sends.append(("eq", EqModel(EqParams(e["params"]), f"s{e['slot']}"),
                          e["send_slot"], e["send_gain_f"], e["return_f"]))
        else:
            raise ValueError(e["type"])
    return ains, sends


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "sxt-023",
                                         "artifacts-followup", "nc-b"))
    args = ap.parse_args()
    slug = args.slug

    cfg = json.load(open(os.path.join(REPO, "model/effects/fx_inputs", slug + ".json")))
    dry, _ = read_wav_stereo_f32(os.path.join(
        REPO, "reports/sxt-023/fixtures", f"{slug}__seq-notes-coverage-v1-dry.f32.wav"))
    frames = dry.shape[1]
    n_total = SETTLE_BLOCKS + (-(-frames // 32))
    frames_padded = n_total * 32

    a_q = to_q(db_to_linear_d(cfg["volume_f"]), "Q13.18")
    a_d = db_to_linear_d(cfg["volume_f"])
    if float(max(abs(dry).max(), 0)) == 0.0:
        raise ValueError("empty dry bus")

    zeros = [0] * (SETTLE_BLOCKS * 32)
    in_l = zeros + [to_q(float(x) / a_d, "Q10.21") for x in dry[0]] \
        + [0] * (frames_padded - SETTLE_BLOCKS * 32 - frames)
    in_r = zeros + [to_q(float(x) / a_d, "Q10.21") for x in dry[1]] \
        + [0] * (frames_padded - SETTLE_BLOCKS * 32 - frames)

    ains, sends = build_nn_models(cfg)
    for _k, m in ains:
        m.initialize()
    for _k, m, _i, _s, _r in sends:
        m.initialize()

    import numpy as np
    out = np.zeros((2, frames_padded), dtype=np.float32)
    for b in range(n_total):
        ol, orr, _sp = run_chain(ains, sends,
                                 in_l[b * 32:(b + 1) * 32],
                                 in_r[b * 32:(b + 1) * 32], a_q)
        out[0, b * 32:(b + 1) * 32] = [v / float(1 << FRAC["Q10.21"]) for v in ol]
        out[1, b * 32:(b + 1) * 32] = [v / float(1 << FRAC["Q10.21"]) for v in orr]

    os.makedirs(args.out_dir, exist_ok=True)
    wav_path = os.path.join(args.out_dir, f"ncb__{slug}__seq-notes-coverage-v1.f32.wav")
    write_wav_stereo_f32(wav_path, out[:, SETTLE_BLOCKS * 32:SETTLE_BLOCKS * 32 + frames])

    ref_path = os.path.join(REPO, "reports/sxt-023/fixtures",
                            f"{slug}__seq-notes-coverage-v1-wet.f32.wav")
    metrics_path = os.path.join(args.out_dir, f"nc-b-{slug}.json")
    subprocess.run([sys.executable,
                    os.path.join(REPO, "tools", "compare_fx_reference.py"),
                    "--ref", ref_path, "--model", wav_path,
                    "--preset", slug, "--json", metrics_path],
                   check=True)
    print(f"NC-b {slug}: NN render {os.path.relpath(wav_path, REPO)}\n"
          f"  metrics   {os.path.relpath(metrics_path, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
