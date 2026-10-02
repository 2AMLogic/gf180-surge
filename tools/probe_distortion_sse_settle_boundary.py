#!/usr/bin/env python3
"""SXT-028e-sse (#136): MEASURE where the effect's history starts.

The fixture render runs a 0.25 s (375-block) settle before the first note.
Whether that settle belongs to the **synth** (already baked into the all-off
dry bus the model reads) or also to the **effect** (so the model must be
pre-rolled through it) is a boundary this harness must not guess: the two
choices differ by 73 dB on the anchor carrier, which is larger than the
whole [PROPOSED] budget.

This probe decides it by measurement, on the pinned engine, and writes
`reports/SXT-028e-sse/artifacts/settle-boundary.json`:

  A. settle-length invariance — render the same leg with a 375-block and a
     3750-block settle. BYTE-IDENTICAL means the effect state provably does
     not evolve during a silent settle.
  B. construction invariance — render the synthetic carrier (a) constructed
     in place and (b) saved to a `.fxp` and re-loaded into a fresh instance
     through the ordinary `loadPatch` path. BYTE-IDENTICAL means A is the
     engine's behaviour for an ordinary loaded preset, not an artifact of
     how this leaf constructs its declared synthetic carriers.
  C. the model boundary itself — run the frozen model with 0 and with 375
     blocks of silent pre-roll and report both achieved max/rms against the
     engine's wet bus. Recorded, not tuned.

A failure of A or B is reported as such and makes the declared boundary
UNRESOLVED; nothing is averaged, nothing is chosen by which answer scores
better.

Original tool, Apache-2.0. Drives the GPL engine through `surgepy` only.
"""

import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "fixtures"))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

import numpy as np  # noqa: E402

import distortion_sse_synthetic as syn  # noqa: E402
import render_distortion_sse_fixtures as rdf  # noqa: E402
import render_fx_fixtures as rfx  # noqa: E402

ART = os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts")
LSB = 1.0 / (1 << 21)
PROBE_SLUG = syn.ANCHOR_SLUG          # the one-instance harness anchor
PROBE_SEQ = "seq-poly-8-v1"
LONG_SETTLE_S = 2.5                   # 10x the declared 0.25 s


def _seq(name, settle_s=None):
    p = os.path.join(REPO, "fixtures", "sequences", f"{name}.json")
    s = json.load(open(p))
    if settle_s is not None:
        s = dict(s, settle_s=settle_s)
    return s


def _metrics(ref, mod):
    """Same mono-sum definition the leg's comparator uses, so the two
    records' dBFS figures are directly comparable."""
    n = min(ref.shape[1], mod.shape[1])
    import compare_audio_reference as car
    d = (0.5 * (ref[0, :n] + ref[1, :n])
         - 0.5 * (mod[0, :n] + mod[1, :n])).astype(np.float64)
    rms = float(np.sqrt((d ** 2).mean()))
    return {
        "max_abs_diff_lsb": float(np.abs(d).max() / LSB),
        "rms_diff_dbfs": car.rms_dbfs(rms / LSB, float(1 << 20)),
    }


def main():
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    base = os.path.join(oc.engine_dir(), syn.SYN_BASE)
    if not os.path.exists(base):
        print(f"REFUSING: synthetic base patch absent: {base}", file=sys.stderr)
        return 2
    slots = syn.carrier_slots(PROBE_SLUG)

    # --- A. settle-length invariance ---------------------------------------
    short, info_s = rdf._render_once(
        surgepy, base, _seq(PROBE_SEQ, 0.25),
        rdf.synthetic_mutator(PROBE_SLUG, slots))
    long_, info_l = rdf._render_once(
        surgepy, base, _seq(PROBE_SEQ, LONG_SETTLE_S),
        rdf.synthetic_mutator(PROBE_SLUG, slots))
    a_ok = rfx.sha256_buf(short) == rfx.sha256_buf(long_)

    # --- B. construction invariance ----------------------------------------
    s = surgepy.createSurge(48000.0)
    try:
        if not s.loadPatch(base):
            print("REFUSING: loadPatch failed", file=sys.stderr)
            return 2
        s.pitchBend(0, 0)
        s.channelController(0, 64, 0)
        s.channelController(0, 1, 0)
        s.channelController(0, 11, 0)
        s.channelAftertouch(0, 0)
        s.allNotesOff()
        syn.construct(s, PROBE_SLUG, slots,
                      int(0.25 * 48000) // int(s.getBlockSize()))
        tmpdir = tempfile.mkdtemp(prefix="sxt028e-sse-settle-")
        saved = os.path.join(tmpdir, "constructed.fxp")
        s.savePatch(saved)
    finally:
        del s
    reloaded, _info_r = rdf._render_once(surgepy, saved, _seq(PROBE_SEQ, 0.25),
                                         None)
    b_ok = rfx.sha256_buf(short) == rfx.sha256_buf(reloaded)

    # --- C. the model boundary ---------------------------------------------
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rdsm", os.path.join(REPO, "model", "effects",
                             "run_distortion_sse_model.py"))
    rdsm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rdsm)
    from compare_chorus_reference import read_wav_stereo_f32

    ref = np.asarray(short, dtype=np.float32)
    outdir = tempfile.mkdtemp(prefix="sxt028e-sse-settle-model-")
    legs = {}
    for pre in (0, rdsm.FIXTURE_SETTLE_BLOCKS):
        rdsm.run(PROBE_SLUG, PROBE_SEQ,
                 os.path.join(REPO, "reports", "SXT-028e-sse", "fixtures"),
                 os.path.join(ART, "synthetic"), outdir,
                 out_name=f"preroll-{pre}.f32.wav", silent_preroll_blocks=pre)
        mod, _sr = read_wav_stereo_f32(os.path.join(outdir,
                                                    f"preroll-{pre}.f32.wav"))
        legs[str(pre)] = _metrics(ref, mod)

    declared = 0 if (a_ok and b_ok) else None
    rec = {
        "leaf": "SXT-028e-sse",
        "issue": "#136 reference leg: where does the effect's history start?",
        "probe_carrier": PROBE_SLUG,
        "probe_carrier_kind": "DECLARED-SYNTHETIC (the harness anchor)",
        "sequence": PROBE_SEQ,
        "engine_pin": "surge-synthesizer/surge@"
                      "58914e59c608ed4384ba6002e44c3465c58b2e71",
        "sample_rate": 48000,
        "block_size": 32,
        "A_settle_length_invariance": {
            "settle_blocks_compared": [info_s["settle_blocks"],
                                       info_l["settle_blocks"]],
            "sha256": [rfx.sha256_buf(short), rfx.sha256_buf(long_)],
            "byte_identical": bool(a_ok),
            "means": "the engine's effect state does NOT evolve during a "
                     "silent settle",
        },
        "B_construction_invariance": {
            "sha256_constructed_in_place": rfx.sha256_buf(short),
            "sha256_saved_and_reloaded": rfx.sha256_buf(reloaded),
            "byte_identical": bool(b_ok),
            "means": "A is the engine's behaviour for an ORDINARY loaded "
                     "preset, not an artifact of the synthetic construction",
        },
        "C_model_boundary_vs_engine": {
            "silent_preroll_blocks": legs,
            "budget_reference": "[PROPOSED] SXT-023 effect slice: max <= "
                                "8192 LSB Q10.21, rms <= -46 dBFS. PROPOSED, "
                                "not frozen (#12).",
        },
        "declared_silent_preroll_blocks": declared,
        "status": "RESOLVED" if declared == 0 else "UNRESOLVED",
        "note": "If A or B is not byte-identical the boundary is UNRESOLVED "
                "and the reference leg must say so; the harness does not pick "
                "whichever pre-roll scores better.",
        "claim_scope": "a harness boundary measurement. It is not a fidelity "
                       "result, not a support claim, and it does not change "
                       "the frozen model (byte-frozen; "
                       "docs/byte-frozen-sources.json).",
    }
    os.makedirs(ART, exist_ok=True)
    out = os.path.join(ART, "settle-boundary.json")
    with open(out, "w") as f:
        json.dump(rec, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(rec, indent=2, sort_keys=True))
    print(f"\nwrote {os.path.relpath(out, REPO)}")
    return 0 if rec["status"] == "RESOLVED" else 2


if __name__ == "__main__":
    sys.exit(main())
