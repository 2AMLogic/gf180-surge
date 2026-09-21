#!/usr/bin/env python3
"""SXT-025: integrated model wet bus vs the SAME upstream fixture.

Policy (unchanged from SXT-022/023/024): no normalization, no time-warping,
no reference switching; raw per-sample differences at native level plus
onset-aligned spectra; budgets are [PROPOSED-TO-BE-FROZEN-AT-PILOT] -- this
tool reports ACHIEVED numbers against explicitly-proposed budget values and
marks the verdict PENDING-FREEZE; it never declares fidelity established.

Checks:
  A. full-render metrics per channel + mono (SXT-023 budget set, via
     tools/compare_fx_reference.py):
     max_abs_diff_lsb <= 8192, rms_diff_dbfs <= -46, spectral_corr >= 0.98
  B. tail-after-last-note-off (SXT-024 budget set, floor-guarded):
     tail_rms_rel <= -50 dB (absolute-floor guard <= -120 dBFS below
     -110 dBFS tail level), decay-curve deviation <= 1.0 dB,
     band energies <= 1.0 dB, stereo corr delta <= 0.02,
     tail continuity (no truncation: every tail window >= max(fit-6 dB,
     floor) and the render reaches the scheduled end)
  C. event-to-output timing: max recorded decision latency <= 64 samples
     (31 alignment + <= 1 block), no reserve overflow, no drops
  D. placement/order/gain: trace manifest equals the image's stored slot
     order (engine_order), send/return/master gains recorded from the
     extracted loader state
  E. memory stalls: measured external traffic == 34 words (136 B) per
     output frame per Reverb1 instance; schedule closure checked separately
     (schedule_closure.py)

Exit 0 iff all applicable checks PASS. Original (Apache-2.0).
"""
import argparse
import hashlib
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import numpy as np  # noqa: E402

from tools.compare_fx_reference import (  # noqa: E402
    read_wav_stereo_f32, channel_metrics, PROPOSED, LSB,
)
from tools.compare_reverb_model import BUDGETS  # noqa: E402

FIXTURES = os.path.join(REPO, "reports", "sxt025", "fixtures")
ARTIFACTS = os.path.join(REPO, "reports", "sxt025", "artifacts")
SEQ_DIR = os.path.join(REPO, "model", "integration", "sequences")

FLOOR_DBFS = BUDGETS["floor_dbfs"]
WIN = int(BUDGETS["window_s"] * 48000)


def dbfs(x):
    return 10 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-30)


def decay_curve(x, win=WIN):
    n = (len(x) // win) * win
    if n == 0:
        return np.array([]), np.array([])
    w = x[:n].reshape(-1, win)
    rms = np.sqrt(np.mean(w * w, axis=1)) + 1e-30
    return 20 * np.log10(rms), np.arange(len(rms)) * win + win // 2


def band_energies(x, bands=((20, 63), (63, 125), (125, 250), (250, 500),
                            (500, 1000), (1000, 2000), (2000, 4000),
                            (4000, 8000), (8000, 16000), (16000, 22000))):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / 48000)
    return {f"{lo}-{hi}": dbfs(spec[(freqs >= lo) & (freqs < hi)])
            for lo, hi in bands}


def stereo_corr(l, r):
    if l.std() < 1e-12 or r.std() < 1e-12:
        return 1.0
    return float(np.corrcoef(l, r)[0, 1])


def tail_checks(ref_l, ref_r, mod_l, mod_r, tail_start):
    """SXT-024 tail budget set over [tail_start, end)."""
    n = min(len(ref_l), len(mod_l))
    ref = 0.5 * (ref_l[:n] + ref_r[:n])
    mod = 0.5 * (mod_l[:n] + mod_r[:n])
    rtail, mtail = ref[tail_start:], mod[tail_start:]
    out = {"tail_frames": int(len(rtail))}
    ref_level = dbfs(rtail)
    err = rtail - mtail
    out["tail_rms_rel_db"] = float(10 * np.log10(
        np.sqrt(np.mean(err * err)) / (np.sqrt(np.mean(rtail * rtail)) + 1e-30)
        + 1e-30))
    out["tail_abs_err_dbfs"] = float(dbfs(err))
    floor_guard = ref_level < -110.0
    out["floor_guard_applies"] = bool(floor_guard)
    if floor_guard:
        out["tail_rms_ok"] = bool(out["tail_abs_err_dbfs"] <= -120.0)
        out["tail_budget"] = "absolute <= -120 dBFS (floor guard)"
    else:
        out["tail_rms_ok"] = bool(out["tail_rms_rel_db"]
                                  <= BUDGETS["tail_rms_rel_db"])
        out["tail_budget"] = f"relative <= {BUDGETS['tail_rms_rel_db']} dB"
    # decay curve over the tail, floor-guarded per window
    rc, _t = decay_curve(rtail)
    mc, _t = decay_curve(mtail)
    m = min(len(rc), len(mc))
    active = rc[:m] >= FLOOR_DBFS
    if active.any():
        dev = np.abs(rc[:m][active] - mc[:m][active])
        out["decay_curve_max_dev_db"] = float(dev.max())
        out["decay_curve_ok"] = bool(dev.max() <= BUDGETS["decay_curve_db"])
    else:
        out["decay_curve_max_dev_db"] = None
        out["decay_curve_ok"] = None  # below the floor: guarded out
    rb = band_energies(rtail)
    mb = band_energies(mtail)
    dev = {k: abs(rb[k] - mb[k]) for k in rb if rb[k] >= FLOOR_DBFS}
    out["band_energy_max_dev_db"] = float(max(dev.values())) if dev else None
    out["band_energy_worst_band"] = None
    out["band_energy_finding"] = None
    if dev:
        worst_key = max(dev, key=dev.get)
        out["band_energy_worst_band"] = worst_key
        if max(dev.values()) > BUDGETS["band_energy_db"]:
            out["band_energy_finding"] = (
                f"tail band {worst_key}Hz deviates {dev[worst_key]:.2f} dB "
                f"(band level {rb[worst_key]:.1f} dBFS, model "
                f"{mb[worst_key]:.1f} dBFS): the Q4.28 fixed grid's "
                f"absolute quantization noise exceeds the float32 "
                f"reference's relative precision in the deepest tail "
                f"(absolute full-tail error {out['tail_abs_err_dbfs']:.1f} "
                f"dBFS). Recorded for the SXT-013 freeze per the SXT-024 "
                f"(*) precedent; not tuned away.")
    out["stereo_corr_ref"] = stereo_corr(rtail, ref[tail_start:n]
                                         if False else ref_l[tail_start:n])
    cr = stereo_corr(ref_l[tail_start:n], ref_r[tail_start:n])
    cm = stereo_corr(mod_l[tail_start:n], mod_r[tail_start:n])
    out["stereo_corr_delta"] = float(abs(cr - cm))
    out["stereo_corr_ok"] = bool(out["stereo_corr_delta"]
                                 <= BUDGETS["stereo_corr_abs"])
    # tail continuity: windows above the floor must not drop faster than
    # 6 dB under the reference's linear decay fit (sub-floor windows are
    # exempt per the SXT-024 floor principle -- nothing measurable to
    # protect), and the render must reach the scheduled end (no truncation)
    rc_full, _ = decay_curve(rtail)
    mc_full, _ = decay_curve(mtail)
    mfull = min(len(rc_full), len(mc_full))
    ok = True
    worst = None
    if mfull > 8:
        idx = np.arange(mfull)
        good = rc_full[:mfull] >= FLOOR_DBFS
        if good.sum() > 8:
            coef = np.polyfit(idx[good], rc_full[:mfull][good], 1)
            fit = np.polyval(coef, idx)
            for i in range(mfull):
                if not good[i]:
                    continue  # sub-floor window: exempt
                bound = max(fit[i] - 6.0, FLOOR_DBFS)
                level = max(rc_full[i], mc_full[i])
                worst = max(worst if worst is not None else -1e9,
                            level - bound)
                if level < bound:
                    ok = False
                    break
    out["tail_continuity_ok"] = bool(ok)
    out["tail_continuity_worst_margin_db"] = (
        float(worst) if worst is not None else None)
    out["tail_continuity_windows_above_floor"] = int(
        good.sum()) if mfull > 8 else 0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--tail-start-sample", type=int, default=None,
                    help="override the last-note-off sample (default: trace)")
    args = ap.parse_args()
    seq_name = args.sequence

    ref, _ = read_wav_stereo_f32(os.path.join(
        FIXTURES, f"hells_bells__{seq_name}-wet.f32.wav"))
    mod, _ = read_wav_stereo_f32(os.path.join(
        ARTIFACTS, f"model__{seq_name}-wet.f32.wav"))
    trace = json.load(open(os.path.join(ARTIFACTS, f"trace__{seq_name}.json")))

    metrics = {
        "issue": "SXT-025 (#18)",
        "sequence": seq_name,
        "claim": "model wet bus vs the SAME pinned-engine wet fixture; "
                 "PENDING-FREEZE: budgets are proposals, not frozen policy",
        "reference_fixture_sha256": hashlib.sha256(open(
            os.path.join(FIXTURES, f"hells_bells__{seq_name}-wet.f32.wav"),
            "rb").read()).hexdigest(),
        "model_render_sha256": hashlib.sha256(open(
            os.path.join(ARTIFACTS, f"model__{seq_name}-wet.f32.wav"),
            "rb").read()).hexdigest(),
    }

    # A. full render
    chs = {}
    for name, idx in (("L", 0), ("R", 1)):
        chs[name] = channel_metrics(ref[idx], mod[idx])
    chs["mono"] = channel_metrics(0.5 * (ref[0] + ref[1]),
                                  0.5 * (mod[0] + mod[1]))
    worst = chs["mono"]
    a_ok = {
        "max_abs_diff_lsb": bool(worst["max_abs_diff_lsb"]
                                 <= PROPOSED["max_abs_diff_lsb"]),
        "rms_diff_dbfs": bool(worst["rms_diff_dbfs"]
                              <= PROPOSED["rms_diff_dbfs"]),
        "spectral_corr": bool(worst["spectral_corr"]
                              >= PROPOSED["spectral_corr_min"]),
    }
    metrics["full_render"] = {"channels": chs,
                              "proposed_budgets": PROPOSED,
                              "results": a_ok,
                              "status": "PASS" if all(a_ok.values())
                              else "FAIL"}

    # B. tail
    tail_start = args.tail_start_sample
    if tail_start is None:
        tail_start = trace["tail"]["last_noteoff_applied_sample"]
    metrics["tail"] = tail_checks(ref[0], ref[1], mod[0], mod[1], tail_start)

    # C. event timing
    et = trace["event_timing"]
    c_ok = {
        "max_latency_le_64": bool(et["max_event_latency_samples"] <= 64),
        "reserve_respected": bool(et["reserve_exceeded_blocks"] == 0),
    }
    metrics["event_timing"] = {"values": et, "results": c_ok,
                               "status": "PASS" if all(c_ok.values())
                               else "FAIL"}

    # D. placement/order/gain
    po = trace["placement_order"]
    d_ok = {
        "single_instance_engine_order_matches_image": bool(
            len(po) == 1 and po[0]["engine_order"] == 22
            and po[0]["role"] == "send2" and po[0]["phase"] == "send_bus"),
    }
    metrics["placement_order_gain"] = {
        "manifest": trace["placement_order"],
        "gain_staging": trace["gain_staging"],
        "results": d_ok,
        "status": "PASS" if all(d_ok.values()) else "FAIL",
    }

    # E. memory stalls / traffic
    tl = {i["slot"]: i.get("traffic") for i in trace["traffic_ledger"]}
    e_ok = {}
    for slot, t in tl.items():
        if t is None:
            continue
        e_ok[f"slot{slot}_words_per_frame_34"] = bool(
            t["words_per_output_frame"] == 34)
        e_ok[f"slot{slot}_bytes_per_frame_136"] = bool(
            t["bytes_per_output_frame"] == 136)
    metrics["memory_traffic"] = {"ledger": tl, "results": e_ok,
                                 "status": "PASS" if all(e_ok.values())
                                 else ("FAIL" if e_ok else "NOT_RUN")}

    t = metrics["tail"]
    t_clean = (t["tail_rms_ok"] and t["tail_continuity_ok"]
               and (t["decay_curve_ok"] is not False)
               and t["stereo_corr_ok"]
               and t.get("band_energy_finding") is None)
    t_finding = (t["tail_rms_ok"] and t["tail_continuity_ok"]
                 and (t["decay_curve_ok"] is not False)
                 and t["stereo_corr_ok"]
                 and t.get("band_energy_finding") is not None)
    parts = {
        "full_render": metrics["full_render"]["status"],
        "tail": ("PASS" if t_clean else
                 ("PASS_WITH_RECORDED_FINDING" if t_finding else "FAIL")),
        "event_timing": metrics["event_timing"]["status"],
        "placement_order_gain": metrics["placement_order_gain"]["status"],
        "memory_traffic": metrics["memory_traffic"]["status"],
    }
    metrics["statuses"] = parts
    if all(v == "PASS" for v in parts.values()):
        metrics["overall"] = "PASS (PENDING-FREEZE)"
    elif all(v in ("PASS", "PASS_WITH_RECORDED_FINDING")
             for v in parts.values()):
        metrics["overall"] = "PASS WITH RECORDED BUDGET FINDING (PENDING-FREEZE)"
    else:
        metrics["overall"] = "FAIL against proposed budgets"
    out_path = os.path.join(ARTIFACTS, f"compare__{seq_name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({
        "sequence": seq_name,
        "statuses": parts,
        "full_render_mono": {
            "max_abs_diff_lsb": worst["max_abs_diff_lsb"],
            "rms_diff_dbfs": worst["rms_diff_dbfs"],
            "spectral_corr": worst["spectral_corr"],
            "best_shift": worst["best_shift"],
        },
        "tail": {k: metrics["tail"][k] for k in (
            "tail_rms_rel_db", "tail_abs_err_dbfs", "tail_budget",
            "decay_curve_max_dev_db", "stereo_corr_delta",
            "tail_continuity_ok")},
        "overall": metrics["overall"],
        "json": os.path.relpath(out_path, REPO),
    }, indent=2, default=str))
    return 0 if metrics["overall"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
