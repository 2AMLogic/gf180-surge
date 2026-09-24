#!/usr/bin/env python3
"""SXT-040 cost accounting: count the model-side qmul calls (MACs of the
declared Q discipline) of a full canonical render, mirroring
tools/count_classic_model_qmuls.py. Planning numbers under the 1-MAC/cycle
assumption (A-DSP-1c), not technology claims."""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "sine"))

from model.voice import voice_model as vm  # noqa: E402

COUNTER = {"n": 0}
_orig_qmul = vm.qmul


def counting_qmul(a, b, fa=vm.FQ, fb=vm.FQ, fq=vm.FQ):
    COUNTER["n"] += 1
    return _orig_qmul(a, b, fa=fa, fb=fb, fq=fq)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--sequence", default="seq-notes-repeated-v1")
    args = ap.parse_args()

    vm.qmul = counting_qmul
    import sine_model as sm  # noqa: E402  (module import binds vm at call time)
    assert sm.vm is vm
    import run_model as rm

    sys.argv = ["run_model.py", "--inputs", args.inputs,
                "--sequence", args.sequence, "--out-dir",
                "/tmp/sxt040-qmul-count"]
    try:
        rm.main()
    except SystemExit as e:  # pragma: no cover
        if e.code not in (0, None):
            raise
    print(json.dumps({"inputs": args.inputs, "sequence": args.sequence,
                      "model_qmuls": COUNTER["n"]}))


if __name__ == "__main__":
    main()
