#!/usr/bin/env python3
"""SXT-023 NC-c regression: extended-max-feedback corner of the frozen Delay
model (fb gain 1.0 through softclip, mix 1.0, click train, 1,740 blocks).
Bounded output with zero saturation = PASS (model-side only; no engine leg).
Writes reports/sxt-023/negative-controls/nc-c-maxfb-corner-rerun-issue16.json
(the PR #44 nc-c record is kept unedited)."""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from model.effects.delay.delay_model import DelayModel, DelayParams  # noqa: E402
from model.effects.qmath import to_q, FRAC  # noqa: E402
from model.effects.delay.delay_model import A_FMT  # noqa: E402

BLOCKS = 1740


def main():
    d = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs", "metallic.json")))
    p = dict(d["chain"]["ains"][0]["params"])
    p.update(feedback_f=1.0, feedback_extend=True, mix_f=1.0)
    m = DelayModel(DelayParams(p), "nc_c")
    m.initialize()
    one = to_q(0.25, A_FMT)
    peak, sat, n = 0, 0, 0
    limit = 8 << FRAC[A_FMT]
    for b in range(BLOCKS):
        x = [one if (b * 32 + k) % 4800 == 0 else 0 for k in range(32)]
        ol, orr = m.process_block(x, list(x))
        for v in ol + orr:
            n += 1
            peak = max(peak, abs(v))
            sat += abs(v) >= limit
    rec = {"corner": "max-feedback extended fb=+1.0 (fb gain 1.0), mix=1.0, click train",
           "samples": n, "blocks": BLOCKS, "max_abs_out": peak / (1 << FRAC[A_FMT]),
           "saturated_samples": sat, "bounded": sat == 0,
           "verdict": "PASS" if sat == 0 else "FAIL"}
    out = os.path.join(REPO, "reports", "sxt-023", "negative-controls",
                       "nc-c-maxfb-corner-rerun-issue16.json")
    json.dump(rec, open(out, "w"), indent=1)
    print(json.dumps(rec))
    return 0 if sat == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
