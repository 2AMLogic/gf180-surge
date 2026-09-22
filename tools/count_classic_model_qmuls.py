#!/usr/bin/env python3
"""SXT-033: measure the qmul (MAC) count of the frozen Classic-family model
over a fixture run (issue #67 cost acceptance item).

The frozen model is the specification of the RTL schedule; every
`voice_model.qmul` call is one multiply (round-half-up Q discipline), so
the model-side count is the authoritative MAC measure of the schedule.
The iverilog testbench's own `qmul()` counter cross-checks the RTL
stimulus run but undercounts by construction: the tb inlines the per-tap
`term*gain` product (tb_classic.sv impulse-inject task) outside its
`qmul()` function, and integer equality is about VALUES, not which
callable computed them. Both numbers are recorded in
reports/SXT-033/EVIDENCE.md section 5. Pure integer Python: no oracle,
no iverilog.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "classic"))

from model.voice import voice_model as vm  # noqa: E402

_orig_qmul = vm.qmul
COUNT = {"qmul": 0}


def _counting_qmul(a, b, fa=vm.FQ, fb=vm.FQ, fq=vm.FQ):
    COUNT["qmul"] += 1
    return _orig_qmul(a, b, fa=fa, fb=fb, fq=fq)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", required=True,
                    help="model/oscillators/classic/inputs/<carrier>.json")
    ap.add_argument("--sequence", default="seq-notes-repeated-v1")
    ap.add_argument("--max-blocks", type=int, default=None)
    args = ap.parse_args()

    vm.qmul = _counting_qmul
    COUNT["qmul"] = 0
    import run_model  # noqa: E402  (imports under the patched vm)
    sys.argv = ["run_model.py", "--inputs", args.inputs,
                "--sequence", args.sequence,
                "--out-dir", "/tmp/sxt033-qmul-count"]
    if args.max_blocks is not None:
        sys.argv += ["--max-blocks", str(args.max_blocks)]
    rc = run_model.main()
    if rc not in (0, None):
        return rc
    print(json.dumps({
        "inputs": os.path.relpath(args.inputs, REPO),
        "sequence": args.sequence,
        "max_blocks": args.max_blocks,
        "model_qmul_calls": COUNT["qmul"],
        "note": "authoritative MAC measure of the frozen schedule; the tb "
                "qmul() counter undercounts (inline per-tap term*gain)",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
