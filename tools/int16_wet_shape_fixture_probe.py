#!/usr/bin/env python3
"""Issue #187 probe: which committed int16 wet fixture can carry the tail-SHAPE
leg WITHOUT grading inside the int16 quantization-dominated band, and does the
late-tail control set survive there.

Input to the SXT-017 pilot freeze (#12); continuation of issue #160 /
`decision-records/0016` option **F-E**, fixture-side arm. This probe measures,
it does not decide, and it changes NO committed budget: candidate floors below
are applied by patching the imported `compare_audio_reference.PROPOSED_TAIL`
dict *inside this process only*. `tools/compare_audio_reference.py` is not
modified, and the declared floor it ships stays -100.0 dBFS, the declared
deviation budget 1.0 dB.

Background (measured in #160, reproduced by leg 3 here)
-------------------------------------------------------
On the mono int16 wet bus (full scale 32767) one LSB RMS is -90.3 dBFS, so the
declared shape-leg floor sits 9.7 dB BELOW one LSB and the graded band
[-100.0, -72.0] dBFS is quantization-dominated. On
`fixtures/audio/koala2/seq-notes-coverage-v1-wet.wav` the landed #111 negative
control `mono/koala2/zero-late-tail-from-44%` fails through exactly one graded
window at -81.9 dBFS -- INSIDE that band -- so every floor that clears the band
disables the control. The comparator is correct but fixture-limited there.

Legs
----
[1] Eligibility survey of every committed int16 wet fixture. For each fixture's
    DECLARED tail region: window levels, graded/total windows at the declared
    floor, the lowest graded window level, and the worst-case coherent +-1 LSB
    "spend" that window would suffer,
        spend_db = 20*log10(1 + 1/r_lsb),   r_lsb = lowest graded window RMS
    as a fraction of `decay_curve_max_dev_db`. A fixture is ELIGIBLE as an
    int16 wet SHAPE-GRADING fixture when both hold:
      (i)  coverage: every window of the declared tail region is graded at the
           declared floor (graded == total), so the leg has no coverage gap;
      (ii) quantization headroom: spend_db <= HEADROOM_FRACTION *
           decay_curve_max_dev_db (0.10, i.e. +-1 LSB alone can spend at most
           10% of the declared deviation budget in the WORST window).
    (ii) is strictly stronger than "no graded window inside the declared band":
    the level it requires (-51.6 dBFS for the shipped constants) is 20.5 dB
    above the band's upper edge. Neither criterion is a grading budget -- they
    select a fixture; no verdict is computed from them.

[2] The #111 mono late-tail controls re-derived on the DESIGNATED fixture, plus
    the single-window control that re-derives `mono/koala2/zero-late-tail-from-
    44%` (whose one defect window sat inside the band), plus the #93 +-1 LSB
    dither control. Every control is graded through the real comparator entry
    point at the DECLARED floor. For each required-FAIL control the probe also
    locates every over-budget window and checks that ALL of them lie above the
    band -- a control that fails only inside the quantization regime would be
    exactly the defect this issue exists to remove.

[3] The floor-insensitivity pair, which is this issue's failure control:
      * on the DESIGNATED fixture, raising the floor to the band edges
        (-84.4, -80.0, -72.0 dBFS) must change NO control status and must not
        reduce the graded-window count: the fixture no longer grades inside its
        own quantization noise;
      * on the OLD fixture (koala2), `zero-late-tail-from-44%` must STILL flip
        FAIL -> PASS at -80.0 and -72.0 dBFS. That is #160's live control and
        the reason the fixture changed. If it ever stops firing this leg FAILs
        rather than reporting success.

Claim scope
-----------
Comparator and fixture-selection behaviour only. Every control "model" is
derived from a committed reference render, so a PASS here is a tool self-test,
never a model-vs-reference result. Nothing here is a fidelity, RTL,
preset-support, coverage, or sound claim, and nothing here freezes a budget:
the tail-shape values remain [PROPOSED-TO-BE-FROZEN-AT-PILOT].

Usage:
  python3 tools/int16_wet_shape_fixture_probe.py [--legs 1,2,3]
      [--scratch-root DIR]
"""

import argparse
import contextlib
import datetime
import glob
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

ART = os.path.join(REPO, "reports", "int16-wet-shape-fixture", "artifacts")

# Fixture-eligibility criterion (ii): the worst graded window of an eligible
# fixture may lose at most this FRACTION of the declared deviation budget to a
# worst-case coherent +-1 LSB model difference. This selects a FIXTURE; it is
# not a grading budget and no verdict is derived from it.
HEADROOM_FRACTION = 0.10

# The fixture designated by decision-records/0017 (#187) as the int16 wet
# shape-grading fixture, and the fixture #160's conflict was measured on.
DESIGNATED = ("behemoth", "seq-notes-holds-v1")
OLD_FIXTURE = ("koala2", "seq-notes-coverage-v1")

# Floors probed in leg 3. -100.0 is the DECLARED value that ships; the others
# are the band edges from #160 leg 1.
CANDIDATE_FLOORS = [
    (-100.0, "declared today (PROPOSED_TAIL['decay_curve_floor_dbfs'])"),
    (-84.4, "incoherent +-1 LSB band edge (#160 leg 1)"),
    (-80.0, "10 dB above 1 int16 LSB RMS"),
    (-72.0, "coherent worst-case +-1 LSB band edge (#160 leg 1)"),
]

# The #111 mono late-tail controls, re-derived on the designated fixture, plus
# the single-window control that re-derives mono/koala2/zero-late-tail-from-44%
# and the #93 +-1 LSB dither control.
#   (name, how, required status, is-a-control)
CONTROL_SPECS = [
    ("baseline", None, "PASS", True),
    ("zero-late-tail-from-40%", 0.40, "FAIL", True),
    ("zero-late-tail-from-60%", 0.60, "FAIL", True),
    ("zero-late-tail-from-95%", 0.95, "FAIL", True),
    ("zero-late-tail-from-98%", 0.98, "FAIL", True),
    ("late-tail-decays-too-fast-from-40%", "fast-0.2", "FAIL", True),
    ("dither-first-half", "dither-half", "PASS", True),
]


def emit(lines, s=""):
    lines.append(s)
    print(s)


def fixture_paths(slug, seq):
    d = os.path.join(REPO, "fixtures", "audio", slug)
    return (os.path.join(d, "%s-wet.wav" % seq), os.path.join(d, "%s.json" % seq))


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


def window_levels(x, win):
    """Per-window RMS level in dBFS on the int16 bus."""
    return np.array([car.rms_dbfs(float(np.sqrt((x[s:s + win]
                                                 * x[s:s + win]).mean())),
                                  car.INT16_FULL_SCALE)
                     for s in range(0, len(x), win)])


def band_edges():
    """(1 LSB RMS, incoherent edge, coherent edge) in dBFS, from the shipped
    constants -- the same arithmetic as #160 leg 1."""
    dev = float(car.PROPOSED_TAIL["decay_curve_max_dev_db"])
    one_lsb = 20.0 * np.log10(1.0 / car.INT16_FULL_SCALE)
    inc = 20.0 * np.log10((1.0 / np.sqrt(10.0 ** (dev / 10.0) - 1.0))
                          / car.INT16_FULL_SCALE)
    coh = 20.0 * np.log10((1.0 / (10.0 ** (dev / 20.0) - 1.0))
                          / car.INT16_FULL_SCALE)
    return float(one_lsb), float(inc), float(coh)


def coherent_spend_db(level_dbfs):
    """Worst-case coherent +-1 LSB level error, dB, at an int16 window level."""
    r = 10.0 ** (level_dbfs / 20.0) * car.INT16_FULL_SCALE
    if r <= 0:
        return float("inf")
    return float(20.0 * np.log10(1.0 + 1.0 / r))


def eligibility_level_dbfs():
    """Lowest graded-window level criterion (ii) admits, dBFS."""
    dev = float(car.PROPOSED_TAIL["decay_curve_max_dev_db"])
    r = 1.0 / (10.0 ** (HEADROOM_FRACTION * dev / 20.0) - 1.0)
    return float(20.0 * np.log10(r / car.INT16_FULL_SCALE))


def survey_fixture(wet_path, sidecar):
    """Declared-tail window statistics for one committed int16 wet fixture."""
    region = car.declared_tail_region(sidecar, "wet")
    ref, sr = car.read_wav(wet_path)
    off, length = region["tail_offset"], region["tail_frames"]
    win = int(round(float(car.PROPOSED_TAIL["decay_curve_window_s"]) * sr))
    floor = float(car.PROPOSED_TAIL["decay_curve_floor_dbfs"])
    dev = float(car.PROPOSED_TAIL["decay_curve_max_dev_db"])
    lv = window_levels(ref[off:off + length], win)
    graded = lv >= floor
    _, _, coh = band_edges()
    lowest = float(lv[graded].min()) if graded.any() else None
    spend = coherent_spend_db(lowest) if lowest is not None else None
    covered = bool(graded.all())
    headroom_ok = bool(spend is not None and spend <= HEADROOM_FRACTION * dev)
    reasons = []
    if not covered:
        reasons.append("coverage gap: %d of %d windows below the declared floor"
                       % (int((~graded).sum()), int(len(lv))))
    if not headroom_ok:
        reasons.append("worst graded window spends %.2f dB of the %.2f dB "
                       "budget on a +-1 LSB difference (> %.2f dB)"
                       % (spend if spend is not None else float("nan"), dev,
                          HEADROOM_FRACTION * dev))
    return {
        "fixture": os.path.relpath(wet_path, REPO),
        "tail_s": region["tail_s"],
        "tail_offset": off,
        "tail_frames": length,
        "window_frames": win,
        "total_windows": int(len(lv)),
        "graded_windows": int(graded.sum()),
        "lowest_graded_dbfs": lowest,
        "windows_in_declared_band": int((graded & (lv < coh)).sum()),
        "coherent_spend_db": spend,
        "coherent_spend_fraction_of_budget": (None if spend is None
                                              else spend / dev),
        "full_coverage": covered,
        "headroom_ok": headroom_ok,
        "eligible": bool(covered and headroom_ok),
        "ineligible_because": reasons,
    }


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


def build_control(ref, off, length, how, sr):
    """One control model render, derived from the committed reference."""
    m = ref.astype(np.int64).copy()
    if how is None:
        return m
    if how == "dither-half":
        m[off:off + length // 2] += dither(length // 2, off)
    elif how == "fast-0.2":
        s0 = off + int(length * 0.40)
        t = np.arange(off + length - s0) / float(sr)
        m[s0:off + length] = np.round(ref[s0:off + length] * np.exp(-t / 0.2))
    else:
        m[off + int(length * float(how)):off + length] = 0
    return m


def over_budget_windows(ref, mod, off, length, win, floor, max_dev):
    """Graded windows whose level deviation exceeds the budget, with levels."""
    rl = window_levels(ref[off:off + length], win)
    ml = window_levels(mod[off:off + length].astype(np.float64), win)
    graded = rl >= floor
    dev = np.abs(ml - rl)
    idx = [int(i) for i in np.flatnonzero(graded & (dev > max_dev))]
    return rl, ml, dev, graded, idx


def make_controls(scratch, slug, seq):
    """Materialize every control render for one fixture. Returns (ctx, rows)."""
    ref_p, sc = fixture_paths(slug, seq)
    region = car.declared_tail_region(sc, "wet")
    off, length = region["tail_offset"], region["tail_frames"]
    ref, sr = car.read_wav(ref_p)
    win = int(round(float(car.PROPOSED_TAIL["decay_curve_window_s"]) * sr))
    out = []
    for name, how, required, is_control in CONTROL_SPECS:
        mod = build_control(ref, off, length, how, sr)
        tag = ("%s-%s-%s" % (slug, seq, name)).replace("%", "")
        p = os.path.join(scratch, "%s.wav" % tag)
        write_i16(p, mod, sr)
        # The control name carries the SEQUENCE as well as the preset: the
        # landed #111 mono Behemoth controls have the same suffixes on
        # seq-notes-coverage-v1, and the two sets must never be confused.
        out.append({"control": "mono/%s/%s/%s" % (slug, seq, name), "tag": tag,
                    "ref": ref_p, "sidecar": sc, "model": p, "mod": mod,
                    "required": required, "is_control": is_control})
    ctx = {"slug": slug, "seq": seq, "ref": ref, "ref_path": ref_p,
           "sidecar": sc, "off": off, "length": length, "win": win, "sr": sr}
    return ctx, out


# ---------------------------------------------------------------- leg 1 --

def leg1(lines):
    emit(lines, "=" * 74)
    emit(lines, "[1] int16 wet fixture eligibility survey (shape-grading "
                "fixture selection)")
    emit(lines, "=" * 74)
    floor = float(car.PROPOSED_TAIL["decay_curve_floor_dbfs"])
    dev = float(car.PROPOSED_TAIL["decay_curve_max_dev_db"])
    one_lsb, inc, coh = band_edges()
    emit(lines, "  declared floor %.1f dBFS | declared max deviation %.2f dB"
         % (floor, dev))
    emit(lines, "  1 int16 LSB RMS %.1f dBFS | +-1 LSB band edges: incoherent "
                "%.1f dBFS, coherent %.1f dBFS" % (one_lsb, inc, coh))
    emit(lines, "  declared quantization-dominated band (policy 2.5): "
                "[%.1f, %.1f] dBFS" % (floor, coh))
    emit(lines, "  eligibility: (i) graded == total windows, and (ii) the "
                "lowest graded window loses")
    emit(lines, "               at most %.0f%% of the %.2f dB budget to a "
                "worst-case coherent +-1 LSB"
         % (100.0 * HEADROOM_FRACTION, dev))
    emit(lines, "               difference, i.e. its level is >= %.1f dBFS "
                "(%.1f dB above the band edge)."
         % (eligibility_level_dbfs(), eligibility_level_dbfs() - coh))
    emit(lines)
    rows = []
    for wet in sorted(glob.glob(os.path.join(REPO, "fixtures", "audio", "*",
                                             "*-wet.wav"))):
        sc = wet[: -len("-wet.wav")] + ".json"
        if not os.path.exists(sc):
            continue
        rows.append(survey_fixture(wet, sc))
    rows.sort(key=lambda r: (not r["eligible"],
                             -(r["lowest_graded_dbfs"] or -999.0)))
    emit(lines, "  %-44s %4s %4s %9s %7s %8s %s"
         % ("fixture (declared wet tail region)", "tot", "grd", "lowest",
            "in-band", "spend", "eligible"))
    for r in rows:
        emit(lines, "  %-44s %4d %4d %9.1f %7d %7.2f  %s"
             % (r["fixture"].replace("fixtures/audio/", ""),
                r["total_windows"], r["graded_windows"],
                r["lowest_graded_dbfs"], r["windows_in_declared_band"],
                r["coherent_spend_db"], "YES" if r["eligible"] else "no"))
    eligible = [r for r in rows if r["eligible"]]
    emit(lines)
    emit(lines, "  eligible fixtures: %d of %d committed int16 wet fixtures"
         % (len(eligible), len(rows)))
    des_rel = "fixtures/audio/%s/%s-wet.wav" % DESIGNATED
    old_rel = "fixtures/audio/%s/%s-wet.wav" % OLD_FIXTURE
    des = next((r for r in rows if r["fixture"] == des_rel), None)
    old = next((r for r in rows if r["fixture"] == old_rel), None)
    emit(lines, "  designated (decision-records/0017): %s" % des_rel)
    if des:
        emit(lines, "    %d/%d windows graded, lowest graded %.1f dBFS "
                    "(%.1f dB above 1 LSB RMS, %.1f dB above the band edge),"
             % (des["graded_windows"], des["total_windows"],
                des["lowest_graded_dbfs"],
                des["lowest_graded_dbfs"] - one_lsb,
                des["lowest_graded_dbfs"] - coh))
        emit(lines, "    worst-case coherent +-1 LSB spend %.2f dB = %.1f%% of "
                    "the %.2f dB budget, %d windows in band"
             % (des["coherent_spend_db"],
                100.0 * des["coherent_spend_fraction_of_budget"], dev,
                des["windows_in_declared_band"]))
    emit(lines, "  old fixture (#160 conflict): %s" % old_rel)
    if old:
        emit(lines, "    %d/%d windows graded, lowest graded %.1f dBFS, "
                    "worst-case spend %.2f dB = %.0f%% of the budget, %d "
                    "windows in band -- INELIGIBLE: %s"
             % (old["graded_windows"], old["total_windows"],
                old["lowest_graded_dbfs"], old["coherent_spend_db"],
                100.0 * old["coherent_spend_fraction_of_budget"],
                old["windows_in_declared_band"],
                "; ".join(old["ineligible_because"])))
    ok = bool(des and des["eligible"] and des["windows_in_declared_band"] == 0
              and des["graded_windows"] == des["total_windows"]
              and old and not old["eligible"]
              and old["windows_in_declared_band"] > 0)
    emit(lines, "  leg 1: %s (a committed int16 wet fixture with NO graded "
                "window inside the band exists; the fixture #160 measured the "
                "conflict on does not)" % ("PASS" if ok else "FAIL"))
    return ok, {"status": "PASS" if ok else "FAIL",
                "declared_floor_dbfs": floor, "declared_max_dev_db": dev,
                "one_lsb_rms_dbfs": one_lsb,
                "band_edge_incoherent_dbfs": inc,
                "band_edge_coherent_dbfs": coh,
                "headroom_fraction": HEADROOM_FRACTION,
                "eligibility_level_dbfs": eligibility_level_dbfs(),
                "designated_fixture": des_rel, "old_fixture": old_rel,
                "eligible_fixtures": [r["fixture"] for r in eligible],
                "rows": rows}


# ---------------------------------------------------------------- leg 2 --

def leg2(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[2] #111 mono late-tail controls re-derived on the designated "
                "fixture")
    emit(lines, "=" * 74)
    emit(lines, "  NOTE (claim scope): every control model is derived from the "
                "COMMITTED reference render")
    emit(lines, "        (baseline model := reference), so a PASS here is a "
                "tool self-test, never a fidelity result.")
    floor = float(car.PROPOSED_TAIL["decay_curve_floor_dbfs"])
    dev = float(car.PROPOSED_TAIL["decay_curve_max_dev_db"])
    _, _, coh = band_edges()
    ctx, controls = make_controls(scratch, *DESIGNATED)
    emit(lines, "  fixture %s/%s, declared wet tail region [%d, %d), "
                "%d-frame windows"
         % (DESIGNATED[0], DESIGNATED[1], ctx["off"],
            ctx["off"] + ctx["length"], ctx["win"]))
    emit(lines)
    rows = []
    ok = True
    for c in controls:
        status, tc, budgets_ok = run_comparator(
            c["ref"], c["model"], c["sidecar"],
            os.path.join(scratch, "%s.declared.json" % c["tag"]), floor)
        dc = tc.get("tail_decay_curve") or {}
        rl, ml, dv, graded, over = over_budget_windows(
            ctx["ref"], c["mod"], ctx["off"], ctx["length"], ctx["win"],
            floor, dev)
        over_levels = [float(rl[i]) for i in over]
        lowest_over = min(over_levels) if over_levels else None
        clear = (True if lowest_over is None else lowest_over >= coh)
        good = status == c["required"]
        if c["is_control"]:
            ok &= good and clear
        rows.append({
            "control": c["control"], "required": c["required"],
            "observed": status, "as_required": good,
            "budgets_all_ok": budgets_ok,
            "tail_rms_rel_ok": tc.get("tail_rms_rel_ok"),
            "tail_decay_curve_ok": tc.get("tail_decay_curve_ok"),
            "graded_windows": dc.get("graded_windows"),
            "total_windows": dc.get("total_windows"),
            "max_dev_db": dc.get("max_dev_db"),
            "over_budget_windows": over,
            "over_budget_window_ref_dbfs": over_levels,
            "lowest_over_budget_ref_dbfs": lowest_over,
            "all_over_budget_windows_above_band": bool(clear),
            "shape_leg_is_sole_failing_leg": bool(
                status == "FAIL" and budgets_ok and tc.get("tail_rms_rel_ok")
                and not tc.get("tail_decay_curve_ok")),
            "result": (("CONTROL-OK" if (good and clear) else "CONTROL-BROKEN")
                       if c["is_control"] else "CHARACTERIZATION"),
        })
        emit(lines, "  %-40s required %-4s observed %-4s | shape leg %s "
                    "(%s/%s graded, worst dev %s dB) | %s"
             % (c["control"].split("/", 3)[-1], c["required"], status,
                "PASS" if tc.get("tail_decay_curve_ok") else "FAIL",
                dc.get("graded_windows"), dc.get("total_windows"),
                "n/a" if dc.get("max_dev_db") is None
                else "%.2f" % dc["max_dev_db"], rows[-1]["result"]))
        if over:
            emit(lines, "      over-budget windows %s at %s dBFS -- lowest "
                        "%.1f dBFS, %s the declared band (edge %.1f dBFS)"
                 % (",".join(str(i) for i in over[:8])
                    + ("..." if len(over) > 8 else ""),
                    "/".join("%.1f" % v for v in over_levels[:8])
                    + ("..." if len(over_levels) > 8 else ""),
                    lowest_over, "CLEAR of" if clear else "INSIDE",
                    coh))
        else:
            emit(lines, "      no over-budget window; residual leg %s, "
                        "budgets all pass=%s"
                 % ("PASS" if tc.get("tail_rms_rel_ok") else "FAIL",
                    budgets_ok))
    ctl = [r for r in rows if r["result"] != "CHARACTERIZATION"]
    n_ok = sum(1 for r in ctl if r["result"] == "CONTROL-OK")
    shape_only = [r["control"] for r in ctl if r["shape_leg_is_sole_failing_leg"]]
    dith = next((r for r in rows if r["control"].endswith("dither-first-half")),
                None)
    emit(lines)
    emit(lines, "  result: %d/%d controls behaved as required AND failed only "
                "above the declared band" % (n_ok, len(ctl)))
    emit(lines, "  shape leg is the sole failing leg for: %s"
         % (", ".join(s.split("/", 3)[-1] for s in shape_only) or "none"))
    if dith is not None:
        emit(lines, "  +-1 LSB dither over the first half of the declared tail "
                    "spends %.2f dB of the %.2f dB budget here"
             % (dith["max_dev_db"] or 0.0, dev))
        emit(lines, "    (#160 measured 0.79 dB for the same control on "
                    "koala2/seq-notes-coverage-v1)")
    ok &= bool(shape_only)
    emit(lines, "  leg 2: %s" % ("PASS" if ok else "FAIL"))
    return ok, {"status": "PASS" if ok else "FAIL",
                "fixture": "fixtures/audio/%s/%s-wet.wav" % DESIGNATED,
                "declared_floor_dbfs": floor,
                "band_edge_coherent_dbfs": coh,
                "shape_leg_sole_failing_leg": shape_only,
                "dither_spend_db": (dith or {}).get("max_dev_db"),
                "controls": rows}


# ---------------------------------------------------------------- leg 3 --

def leg3(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[3] floor-insensitivity pair (this issue's failure control)")
    emit(lines, "=" * 74)
    emit(lines, "  a) designated fixture: raising the floor to the band edges "
                "must change nothing.")
    emit(lines, "  b) OLD fixture: raising the floor must STILL disable "
                "mono/koala2/zero-late-tail-from-44%.")
    emit(lines)
    declared = float(car.PROPOSED_TAIL["decay_curve_floor_dbfs"])
    ctx, controls = make_controls(scratch, *DESIGNATED)
    rows = []
    by_floor = {}
    for floor, why in CANDIDATE_FLOORS:
        emit(lines, "  [a] %s/%s at floor %.1f dBFS -- %s"
             % (DESIGNATED[0], DESIGNATED[1], floor, why))
        obs = {}
        for c in controls:
            status, tc, _ = run_comparator(
                c["ref"], c["model"], c["sidecar"],
                os.path.join(scratch, "%s.%.1f.json" % (c["tag"], floor)),
                floor)
            dc = tc.get("tail_decay_curve") or {}
            obs[c["control"]] = (status, dc.get("graded_windows"),
                                 dc.get("total_windows"))
            rows.append({"fixture": "designated", "floor_dbfs": floor,
                         "control": c["control"], "required": c["required"],
                         "observed": status,
                         "graded_windows": dc.get("graded_windows"),
                         "total_windows": dc.get("total_windows")})
        by_floor[floor] = obs
        emit(lines, "      %s"
             % ", ".join("%s=%s(%s/%s)" % (k.split("/", 3)[-1], v[0], v[1],
                                           v[2]) for k, v in obs.items()))
    base = by_floor[declared]
    drift = []
    for floor, obs in by_floor.items():
        for k, v in obs.items():
            if v[0] != base[k][0] or v[1] != base[k][1]:
                drift.append("%s at %.1f dBFS: %s(%s) vs declared %s(%s)"
                             % (k, floor, v[0], v[1], base[k][0], base[k][1]))
    emit(lines)
    emit(lines, "  [a] drift vs the declared floor: %s"
         % ("; ".join(drift) if drift else
            "none -- every control keeps its status and its graded-window "
            "count at every band edge"))
    emit(lines)

    # (b) the retained #160 failure control, on the OLD fixture.
    old_ref, old_sc = fixture_paths(*OLD_FIXTURE)
    region = car.declared_tail_region(old_sc, "wet")
    off, length = region["tail_offset"], region["tail_frames"]
    ref, sr = car.read_wav(old_ref)
    mod = ref.astype(np.int64).copy()
    mod[off + int(length * 0.44):off + length] = 0
    p = os.path.join(scratch, "koala2-zero-late-tail-from-44.wav")
    write_i16(p, mod, sr)
    old_rows = []
    for floor, why in CANDIDATE_FLOORS:
        status, tc, _ = run_comparator(
            old_ref, p, old_sc,
            os.path.join(scratch, "koala2-44.%.1f.json" % floor), floor)
        dc = tc.get("tail_decay_curve") or {}
        old_rows.append({"fixture": "old", "floor_dbfs": floor,
                         "control": "mono/koala2/zero-late-tail-from-44%",
                         "required": "FAIL", "observed": status,
                         "graded_windows": dc.get("graded_windows"),
                         "total_windows": dc.get("total_windows")})
        emit(lines, "  [b] koala2/zero-late-tail-from-44%% at floor %.1f dBFS "
                    "-> %-4s (%s/%s graded) -- %s"
             % (floor, status, dc.get("graded_windows"),
                dc.get("total_windows"),
                "as landed" if status == "FAIL" else
                "DISABLED by the raised floor"))
    rows.extend(old_rows)
    at_declared = next(r for r in old_rows if r["floor_dbfs"] == declared)
    disabled = [r["floor_dbfs"] for r in old_rows
                if r["floor_dbfs"] > declared and r["observed"] == "PASS"]
    emit(lines)
    emit(lines, "  [b] control still FAILs at the declared floor: %s; raised "
                "floors that disable it: %s"
         % (at_declared["observed"] == "FAIL",
            ", ".join("%.1f" % f for f in disabled) or "none"))
    ok = (not drift) and at_declared["observed"] == "FAIL" and bool(disabled)
    emit(lines, "  leg 3: %s (the designated fixture is floor-insensitive "
                "across the band AND #160's control keeps firing on the old "
                "fixture)" % ("PASS" if ok else "FAIL"))
    return ok, {"status": "PASS" if ok else "FAIL",
                "designated_drift": drift,
                "old_fixture_control_at_declared_floor":
                    at_declared["observed"],
                "raised_floors_that_disable_the_old_control":
                    ["%.1f" % f for f in disabled],
                "rows": rows}


# ----------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch-root", default="/tmp/sxt-int16-wet-shape")
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
    emit(lines, "int16 wet tail-shape grading fixture probe (issue #187) -- "
                "SXT-017 pilot-freeze input")
    emit(lines, "continuation of issue #160 / decision-records/0016 option F-E "
                "(fixture-side arm)")
    emit(lines, "repo HEAD %s   numpy %s   python %s   %s"
         % (head[:12], np.__version__, sys.version.split()[0], stamp))
    emit(lines, "shipped budget (unmodified): %s"
         % json.dumps(car.PROPOSED_TAIL, sort_keys=True))
    emit(lines, "claim scope: comparator and fixture-selection behaviour only; "
                "no fidelity, RTL, support,")
    emit(lines, "             coverage or sound claim; no budget frozen.")
    emit(lines)
    summary = {"issue": 187, "head": head, "timestamp": stamp,
               "numpy": np.__version__, "python": sys.version.split()[0],
               "shipped_proposed_tail": dict(car.PROPOSED_TAIL),
               "designated_fixture": "fixtures/audio/%s/%s-wet.wav"
                                     % DESIGNATED,
               "old_fixture": "fixtures/audio/%s/%s-wet.wav" % OLD_FIXTURE,
               "legs": {}}
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
    with open(os.path.join(ART, "fixture-probe.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(ART, "fixture-probe.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
