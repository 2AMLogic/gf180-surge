#!/usr/bin/env python3
"""SXT-025 negative controls -- each must demonstrably FAIL the check it
targets (repo convention; exit 0 iff every control failed its check).

NC-A  placement/order permutation (issue #18: "reordering that preset's
      effects (wrong order) must be detected"). The chosen preset stores a
      single effect (Reverb 1 @ send2), so the reorder axis degenerates to
      the placement/order axis the image actually carries: the control
      rewrites the image's stored role send2 -> ains1 (insert phase instead
      of the send-return phase) and re-runs the integration chain. The
      comparator must flag the permuted run against the SAME upstream wet
      fixture. (Degeneracy recorded in the transcript; the order machinery
      itself is exercised by the image-verified engine_order invariant and
      by the chain's phase iteration.)
NC-B  tail truncation: the model wet render is cut 1.0 s after the last
      note-off; the SXT-024-style tail-continuity/decay checks must fail
      (the render ends mid-ringout above the floor).
NC-C  silent stub swapped into the integration slot: the Reverb1 leaf is
      replaced by an all-zero stub under the same chain; the wet-activity
      output contract (the wet render must differ from the all-off dry bus
      by the send/return energy) and the fidelity budgets must fail.
      The RTL-side stale stub is the committed reverb1_broken_mutant.sv,
      demonstrated in reports/sxt-025/rtl-exactness.json (kernel comparison
      FAILS) -- referenced, not re-run here.

Original to this repository (Apache-2.0).
"""
import argparse
import copy
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import numpy as np  # noqa: E402

from model.integration.integration_model import (  # noqa: E402
    IntegrationRun, Reverb1Counted,
)
from model.integration.run_model import read_wav_stereo_f32  # noqa: E402
from model.integration.compare_integration import (  # noqa: E402
    tail_checks,
)
from model.integration.extract_preset_inputs import (  # noqa: E402
    IMAGE_JSON, OUT_PATH as INPUTS_JSON,
)
from tools.compare_fx_reference import channel_metrics, PROPOSED  # noqa: E402

FIXTURES = os.path.join(REPO, "reports", "sxt-025", "fixtures")
ARTIFACTS = os.path.join(REPO, "reports", "sxt-025", "artifacts")
NC_DIR = os.path.join(REPO, "reports", "sxt-025", "negative-controls")
SEQ_DIR = os.path.join(REPO, "model", "integration", "sequences")


def wet_activity_contract(wet, dry):
    """Output contract for a wet render: it must differ from the all-off dry
    bus by the send/return wet energy (a silent/stale stub returns the dry
    signal itself and fails)."""
    n = min(wet.shape[1], dry.shape[1])
    d = wet[:, :n] - dry[:, :n]
    rms = float(np.sqrt((d.astype(np.float64) ** 2).mean()))
    return {"wet_minus_dry_rms": rms,
            "peak_abs": float(np.abs(d).max()),
            "contract_min_rms": 1e-4,
            "ok": rms > 1e-4}


def run_config(image, inputs, dry, frames, seq):
    run = IntegrationRun.__new__(IntegrationRun)
    IntegrationRun.__init__(run, image, inputs, dry, frames)
    return run.run(seq)


def nc_a(sequence):
    seq_name = sequence
    seq = json.load(open(os.path.join(SEQ_DIR, seq_name + ".json")))
    sidecar = json.load(open(os.path.join(
        FIXTURES, f"hells_bells__{seq_name}.json")))
    dry, _ = read_wav_stereo_f32(os.path.join(REPO, sidecar["dry"]["wav"]))
    ref, _ = read_wav_stereo_f32(os.path.join(
        FIXTURES, f"hells_bells__{seq_name}-wet.f32.wav"))
    frames = sidecar["render"]["frames"]

    image = json.load(open(IMAGE_JSON))
    mut = copy.deepcopy(image)
    slots = mut["body"]["graph"]["fx_slots"]
    derived = {s["slot"]: s for s in
               mut["body"]["derived"]["fx_section"]["slots"]}
    target = None
    for s in slots:
        if s.get("on") == 1 and s.get("t", 0) != 0:
            target = s["i"]
    if target is None:
        raise RuntimeError("no active FX slot to permute")
    # THE PERMUTATION: stored role send2 -> ains1 (insert), order derived
    slots[target]["r"] = "ains1"
    derived[target].update({"role": "ains1", "phase": 0,
                            "phase_name": "scene_A_insert",
                            "order_in_phase": 1, "engine_order": 0})
    mut_path = os.path.join(NC_DIR, "image-permuted-placement.json")
    with open(mut_path, "w", encoding="utf-8") as f:
        json.dump(mut, f, indent=2, sort_keys=True)

    # the control-plane inputs follow the permuted placement (the fault is a
    # different STORED placement; the extracted parameters are unchanged)
    inputs = json.load(open(INPUTS_JSON))
    mut_inputs = copy.deepcopy(inputs)
    for e in mut_inputs["fx_instances"]:
        if e["slot"] == target:
            e["role"] = "ains1"
            e["engine_order"] = 0
            e.pop("send_slot", None)
            e.pop("send_gain_f", None)
            e.pop("return_f", None)
    mut_inputs_path = os.path.join(NC_DIR, "inputs-permuted-placement.json")
    with open(mut_inputs_path, "w", encoding="utf-8") as f:
        json.dump(mut_inputs, f, indent=2, sort_keys=True)

    run = IntegrationRun(mut_path, mut_inputs_path, dry, frames)
    res = run.run(seq)
    wet = np.vstack([np.asarray(res["wet_l"], dtype=np.float32),
                     np.asarray(res["wet_r"], dtype=np.float32)])
    chs = channel_metrics(0.5 * (ref[0] + ref[1]),
                          0.5 * (wet[0] + wet[1]))
    budgets_fail = {
        "max_abs_diff_lsb": bool(chs["max_abs_diff_lsb"]
                                 > PROPOSED["max_abs_diff_lsb"]),
        "rms_diff_dbfs": bool(chs["rms_diff_dbfs"]
                              > PROPOSED["rms_diff_dbfs"]),
        "spectral_corr": bool(chs["spectral_corr"]
                              < PROPOSED["spectral_corr_min"]),
    }
    out = {
        "control": "NC-A placement/order permutation (send2 -> ains1)",
        "degeneracy_note": "the preset stores ONE effect, so reordering "
                           "degenerates to re-placing it across the engine's "
                           "fixed phase boundary (send_bus -> insert); the "
                           "comparator must flag it against the SAME fixture",
        "metrics": {k: chs[k] for k in ("max_abs_diff_lsb", "rms_diff_dbfs",
                                        "spectral_corr", "best_shift")},
        "budgets": PROPOSED,
        "budgets_violated": budgets_fail,
        "detected": any(budgets_fail.values()),
        "verdict": ("CONTROL-OK (permuted placement flagged by the comparator)"
                    if any(budgets_fail.values()) else
                    "CONTROL-BROKEN (permutation NOT detected -- finding!)"),
    }
    return out, wet


def nc_b(sequence):
    seq_name = sequence
    ref, _ = read_wav_stereo_f32(os.path.join(
        FIXTURES, f"hells_bells__{seq_name}-wet.f32.wav"))
    model, _ = read_wav_stereo_f32(os.path.join(
        ARTIFACTS, f"model__{seq_name}-wet.f32.wav"))
    trace = json.load(open(os.path.join(
        ARTIFACTS, f"trace__{seq_name}.json")))
    tail_start = trace["tail"]["last_noteoff_applied_sample"]
    cut = tail_start + 48000  # 1.0 s after the last note-off
    # baseline: the full model render passes the tail checks
    base = tail_checks(ref[0], ref[1], model[0], model[1], tail_start)
    # truncated render: the render STOPS (silence where the reference
    # continues), so the tail comparison spans the full reference tail
    n = ref.shape[1]
    pad = np.zeros((2, n), dtype=np.float32)
    pad[:, :cut] = model[:, :cut]
    trunc = tail_checks(ref[0], ref[1], pad[0], pad[1], tail_start)
    base_pass = (base["tail_rms_ok"] and base["tail_continuity_ok"]
                 and base["stereo_corr_ok"]
                 and base["decay_curve_ok"] is not False)
    trunc_fail = (not trunc["tail_continuity_ok"]) or \
                 (not trunc["tail_rms_ok"]) or \
                 (trunc["decay_curve_ok"] is False)
    out = {
        "control": "NC-B tail truncation (render cut 1.0 s after last "
                   "note-off)",
        "tail_start_sample": tail_start,
        "cut_sample": int(cut),
        "baseline": {"tail_rms_rel_db": base["tail_rms_rel_db"],
                     "continuity_ok": base["tail_continuity_ok"],
                     "pass": bool(base_pass)},
        "truncated": {"tail_frames_present": trunc["tail_frames"],
                      "tail_continuity_ok": trunc["tail_continuity_ok"],
                      "tail_rms_ok": trunc["tail_rms_ok"],
                      "decay_curve_ok": trunc["decay_curve_ok"]},
        "detected": bool(base_pass and trunc_fail),
        "verdict": ("CONTROL-OK (truncation flagged by the tail-continuity "
                    "check)" if (base_pass and trunc_fail) else
                    "CONTROL-BROKEN (truncation NOT detected -- finding!)"),
    }
    return out


def nc_c(sequence):
    seq_name = sequence
    seq = json.load(open(os.path.join(SEQ_DIR, seq_name + ".json")))
    sidecar = json.load(open(os.path.join(
        FIXTURES, f"hells_bells__{seq_name}.json")))
    dry, _ = read_wav_stereo_f32(os.path.join(REPO, sidecar["dry"]["wav"]))
    ref, _ = read_wav_stereo_f32(os.path.join(
        FIXTURES, f"hells_bells__{seq_name}-wet.f32.wav"))
    frames = sidecar["render"]["frames"]

    # silent stub in the integration slot
    orig = Reverb1Counted.process_block

    def silent(self, bl, br):
        return [0] * 32, [0] * 32

    Reverb1Counted.process_block = silent
    try:
        run = IntegrationRun(IMAGE_JSON, INPUTS_JSON, dry, frames)
        res = run.run(seq)
    finally:
        Reverb1Counted.process_block = orig
    wet = np.vstack([np.asarray(res["wet_l"], dtype=np.float32),
                     np.asarray(res["wet_r"], dtype=np.float32)])
    contract = wet_activity_contract(wet, dry)
    chs = channel_metrics(0.5 * (ref[0] + ref[1]),
                          0.5 * (wet[0] + wet[1]))
    detected = (not contract["ok"]) or \
               (chs["rms_diff_dbfs"] > PROPOSED["rms_diff_dbfs"])
    out = {
        "control": "NC-C silent stub swapped into the integration slot "
                   "(Reverb1 leaf -> all-zero block)",
        "wet_activity_contract": contract,
        "rms_diff_dbfs_vs_fixture": chs["rms_diff_dbfs"],
        "budget": PROPOSED["rms_diff_dbfs"],
        "detected": bool(detected),
        "verdict": ("CONTROL-OK (silent stub fails the output contract / "
                    "fidelity budgets)" if detected else
                    "CONTROL-BROKEN (silent stub NOT detected -- finding!)"),
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequence", default="sxt025-smoke-v1")
    args = ap.parse_args()
    os.makedirs(NC_DIR, exist_ok=True)

    results = []
    out_a, wet_a = nc_a(args.sequence)
    results.append(("NC-A", out_a))
    results.append(("NC-B", nc_b(args.sequence)))
    results.append(("NC-C", nc_c(args.sequence)))

    ok = True
    transcript = []
    for name, r in results:
        path = os.path.join(NC_DIR, f"{name.lower()}-{args.sequence}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2, sort_keys=True)
            f.write("\n")
        transcript.append(f"{name}: {r['verdict']}")
        ok = ok and r["detected"]
        print(f"{name}: {r['verdict']}")

    rtl = json.load(open(os.path.join(REPO, "reports", "sxt-025",
                                      "rtl-exactness.json")))
    mut = next((c for c in rtl["cases"] if c["case"] == "mutant"), None)
    if mut:
        transcript.append("NC-C-RTL (stale stub, committed mutant): "
                          f"{mut['verdict']}")
        ok = ok and (mut["verdict"].startswith("CONTROL-OK"))

    transcript.append(f"ALL CONTROLS {'HEALTHY' if ok else 'BROKEN'}")
    with open(os.path.join(REPO, "reports", "sxt-025",
                           "negative-controls.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(transcript) + "\n")
    for line in transcript:
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
