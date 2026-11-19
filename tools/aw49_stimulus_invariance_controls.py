#!/usr/bin/env python3
"""SXT-028a stimulus-quantization invariance control (#668).

The frozen model's input-boundary quantizer `f32_to_s32i()` scales the
float32 fixture samples to Q6.25. Under numpy >= 2 (NEP 50 weak scalars)
the product `np.float32 * python float` stays single precision, while
numpy 1.x value-based casting promoted it to double -- so an uncoerced
operand quantized 13 of the 32768 canonical stimulus words 1 LSB
differently between the two major versions, moving the whole
`canonical-temple-512b` txn log (measured; issue #668). The helper now
coerces its operand to a python float (#668, option (a)), making the
quantization version-invariant.

This control re-measures that invariant against the committed canonical
fixture and FAILS (exit 1) if quantizing the raw float32 scalar ever
differs from quantizing its exact double value -- i.e. if the installed
numpy major version can move the frozen model's input stimulus again.
Run it under both pinned majors for the two-version evidence (never a
host-tool install; throwaway envs):

  uv run --no-project --python 3.12 --with numpy==1.26.4 \
      python3 tools/aw49_stimulus_invariance_controls.py
  uv run --no-project --python 3.12 --with numpy==2.4.2 \
      python3 tools/aw49_stimulus_invariance_controls.py

Serialization (defined here; the stimulus-words hash is only comparable
between runs OF THIS SCRIPT -- three probes of the same defect produced
three distinct hash pairs before this serialization was pinned, see #668
correction 5): quantize every element of `gal_in` over the canonical
case's first 512 blocks, channel 0 then channel 1, 32 samples each =
32768 int32 words, serialized little-endian; the hash is sha256 over
that raw byte stream.

Writes nothing; verdict is the exit code plus a stdout "status:" line.
Exits 0 iff zero words differ.
Original to this repository (Apache-2.0).
"""

import hashlib
import json
import os
import struct
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-49"))

import galactic_model as gm  # noqa: E402

CANONICAL_NPZ = os.path.join(REPO, "reports", "sxt-028a", "fixtures",
                             "temple__seq-notes-coverage-v1-aw49-taps.npz")
BLOCKS = 512   # the canonical-temple-512b span


def main():
    npz = np.load(CANONICAL_NPZ)
    gal_in = npz["gal_in"]
    assert gal_in.dtype == np.float32, "canonical fixture must be float32"
    words = []
    diffs = []
    max_delta = 0
    vtype = None
    for b in range(min(BLOCKS, len(gal_in))):
        for ch in (0, 1):
            for x in gal_in[b, :, ch]:
                q_raw = gm.f32_to_s32i(x)
                q_dbl = gm.f32_to_s32i(float(x))
                if vtype is None:
                    vtype = type(x * float(1 << gm.FRAC_S32I)).__name__
                words.append(q_raw)
                if q_raw != q_dbl:
                    diffs.append((len(words) - 1, q_raw, q_dbl))
                    max_delta = max(max_delta, abs(q_raw - q_dbl))
    stim_sha = hashlib.sha256(
        struct.pack(f"<{len(words)}i", *words)).hexdigest()
    ok = not diffs
    doc = {
        "numpy": np.__version__,
        "python": sys.version.split()[0],
        "model_frozen_revision": gm.frozen_revision(),
        "words": len(words),
        "stimulus_words_sha256_le_int32": stim_sha,
        "scaling_type_under_installed_numpy": vtype,
        "differing_words_raw_vs_double": len(diffs),
        "max_abs_delta_q6_25_lsb": max_delta,
        "first_differing_index_word_doubled": diffs[:5],
    }
    print(json.dumps(doc, indent=2))
    print("status:", "PASS" if ok else
          "FAIL (f32_to_s32i is numpy-version sensitive)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
