#!/usr/bin/env python3
"""SXT-012: diagnose the source of render-to-render variation in the oracle.

The pinned engine seeds its audio-thread RNG from wall-clock time at instance
creation (SurgeStorage.h RNGGen: std::minstd_rand g(system_clock::now())),
and oscillators whose stored `retrigger` flag is false consume rand_01() per
unison voice at voice start to set a free-running initial phase
(ClassicOscillator.cpp, SineOscillator.cpp). surgepy exposes no seed setter.

This script renders a fixed probe sequence through a preset N times in fresh
instances (unmodified patch), then repeats with `retrigger` forced ON for all
six oscillators via surgepy parameter setters (a DIAGNOSTIC adaptation that
is never used for committed fixtures). If the unmodified renders vary while
the retrigger-forced renders are bit-identical, the variation is attributable
to free-running initial oscillator phase and to nothing else in the path.

Output: JSON on stdout (hashes, bit-identity, quantified variation).
"""

import argparse
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402

SR = 48000


def render_probe(surgepy, preset_abs, force_retrigger):
    import surgepy.constants as C

    s = surgepy.createSurge(float(SR))
    try:
        if not s.loadPatch(preset_abs):
            raise SystemExit(f"loadPatch failed: {preset_abs}")
        if force_retrigger:
            for sc in range(2):
                for o in range(3):
                    s.setParamVal(s.getPatch()["scene"][sc]["osc"][o]["retrigger"], 1.0)
        bs = int(s.getBlockSize())
        blocks = int(2.0 * SR) // bs
        buf = s.createMultiBlock(blocks)
        s.playNote(0, 60, 100, 0)
        s.processMultiBlock(buf, 0, blocks // 2)
        s.releaseNote(0, 60, 0)
        s.processMultiBlock(buf, blocks // 2, blocks - blocks // 2)
        mono = 0.5 * (np.asarray(buf)[0] + np.asarray(buf)[1])
        return mono
    finally:
        del s


def measure(surgepy, preset_abs, repeats, force_retrigger):
    renders, hashes = [], []
    for _ in range(repeats):
        m = render_probe(surgepy, preset_abs, force_retrigger)
        hashes.append(hashlib.sha256(np.ascontiguousarray(m).tobytes()).hexdigest())
        renders.append(m)
    entry = {"retrigger_forced": force_retrigger, "sha256": hashes,
             "bit_identical": all(h == hashes[0] for h in hashes)}
    if not entry["bit_identical"]:
        d = np.abs(renders[0] - renders[1])
        entry["max_abs_diff_render1_vs_2"] = float(d.max())
        entry["peak_abs_float_render1"] = float(np.max(np.abs(renders[0])))
        entry["first_divergence_sample"] = int(np.argmax(d > 0)) if (d > 0).any() else None
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", required=True, help="factory preset name, e.g. 'Leads/Koala 2.fxp'")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    oc.apply_engine_env()
    surgepy = oc.import_surgepy()
    preset_abs = os.path.join(oc.data_home(), "patches_factory", args.preset)
    blob = oc.git_blob_sha1(preset_abs)

    out = {
        "schema_version": 1,
        "issue": "SXT-012",
        "preset": args.preset,
        "preset_census_blob_sha1": blob,
        "repeats": args.repeats,
        "unmodified": measure(surgepy, preset_abs, args.repeats, False),
        "retrigger_forced_diagnostic": measure(surgepy, preset_abs, args.repeats, True),
        "interpretation": "unmodified varies + retrigger-forced bit-identical => variation "
                          "attributable to free-running initial oscillator phase (wall-clock "
                          "seeded engine RNG); any other outcome means additional variation "
                          "sources exist and must be investigated before quantified budgets.",
        "note": "retrigger-forced renders are a diagnostic adaptation only; committed "
                "fixtures always use unmodified patches.",
    }
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
