#!/usr/bin/env python3
"""Issue #160 probe: the int16 tail-shape-leg floor vs the int16 quantization
floor, and what raising the floor would cost.

Input to the SXT-017 pilot freeze (#12). This probe measures, it does not
decide, and it changes NO committed budget: the candidate floors below are
applied by patching the imported `compare_audio_reference.PROPOSED_TAIL` dict
*inside this process only*. `tools/compare_audio_reference.py` is not modified
by this probe, and the declared floor it ships stays -100.0 dBFS.

Legs
----
[1] Bus quantization table. For each bus the shared wet-path tail gate runs on
    (mono int16 full scale 32767; the stereo Q10.21 effect-slice gate, 1 LSB =
    2^-21; the sxt-024 reverb gate, 1 LSB = 2^-23), the level of one LSB RMS in
    dBFS, and the headroom of the declared `decay_curve_floor_dbfs` above it.
    For the int16 bus it also derives the level below which a +-1 LSB model
    difference ALONE can exceed `decay_curve_max_dev_db`, in two regimes:
      * incoherent (the error adds in power):
        20*log10(sqrt(1 + (e/r)^2)) > dev  =>  r < e / sqrt(10^(dev/10) - 1)
      * coherent worst case (the error adds in amplitude):
        20*log10(1 + e/r) > dev            =>  r < e / (10^(dev/20) - 1)
    with e = 1 LSB RMS. Between those levels and the declared floor, a window's
    graded level deviation is quantization, not tail shape.

[2] Window anatomy of the #93 `full-tail-within-budget` control (Koala 2 wet,
    the committed deterministic +-1 LSB dither over the first half of the
    declared tail -- the control finding F1 was measured on). Per graded window:
    reference level and the model's level deviation, so the record shows WHERE
    the 0.79 dB comes from rather than asserting it.

[3] Counterfactual floor sweep. Every int16 mono control the landed records
    grade (three #93 controls, four #111 controls) is re-graded at each
    candidate floor through the real comparator entry point, and its full
    verdict is compared with the status the landed record requires. A candidate
    floor that turns a required-FAIL control into a PASS would flip a landed
    negative control: that is the issue's stop/escalate condition, and this leg
    reports it instead of adopting the floor.

Claim scope
-----------
Comparator behaviour only. Every control "model" is built from a committed
reference render, so a PASS here is a tool self-test, never a
model-vs-reference result. Nothing here is a fidelity, RTL, preset-support, or
sound claim, and nothing here freezes a budget.

Usage:
  python3 tools/tail_shape_floor_probe.py [--legs 1,2,3] [--scratch-root DIR]
"""

import argparse
import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402

ART = os.path.join(REPO, "reports", "pilot-freeze-tail-shape-floor",
                   "artifacts")

# Candidate floors, dBFS. -100.0 is the DECLARED value that ships today; the
# others are the values a "raise the int16 floor out of the quantization
# region" decision would have to choose among (see leg 1 for where they come
# from).
CANDIDATE_FLOORS = [
    (-100.0, "declared today (PROPOSED_TAIL['decay_curve_floor_dbfs'])"),
    (-95.0, "midway between the declared floor and 1 int16 LSB RMS"),
    (-90.3, "1 int16 LSB RMS"),
    (-84.4, "incoherent +-1 LSB band edge (leg 1)"),
    (-80.0, "10 dB above 1 int16 LSB RMS"),
    (-72.0, "coherent worst-case +-1 LSB band edge (leg 1)"),
]

# Buses the shared tail gate is applied on, with full scale in each caller's
# LSB unit (the same value the gate passes to tail_decay_curve).
BUSES = [
    ("mono int16 (compare_audio_reference.py --path wet)",
     car.INT16_FULL_SCALE, "1 LSB = 1 int16 count"),
    ("stereo Q10.21 (compare_chorus_reference.py, compare_fx_reference.py)",
     1.0 / 2.0 ** -21, "1 LSB = 2^-21"),
    ("stereo Q9.23 (compare_reverb_model.py tail_gate)",
     1.0 / 2.0 ** -23, "1 LSB = 2^-23"),
]

KOALA = ("koala2", "seq-notes-coverage-v1")
BEHEMOTH = ("behemoth", "seq-notes-coverage-v1")


def emit(lines, s=""):
    lines.append(s)
    print(s)


def fixture(slug, seq, suffix):
    return os.path.join(REPO, "fixtures", "audio", slug, "%s%s" % (seq, suffix))


def write_i16(path, a, sr=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.asarray(a).astype("<i2").tobytes())


def dither(n, offset=0):
    """The #93 control's deterministic +-1 LSB pattern (tail_gate_checks.py)."""
    i = np.arange(offset, offset + n, dtype=np.int64)
    return ((i * 2654435761) % 3).astype(np.int64) - 1


def window_levels(x, win, full_scale):
    return np.array([car.rms_dbfs(float(np.sqrt((x[s:s + win]
                                                 * x[s:s + win]).mean())),
                                  full_scale)
                     for s in range(0, len(x), win)])


def region_of(slug, seq):
    return car.declared_tail_region(fixture(slug, seq, ".json"), "wet")


def run_comparator(ref_p, model_p, sidecar, out_json, floor):
    """Run the REAL comparator entry point with `floor` patched in-process.

    Returns (status, tail_check dict, budgets_all_ok). The patch is undone
    before returning; the committed tool file is never touched.
    """
    saved = car.PROPOSED_TAIL["decay_curve_floor_dbfs"]
    car.PROPOSED_TAIL["decay_curve_floor_dbfs"] = floor
    argv = sys.argv
    sys.argv = ["compare_audio_reference.py", "--path", "wet",
                "--sidecar", sidecar, "--ref", ref_p, "--model", model_p,
                "--json", out_json]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = car.main()
    finally:
        sys.argv = argv
        car.PROPOSED_TAIL["decay_curve_floor_dbfs"] = saved
    j = json.load(open(out_json)) if os.path.exists(out_json) else {}
    status = ("NO_VERDICT" if rc == 2
              else (j.get("verdict") or "").split(" ", 1)[0])
    budgets = j.get("proposed_budget_results") or {}
    return status, (j.get("tail_check") or {}), bool(budgets) and all(
        budgets.values())


# ---------------------------------------------------------------- leg 1 --

def leg1(lines):
    emit(lines, "=" * 74)
    emit(lines, "[1] bus quantization table vs the declared decay-curve floor")
    emit(lines, "=" * 74)
    floor = float(car.PROPOSED_TAIL["decay_curve_floor_dbfs"])
    dev = float(car.PROPOSED_TAIL["decay_curve_max_dev_db"])
    emit(lines, "  declared floor           : %.1f dBFS" % floor)
    emit(lines, "  declared max deviation   : %.2f dB" % dev)
    emit(lines)
    rows = []
    for name, full_scale, unit in BUSES:
        lsb_dbfs = 20.0 * np.log10(1.0 / full_scale)
        rows.append({"bus": name, "lsb_unit": unit,
                     "full_scale_in_lsb": full_scale,
                     "one_lsb_rms_dbfs": float(lsb_dbfs),
                     "floor_above_one_lsb_db": float(floor - lsb_dbfs)})
        emit(lines, "  %-62s 1 LSB RMS %8.1f dBFS   floor is %+7.1f dB "
                    "relative to it" % (name, lsb_dbfs, floor - lsb_dbfs))
    # +-1 LSB band edges on the int16 bus.
    incoherent = 1.0 / np.sqrt(10.0 ** (dev / 10.0) - 1.0)      # in LSB RMS
    coherent = 1.0 / (10.0 ** (dev / 20.0) - 1.0)               # in LSB RMS
    inc_dbfs = 20.0 * np.log10(incoherent / car.INT16_FULL_SCALE)
    coh_dbfs = 20.0 * np.log10(coherent / car.INT16_FULL_SCALE)
    emit(lines)
    emit(lines, "  int16 bus, a +-1 LSB model difference alone (e = 1 LSB RMS) "
                "exceeds the %.2f dB" % dev)
    emit(lines, "  budget for reference window levels below:")
    emit(lines, "    incoherent  (power addition)     : %6.1f dBFS "
                "(r = %.2f LSB)" % (inc_dbfs, incoherent))
    emit(lines, "    coherent    (amplitude addition) : %6.1f dBFS "
                "(r = %.2f LSB)" % (coh_dbfs, coherent))
    emit(lines)
    emit(lines, "  => on the int16 bus the graded band [%.1f, %.1f] dBFS is "
                "quantization-dominated;" % (floor, coh_dbfs))
    emit(lines, "     the declared floor sits %.1f dB BELOW one int16 LSB RMS, "
                "i.e. inside it."
         % (20.0 * np.log10(1.0 / car.INT16_FULL_SCALE) - floor))
    # Assertions: the record must reproduce the numbers finding F1 cites.
    ok = (abs(rows[0]["one_lsb_rms_dbfs"] + 90.3) < 0.1
          and rows[1]["floor_above_one_lsb_db"] >= 26.0
          and rows[2]["floor_above_one_lsb_db"] >= 26.0
          and floor < rows[0]["one_lsb_rms_dbfs"])
    emit(lines, "  leg 1: %s (F1's numbers reproduce: int16 1 LSB RMS "
                "-90.3 dBFS; float/s24 floors >= 26 dB above their LSB; the "
                "int16 floor is below its LSB)" % ("PASS" if ok else "FAIL"))
    return ok, {"status": "PASS" if ok else "FAIL", "declared_floor_dbfs": floor,
                "declared_max_dev_db": dev, "buses": rows,
                "int16_band_edge_incoherent_dbfs": float(inc_dbfs),
                "int16_band_edge_coherent_dbfs": float(coh_dbfs)}


# ---------------------------------------------------------------- leg 2 --

def leg2(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[2] where the 0.79 dB comes from: #93 full-tail-within-budget "
                "window anatomy")
    emit(lines, "=" * 74)
    slug, seq = KOALA
    region = region_of(slug, seq)
    off, length = region["tail_offset"], region["tail_frames"]
    ref_p, sc = fixture(slug, seq, "-wet.wav"), fixture(slug, seq, ".json")
    ref, sr = car.read_wav(ref_p)
    # The committed #93 control: +-1 LSB over the FIRST HALF of the declared
    # tail (tools/tail_gate_checks.py leg 2 control 1).
    mod = ref.astype(np.int64).copy()
    mod[off:off + length // 2] += dither(length // 2, off)
    p = os.path.join(scratch, "full-tail-within-budget.wav")
    write_i16(p, mod, sr)
    floor = float(car.PROPOSED_TAIL["decay_curve_floor_dbfs"])
    dev_budget = float(car.PROPOSED_TAIL["decay_curve_max_dev_db"])
    status, tc, budgets_ok = run_comparator(
        ref_p, p, sc, os.path.join(scratch, "full-tail-within-budget.json"),
        floor)
    dc = tc.get("tail_decay_curve") or {}
    win = int(dc.get("window_frames") or round(0.05 * sr))
    rl = window_levels(ref[off:off + length], win, car.INT16_FULL_SCALE)
    ml = window_levels(mod[off:off + length].astype(np.float64), win,
                       car.INT16_FULL_SCALE)
    graded = rl >= floor
    dev = np.abs(ml - rl)
    lsb_dbfs = 20.0 * np.log10(1.0 / car.INT16_FULL_SCALE)
    emit(lines, "  fixture %s %s, declared tail region [%d, %d), %d-frame "
                "windows" % (slug, seq, off, off + length, win))
    emit(lines, "  verdict %s (budgets all pass=%s, residual leg %s, shape leg "
                "%s)" % (status, budgets_ok,
                         "PASS" if tc.get("tail_rms_rel_ok") else "FAIL",
                         "PASS" if tc.get("tail_decay_curve_ok") else "FAIL"))
    emit(lines, "  graded windows %d of %d; worst deviation %.2f dB against "
                "the %.2f dB budget"
         % (int(graded.sum()), len(rl), float(dev[graded].max()), dev_budget))
    emit(lines)
    emit(lines, "  graded windows, ordered by reference level (lowest first):")
    emit(lines, "    %-6s %-12s %-12s %-10s %s" % ("window", "ref dBFS",
                                                   "model dBFS", "|dev| dB",
                                                   "dB above 1 LSB RMS"))
    order = [i for i in np.argsort(rl) if graded[i]]
    rows = []
    for i in order:
        rows.append({"window": int(i), "ref_dbfs": float(rl[i]),
                     "model_dbfs": float(ml[i]), "dev_db": float(dev[i]),
                     "db_above_one_lsb_rms": float(rl[i] - lsb_dbfs)})
        emit(lines, "    %-6d %-12.1f %-12.1f %-10.2f %.1f"
             % (i, rl[i], ml[i], dev[i], rl[i] - lsb_dbfs))
    # The claim under test: the deviation is concentrated in the windows
    # closest to 1 LSB RMS, i.e. it is quantization and not tail shape.
    worst = int(order[np.argmax([dev[i] for i in order])]) if order else None
    big = [int(i) for i in order if dev[i] > dev_budget / 4.0]
    highest_big = max((rl[i] for i in big), default=None)
    emit(lines)
    emit(lines, "  windows deviating by more than a quarter of the budget "
                "(%.2f dB): %s" % (dev_budget / 4.0,
                                   ", ".join(str(i) for i in big) or "none"))
    if highest_big is not None:
        emit(lines, "  the highest-level such window sits at %.1f dBFS = "
                    "%.1f dB above 1 int16 LSB RMS"
             % (highest_big, highest_big - lsb_dbfs))
    ok = (abs(float(dev[graded].max()) - 0.79) < 0.02
          and status == "PASS"
          and worst is not None
          and highest_big is not None and highest_big < -72.0)
    emit(lines, "  leg 2: %s (F1 reproduces: control PASSes, worst graded "
                "deviation 0.79 dB, and every window above a quarter of the "
                "budget lies below the coherent band edge)"
         % ("PASS" if ok else "FAIL"))
    return ok, {"status": "PASS" if ok else "FAIL", "verdict": status,
                "floor_dbfs": floor, "window_frames": win,
                "graded_windows": int(graded.sum()),
                "total_windows": int(len(rl)),
                "worst_graded_dev_db": float(dev[graded].max()),
                "worst_graded_window": worst,
                "windows_over_quarter_budget": big,
                "highest_such_window_ref_dbfs": highest_big,
                "graded_window_rows": rows}


# ---------------------------------------------------------------- leg 3 --

def build_controls(scratch):
    """The int16 mono controls the landed #93 / #111 records grade."""
    out = []
    for (slug, seq), specs in (
            (KOALA, (("#93 full-tail-within-budget", "dither-half", "PASS"),
                     ("#93 drop-full-tail", "zero-all", "FAIL"),
                     ("#93 tail-decays-too-fast", "fast-0.4", "FAIL"),
                     ("#111 zero-late-tail-from-44%", 0.44, "FAIL"))),
            (BEHEMOTH, (("#111 baseline (self)", None, "PASS"),
                        ("#111 zero-late-tail-from-40%", 0.40, "FAIL"),
                        ("#111 zero-late-tail-from-60%", 0.60, "FAIL"),
                        ("#111 zero-late-tail-from-95%", 0.95, "FAIL")))):
        region = region_of(slug, seq)
        off, length = region["tail_offset"], region["tail_frames"]
        ref_p, sc = fixture(slug, seq, "-wet.wav"), fixture(slug, seq, ".json")
        ref, sr = car.read_wav(ref_p)
        for name, how, required in specs:
            m = ref.astype(np.int64).copy()
            if how == "dither-half":
                m[off:off + length // 2] += dither(length // 2, off)
            elif how == "zero-all":
                m[off:off + length] = 0
            elif how == "fast-0.4":
                t = np.arange(length) / float(sr)
                m[off:off + length] = np.round(ref[off:off + length]
                                               * np.exp(-t / 0.4))
            elif isinstance(how, float):
                m[off + int(length * how):off + length] = 0
            tag = ("%s-%s" % (slug, name)).replace(" ", "-").replace("%", "")
            tag = tag.replace("#", "").replace("(", "").replace(")", "")
            p = os.path.join(scratch, "%s.wav" % tag)
            write_i16(p, m, sr)
            out.append({"control": "%s/%s" % (slug, name), "tag": tag,
                        "ref": ref_p, "sidecar": sc, "model": p,
                        "required": required})
    return out


def leg3(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[3] counterfactual floor sweep over the landed int16 mono "
                "controls")
    emit(lines, "=" * 74)
    emit(lines, "  Each control is re-graded through compare_audio_reference."
                "main() with ONLY")
    emit(lines, "  decay_curve_floor_dbfs patched in-process. Required statuses"
                " are the landed ones")
    emit(lines, "  (reports/shared-comparator-tail-gate/, "
                "reports/tail-shape-leg/).")
    emit(lines)
    controls = build_controls(scratch)
    rows = []
    ok = True
    flips = {}
    for floor, why in CANDIDATE_FLOORS:
        emit(lines, "  floor %.1f dBFS -- %s" % (floor, why))
        broken = []
        for c in controls:
            status, tc, budgets_ok = run_comparator(
                c["ref"], c["model"], c["sidecar"],
                os.path.join(scratch, "%s.%.1f.json" % (c["tag"], floor)),
                floor)
            dc = tc.get("tail_decay_curve") or {}
            good = status == c["required"]
            if not good:
                broken.append(c["control"])
            rows.append({"floor_dbfs": floor, "control": c["control"],
                         "required": c["required"], "observed": status,
                         "as_required": good,
                         "budgets_all_ok": budgets_ok,
                         "tail_rms_rel_ok": tc.get("tail_rms_rel_ok"),
                         "tail_decay_curve_ok": tc.get("tail_decay_curve_ok"),
                         "graded_windows": dc.get("graded_windows"),
                         "total_windows": dc.get("total_windows"),
                         "max_dev_db": dc.get("max_dev_db")})
            emit(lines, "    %-38s required %-4s observed %-10s | shape leg %s "
                        "(%s graded windows, worst dev %s dB) | %s"
                 % (c["control"], c["required"], status,
                    "PASS" if tc.get("tail_decay_curve_ok") else "FAIL",
                    dc.get("graded_windows"),
                    "n/a" if dc.get("max_dev_db") is None
                    else "%.2f" % dc["max_dev_db"],
                    "as landed" if good else "FLIPPED vs the landed record"))
        flips[floor] = broken
        emit(lines, "    => %s" % ("every landed control behaves as recorded"
                                   if not broken else
                                   "FLIPS: %s" % ", ".join(broken)))
        emit(lines)
        if floor == float(car.PROPOSED_TAIL["decay_curve_floor_dbfs"]):
            ok &= not broken
    raised = [f for f, _ in CANDIDATE_FLOORS
              if f > float(car.PROPOSED_TAIL["decay_curve_floor_dbfs"])]
    breaking = [f for f in raised if flips[f]]
    emit(lines, "  declared floor (%.1f dBFS): %d/%d controls as landed"
         % (car.PROPOSED_TAIL["decay_curve_floor_dbfs"],
            sum(1 for r in rows
                if r["floor_dbfs"] == car.PROPOSED_TAIL[
                    "decay_curve_floor_dbfs"] and r["as_required"]),
            len(controls)))
    emit(lines, "  raised candidate floors that flip a landed control: %s"
         % (", ".join("%.1f" % f for f in breaking) or "none"))
    # The leg is a real test in both directions: it FAILs if the declared floor
    # does not reproduce the landed statuses, AND it FAILs if no raised floor
    # inside the quantization band flips anything (which would remove this
    # issue's stop/escalate argument and require the decision to be re-argued).
    ok &= bool(breaking)
    emit(lines, "  leg 3: %s" % ("PASS" if ok else "FAIL"))
    return ok, {"status": "PASS" if ok else "FAIL", "rows": rows,
                "flips_by_floor": {"%.1f" % f: v for f, v in flips.items()},
                "raised_floors_that_flip_a_landed_control":
                    ["%.1f" % f for f in breaking]}


# ----------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch-root", default="/tmp/sxt-tail-shape-floor")
    ap.add_argument("--legs", default="1,2,3")
    args = ap.parse_args()
    legs = {int(x) for x in args.legs.split(",") if x.strip()}
    scratch = args.scratch_root
    if os.path.exists(scratch):
        shutil.rmtree(scratch)
    os.makedirs(scratch)
    os.makedirs(ART, exist_ok=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, cwd=REPO).stdout.strip()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    lines = []
    emit(lines, "tail-shape-leg floor probe (issue #160) -- SXT-017 pilot-"
                "freeze input")
    emit(lines, "repo HEAD %s   numpy %s   %s" % (head[:12], np.__version__,
                                                  stamp))
    emit(lines, "shipped budget (unmodified): %s"
         % json.dumps(car.PROPOSED_TAIL, sort_keys=True))
    emit(lines, "claim scope: comparator behaviour only; no fidelity, RTL, "
                "support or sound claim; no budget frozen.")
    emit(lines)
    summary = {"head": head, "timestamp": stamp, "numpy": np.__version__,
               "shipped_proposed_tail": dict(car.PROPOSED_TAIL), "legs": {}}
    overall = True
    for n, fn in ((1, lambda: leg1(lines)),
                  (2, lambda: leg2(lines, scratch)),
                  (3, lambda: leg3(lines, scratch))):
        if n not in legs:
            summary["legs"][str(n)] = {"status": "NOT_RUN"}
            overall = False
            continue
        good, rep = fn()
        summary["legs"][str(n)] = rep
        overall &= good
        emit(lines)
    summary["overall"] = "PASS" if overall else "FAIL"
    emit(lines, "OVERALL: %s" % summary["overall"])
    with open(os.path.join(ART, "floor-probe.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(ART, "floor-probe.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
