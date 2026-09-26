#!/usr/bin/env python3
"""SXT-028e-sse exactness harness: RTL trace vs frozen model trace (INTEGER
equality) + negative-control mutants.

Follows the `tools/compare_rtl_model_distortion.py` (SXT-028e) pattern.

Compares, with integer equality (any mismatch = FAIL):
  * every per-instance output sample of every render block (O lines);
  * every shaper-loop tap checkpoint (X lines): the post-lp2 oversampled
    L/R word at each of the first 4 base samples x 4 oversampling steps --
    this pins the feedback recurrence, the quad shaper and both oversampled
    LP stages, not just the block output;
  * every declared state checkpoint (T lines): feedback registers, both
    lipol targets, both peak-EQ coefficient lags, all four TDF2 register
    pairs, all 144 halfband allpass state words, **all 8 quad-waveshaper
    registers and both `init` mask lanes**, the end-of-block `dNow` (which
    pins the /64 drive interpolation) and the block's DC-offset probe
    result -- per instance;
  * the frozen-revision pin (a stale trace revision is REFUSED, never PASS).

Cases
  prs-dual-<n>        2 instances, independent state, PRS stimulus, two
                      different parameter sets AND two different SSE
                      waveshaper models (7 fuzzsoft / 6 fwrectify -- the two
                      that own QuadWaveshaperState registers)
  prs-reset<r>-<n>    same + core reset at block r (engine fx-rebuild /
                      panic semantics: init() == suspend())
  model-<i>-*         one case per reachable FX model 3..7
  corners-*           parameter corners: deactivated high-cuts, extreme
                      drive/feedback, the DD-4 low-drive saturation corner
  reset-mid-tail-*    2 instances, reset 96 blocks INTO the ringout tail
  ringout-tail-1663   the declared tail span: 64 driven blocks followed by
                      the full 1600-block ringout fade to completion

Mutant negative controls (generated from tb_distortion_sse.sv by source
substitution; each MUST FAIL the check it targets, on a stimulus bed chosen
so the defect is REACHABLE -- a control run on a bed that cannot expose it
would be theatre):
  mutant-wsshared      instance 1's QuadWaveshaperState pooled onto
                       instance 0 (the per-instance-state acceptance)
  mutant-nodcoffset    the zero-input DC-offset subtraction dropped
  mutant-dcprobe-live  the DC probe run on the LIVE wsState instead of a
                       throw-away zeroed one (corrupts the registers)
  mutant-drivestep128  dD = (dE - dS)/128 instead of the pinned /64
  mutant-diginorm      `skipDriveNorm` removed: DIGITAL gets the 1/dNow
                       pre-scale too (the double division the source
                       comment warns diverges)
  mutant-order         band1/band2 swapped (post-EQ applied pre-shaper)
  mutant-adaainit      the ADAA `init` first-sample mask forced false
  mutant-dcblockfac    the dcBlock pole 0.9999 replaced by 1.0
  mutant-cvttrunc      the SSE round-to-nearest-even int conversion replaced
                       by truncation (the `lookup_waveshape` convention)
  stale-revision-pin   the same trace judged against a wrong frozen pin

Usage: python3 tools/compare_rtl_model_distortion_sse.py [--quick] [--out JSON]
Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

from distortion_sse_model import (  # noqa: E402
    DistortionSSEModel, DistortionSSEParams, HalfbandD2, model_revision,
    HB_COEFFS_Q, BLOCK, RINGOUT_TIME,
)
from quad_shapers import (  # noqa: E402
    QuadWaveshaperState, SHAPER_INIT_WORDS, SHAPER_INIT_BASE,
)

IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")
TBDIR = os.path.join(REPO, "rtl", "effects", "type-distortion-sse")
TB = os.path.join(TBDIR, "tb_distortion_sse.sv")
WSROM = os.path.join(TBDIR, "ws_sse_q29.hex")

# --- synthetic parameter sets (declared; the fixture-preset sets require the
# --- oracle extraction, which is BLOCKED in an oracle-free environment)
BASE = dict(preeq_gain_f=0.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
            preeq_highcut_f=70.0, drive_f=0.0, feedback_f=0.635445,
            posteq_gain_f=0.0, posteq_freq_f=3.0, posteq_bw_f=0.3,
            posteq_highcut_f=30.535736, gain_f=0.0, model_i=3,
            preeq_highcut_deactivated=False, posteq_highcut_deactivated=False,
            preeq_gain_extend=False, posteq_gain_extend=False,
            drive_extend=False)


def pset(**kw):
    d = dict(BASE)
    d.update(kw)
    return d


# Distinct pre/post EQ gains make the band order OBSERVABLE (with both gains
# at 0 dB `coeff_peakEQ` returns the identity biquad and an order swap is
# unobservable -- that is why `mutant-order` needs these).
SYNTH_A = pset(model_i=7, preeq_gain_f=6.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
               drive_f=6.0, posteq_gain_f=-4.5, posteq_freq_f=24.0,
               posteq_bw_f=1.1)
SYNTH_B = pset(model_i=6, preeq_gain_f=-8.0, preeq_freq_f=3.81786,
               preeq_bw_f=1.944644, preeq_highcut_f=66.0, drive_f=8.0,
               drive_extend=True, feedback_f=0.814286, posteq_gain_f=10.0,
               posteq_freq_f=40.0, posteq_bw_f=2.03125,
               posteq_highcut_f=66.0, gain_f=-21.985725)
# Digital bed: the ONE model where `dNow` is observable at all (for the other
# four the 1/dNow pre-scale and the shaper's own drive multiply cancel), so
# it is the only bed on which the /64 step and `skipDriveNorm` can be
# controlled. Reset mid-render restarts the drive ramp so dS != dE again.
SYNTH_DIGI = pset(model_i=4, preeq_gain_f=3.0, preeq_freq_f=6.0,
                  posteq_gain_f=-6.0, posteq_freq_f=30.0, drive_f=12.0,
                  feedback_f=0.35, gain_f=-6.0)
SYNTH_SINE = pset(model_i=3, preeq_gain_f=4.0, preeq_freq_f=6.0,
                  posteq_gain_f=-3.0, posteq_freq_f=30.0, drive_f=9.0,
                  feedback_f=0.5)

MODEL_CASES = {
    "model-3-sine": pset(model_i=3, drive_f=6.0, feedback_f=0.5,
                         preeq_gain_f=4.0, posteq_gain_f=-3.0),
    "model-4-digital": pset(model_i=4, drive_f=12.0, feedback_f=0.35,
                            preeq_gain_f=3.0, posteq_gain_f=-6.0),
    "model-5-ojd": pset(model_i=5, drive_f=18.0, feedback_f=-0.4,
                        preeq_gain_f=2.0, posteq_gain_f=-2.0),
    "model-6-fwrectify": pset(model_i=6, drive_f=3.0, feedback_f=0.7,
                              preeq_gain_f=5.0, posteq_gain_f=-5.0),
    "model-7-fuzzsoft": pset(model_i=7, drive_f=0.0, feedback_f=0.6,
                             preeq_gain_f=1.0, posteq_gain_f=-1.0),
}

CORNERS = {
    "corners-deact-both": pset(model_i=5, preeq_highcut_deactivated=True,
                               posteq_highcut_deactivated=True,
                               drive_f=24.0, feedback_f=-0.9),
    "corners-extend-hot": pset(model_i=6, drive_f=8.0, drive_extend=True,
                               preeq_gain_f=8.0, preeq_gain_extend=True,
                               posteq_gain_f=-4.0, posteq_gain_extend=True,
                               feedback_f=0.0,
                               preeq_highcut_deactivated=True),
    # DD-4: drive extended to -120 dB quantizes to ZERO in the Q13.18 ramp
    # word, so the 1/dNow pre-scale takes the saturated-reciprocal path. The
    # harness records the model-side saturation-event count; the RTL and the
    # model must still agree EXACTLY (both saturate identically).
    "corners-lowdrive-sat": pset(model_i=3, drive_f=-24.0, drive_extend=True,
                                 feedback_f=0.5, preeq_gain_f=6.0,
                                 posteq_gain_f=-6.0),
    "corners-digital-hifb": pset(model_i=4, drive_f=-12.0, feedback_f=0.95,
                                 preeq_highcut_f=24.0, posteq_highcut_f=-12.0,
                                 gain_f=6.0),
}

# Per-case descriptions, recorded verbatim in `rtl-exactness.json.note` and
# reproduced in reports/SXT-028e-sse/EVIDENCE.md §4. A case whose note only
# said "parameter corner" would make the evidence table unreadable and would
# hide WHICH quirk each case is there to reach.
CASE_NOTES = {
    "model-3-sine": "FX model 3 SINUS_SSE2<false>: table gather with the "
                    "round-to-nearest SSE index and DO_FOLD == false edge clip",
    "model-4-digital": "FX model 4 DIGI_SSE2: skipDriveNorm, the internal "
                       "rcp(drive) and the staircase quantizer",
    "model-5-ojd": "FX model 5 OJD: all five disjoint breakpoint branches, "
                   "negative feedback",
    "model-6-fwrectify": "FX model 6 ADAA_FULL_WAVE: the two ADAA registers "
                         "and the `init` first-sample mask",
    "model-7-fuzzsoft": "FX model 7 TableEval<FuzzTable<1>,1024,TANH>: TANH "
                        "Q40.23 rational, the 1025-word LUT and dcBlock",
    "corners-deact-both": "both high-cuts deactivated (LP stages bypassed), "
                          "drive 24 dB, feedback -0.9",
    "corners-extend-hot": "extended drive and both extended EQ gains, one "
                          "high-cut deactivated, zero feedback",
    "corners-lowdrive-sat": "DD-4 corner: extended drive -120 dB quantizes to "
                            "ZERO in the Q13.18 ramp word, so the 1/dNow "
                            "pre-scale takes the saturated-reciprocal path",
    "corners-digital-hifb": "model 4 with feedback 0.95 — the loop gain the "
                            "`skipDriveNorm` exception exists to protect",
}


def qhex(v, bits):
    m = (1 << bits) - 1
    return f"{v & m:0{bits // 4}x}"


CTRL_WIDTHS = [32, 32, 32] + [64] * 20 + [32]


def write_init(path, models):
    """INITFILE: 12 halfband coefficients, 2x2 lipol targets, 11 shaper
    scalars (DR-0002 clause 1 / DR-0014: the RTL owns no engine data)."""
    with open(path, "w") as f:
        for w in HB_COEFFS_Q:
            f.write(qhex(w, 64) + "\n")
        for i in range(2):
            if i < len(models):
                dw, ow = models[i].init_words()
            else:
                dw, ow = 0, 0
            f.write(qhex(dw, 64) + "\n")
            f.write(qhex(ow, 64) + "\n")
        assert SHAPER_INIT_BASE == 16
        for w in SHAPER_INIT_WORDS:
            f.write(qhex(w, 64) + "\n")


def _state_map(m):
    st = m.st.chain
    ws = m.st.ws
    d = {"fbl": st.fb_l, "fbr": st.fb_r,
         "drv": st.drive.target, "og": st.outgain.target}
    for j in range(5):
        d[f"b1l{j}"] = st.band1.lag[j]
        d[f"b2l{j}"] = st.band2.lag[j]
    for tag, bq in (("b1", st.band1), ("b2", st.band2),
                    ("l1", st.lp1), ("l2", st.lp2)):
        d[f"{tag}r00"] = bq.reg0[0]
        d[f"{tag}r10"] = bq.reg1[0]
        d[f"{tag}r01"] = bq.reg0[1]
        d[f"{tag}r11"] = bq.reg1[1]
    for h, hb in enumerate((st.hr_a, st.hr_b)):
        for c in range(2):
            for r in range(2):
                for j in range(HalfbandD2.STAGES):
                    for t in range(3):
                        d[f"h{h}{c}{r}{j}x{t}"] = hb.x[c][r][j][t]
                        d[f"h{h}{c}{r}{j}y{t}"] = hb.y[c][r][j][t]
    # this leaf's own state: the quad-waveshaper registers + init mask
    for i in range(QuadWaveshaperState.N_REGISTERS):
        for lane in range(QuadWaveshaperState.LANES):
            d[f"wsR{i}{lane}"] = ws.R[i][lane]
    for lane in range(QuadWaveshaperState.LANES):
        d[f"wsI{lane}"] = 1 if ws.init[lane] else 0
    # the drive interpolation end point and the DC-offset probe
    d["dnowe"] = m.ctrl.get("d_now_end", 0)
    d["dcof"] = m.ctrl.get("dc_offset", 0)
    d["er"] = st.ext_reads
    d["ew"] = st.ext_writes
    return d


def _want_state(b, n_blocks, render0):
    return b == 0 or b == n_blocks - 1 or (b >= render0 and (b - render0) % 16 == 0)


def _want_taps(b, n_blocks, render0):
    return b == 0 or b == n_blocks - 1 or (b >= render0 and (b - render0) % 8 == 0)


def build_case(n_blocks, param_dicts, reset_at, seed, wd, render0=0,
               ringout_from=None, amp=1 << 20):
    """Run the frozen model; write in/ctrl/init hex; return expected records."""
    os.makedirs(wd, exist_ok=True)
    models = [DistortionSSEModel(DistortionSSEParams(p), f"i{i}")
              for i, p in enumerate(param_dicts)]
    for m in models:
        m.initialize()
    rs = random.Random(seed)
    in_hex = os.path.join(wd, "in.hex")
    ctrl_hex = os.path.join(wd, "ctrl.hex")
    init_hex = os.path.join(wd, "init.hex")
    exps = []
    with open(in_hex, "w") as fi, open(ctrl_hex, "w") as fc:
        for b in range(n_blocks):
            silent = ringout_from is not None and b >= ringout_from
            ring = (b - ringout_from + 1) if silent else 0
            if silent:
                il = [0] * BLOCK
                ir = [0] * BLOCK
            else:
                il = [rs.randint(-amp, amp) for _ in range(BLOCK)]
                ir = [rs.randint(-amp, amp) for _ in range(BLOCK)]
            rec = {"b": b, "O": {}, "X": {}, "T": {}}
            rows = []
            for i, m in enumerate(models):
                if reset_at is not None and b == reset_at:
                    m.initialize()
                for v in il:
                    fi.write(qhex(v, 32) + "\n")
                for v in ir:
                    fi.write(qhex(v, 32) + "\n")
                taps = []
                hook = None
                if _want_taps(b, n_blocks, render0):
                    def hook(k, s, lv, rv, _t=taps):
                        _t.append((lv, rv))
                out = m.process_block(il, ir, ringout=ring, tap_hook=hook)
                for idx, wv in enumerate(m.control_words()):
                    rows.append(qhex(wv, CTRL_WIDTHS[idx]))
                if _want_taps(b, n_blocks, render0):
                    flat = []
                    for lv, rv in taps:
                        flat += [lv, rv]
                    rec["X"][i] = flat
                if b >= render0:
                    rec["O"][i] = list(out[0]) + list(out[1])
                if _want_state(b, n_blocks, render0):
                    rec["T"][i] = _state_map(m)
            for wtext in rows:
                fc.write(wtext + "\n")
            exps.append(rec)
    write_init(init_hex, models)
    sat = [m.st.ws.sat_events for m in models]
    return exps, in_hex, ctrl_hex, init_hex, sat


def _int_or_none(v):
    try:
        return int(v)
    except ValueError:
        return None


def parse_tb_trace(path):
    rev = None
    O, X, T = {}, {}, {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "R":
                rev = parts[1]
            elif parts[0] == "O":
                O[(int(parts[1]), int(parts[2]))] = [_int_or_none(v) for v in parts[3:]]
            elif parts[0] == "X":
                X[(int(parts[1]), int(parts[2]))] = [_int_or_none(v) for v in parts[3:]]
            elif parts[0] == "T":
                d = {}
                for j in range(3, len(parts) - 1, 2):
                    d[parts[j]] = _int_or_none(parts[j + 1])
                T[(int(parts[1]), int(parts[2]))] = d
    return rev, {"O": O, "X": X, "T": T}


def run_sim(tb_source, plusargs, workdir):
    vvp = os.path.join(workdir, "tb.vvp")
    subprocess.run([IV, "-g2012", "-o", vvp, tb_source], check=True, cwd=workdir)
    subprocess.run([VVP, vvp] + plusargs, check=True, cwd=workdir,
                   stdout=subprocess.DEVNULL)


def compare_case(exp, got, ninst):
    fails = []
    checked = {"outputs": 0, "taps": 0, "checkpoints": 0, "fields": 0}
    for rec in exp:
        b = rec["b"]
        for i in range(ninst):
            want = rec["O"].get(i)
            g = got["O"].get((b, i))
            if want is not None:
                if g is None:
                    fails.append(f"b{b} i{i}: missing O line")
                else:
                    for k, (a, bv) in enumerate(zip(want, g)):
                        checked["outputs"] += 1
                        if a != bv:
                            fails.append(f"b{b} i{i} out[{k}]: model={a} rtl={bv}")
                            if len(fails) > 20:
                                return checked, fails
            wx = rec["X"].get(i)
            if wx:
                checked["taps"] += 1
                gx = got["X"].get((b, i))
                if gx != wx:
                    fails.append(f"b{b} i{i}: tap checkpoint mismatch")
                    if gx is not None:
                        for kk, (a, bv) in enumerate(zip(wx, gx)):
                            if a != bv:
                                fails.append(f"  first tap diff flat[{kk}]: "
                                             f"model={a} rtl={bv}")
                                break
                    if len(fails) > 20:
                        return checked, fails
            wt = rec["T"].get(i)
            if wt is not None:
                checked["checkpoints"] += 1
                gt = got["T"].get((b, i))
                if gt is None:
                    fails.append(f"b{b} i{i}: missing T line")
                    continue
                for kk, want_v in wt.items():
                    checked["fields"] += 1
                    if gt.get(kk) != want_v:
                        fails.append(f"b{b} i{i} {kk}: model={want_v} rtl={gt.get(kk)}")
                        if len(fails) > 20:
                            return checked, fails
    return checked, fails


def simulate(tb_source, name, workdir, n_blocks, ninst, in_hex, ctrl_hex,
             init_hex, reset_at=None, rev8="00000000", render0=0):
    wd = os.path.join(workdir, name)
    os.makedirs(wd, exist_ok=True)
    trace = os.path.join(wd, "tb_trace.txt")
    plus = [f"+NINST={ninst}", f"+NBLOCKS={n_blocks}", f"+RENDER0={render0}",
            f"+TRACE={trace}", f"+INFILE={in_hex}", f"+CTRLFILE={ctrl_hex}",
            f"+INITFILE={init_hex}", f"+WSROM={WSROM}", f"+REV={rev8}"]
    if reset_at is not None:
        plus.append(f"+RESETAT={reset_at}")
    run_sim(tb_source, plus, wd)
    return trace


def judge(name, exp, trace, ninst, rev8, n_blocks, note="", sat=None):
    rev_got, got = parse_tb_trace(trace)
    checked, fails = compare_case(exp, got, ninst)
    pin_ok = rev_got == rev8
    return {"case": name, "blocks": n_blocks, "ninst": ninst,
            "exact": (not fails) and pin_ok,
            "revision_pin": {"ok": pin_ok, "rtl_trace": rev_got,
                             "expected": rev8},
            "checked": checked, "mismatches": len(fails),
            "model_side_saturation_events": sat,
            "note": note, "first_failures": fails[:8]}


# --- mutant negative controls -------------------------------------------
# Each entry: (source substitutions, stimulus bed, what it targets).
MUTANTS = {
    "mutant-wsshared": (
        [("                    o_l = ws_quad(inst, 0, wsm[inst], sbl, dnow);\n"
          "                    o_r = ws_quad(inst, 1, wsm[inst], sbr, dnow);",
          "                    o_l = ws_quad(0, 0, wsm[inst], sbl, dnow);\n"
          "                    o_r = ws_quad(0, 1, wsm[inst], sbr, dnow);")],
        "dual", "per-instance QuadWaveshaperState pooled onto instance 0"),
    "mutant-nodcoffset": (
        [("                    fbl[inst] = c2a(qsub64(o_l, dcoff));\n"
          "                    fbr[inst] = c2a(qsub64(o_r, dcoff));",
          "                    fbl[inst] = c2a(o_l);\n"
          "                    fbr[inst] = c2a(o_r);")],
        "dual", "the zero-input DC-offset subtraction dropped"),
    "mutant-dcprobe-live": (
        [("            ws_zero(2, 0);                    // probeState.R = 0, .init = 0\n"
          "            dcoff = ws_quad(2, 0, wsm[inst], 64'sd0, ds_c);",
          "            dcoff = ws_quad(inst, 0, wsm[inst], 64'sd0, ds_c);")],
        "dual", "DC probe run on the LIVE wsState instead of a throw-away"),
    "mutant-order": (
        [("                bq_sample(inst, 0, ilw[inst][k], irw[inst][k], ol, orr);",
          "                bq_sample(inst, 1, ilw[inst][k], irw[inst][k], ol, orr);"),
         ("                bq_sample(inst, 1, out_l[k], out_r[k], ol, orr);",
          "                bq_sample(inst, 0, out_l[k], out_r[k], ol, orr);")],
        "dual", "band1/band2 swapped (post-EQ applied pre-shaper)"),
    "mutant-dcblockfac": (
        [("            filtval = qadd64(dx, qmul_cc(KC(26), wsR[inst][1][lane]));",
          "            filtval = qadd64(dx, wsR[inst][1][lane]);")],
        "dual", "dcBlock pole 0.9999 replaced by 1.0"),
    "mutant-adaainit": (
        [("                ws_zero(i_, 1);", "                ws_zero(i_, 0);")],
        "dual", "ADAA `init` first-sample mask forced false"),
    "mutant-drivestep128": (
        [("                                   - $signed({{32{dr_cur[inst][31]}}, dr_cur[inst]})) <<< 19);",
          "                                   - $signed({{32{dr_cur[inst][31]}}, dr_cur[inst]})) <<< 18);")],
        "digital", "dD = (dE - dS)/128 instead of the pinned /64"),
    "mutant-diginorm": (
        [("            skipnorm = (wsm[inst] == 4);      // skipDriveNorm: DIGITAL only",
          "            skipnorm = 0;")],
        "digital", "`skipDriveNorm` removed: DIGITAL double-divided by drive"),
    "mutant-cvttrunc": (
        [("            if (r > HALF_C) n = n + 64'sd1;\n"
          "            else if (r == HALF_C && (n & 64'sd1)) n = n + 64'sd1;",
          "            // MUTANT: truncate instead of round-to-nearest-even")],
        "sine", "SSE round-to-nearest-even int conversion replaced by "
                "truncation (the lookup_waveshape convention)"),
}


def make_mutant(name, replacements):
    with open(TB) as f:
        text = f.read()
    for old, new in replacements:
        assert old in text, (name, old[:80])
        text = text.replace(old, new)
    out = os.path.join(TBDIR, f"tb_distortion_sse_{name.split('-', 1)[1]}.sv")
    text = text.replace("module tb_distortion_sse;",
                        "// GENERATED MUTANT -- negative control, never the "
                        "frozen RTL.\nmodule tb_distortion_sse;")
    with open(out, "w") as f:
        f.write(text)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "reports",
                                                  "SXT-028e-sse",
                                                  "rtl-exactness.json"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    rev8 = model_revision()[:8]
    workdir = args.workdir or tempfile.mkdtemp(prefix="sxt028e-sse-rtl-")
    iv_ver = subprocess.run([IV, "-V"], capture_output=True, text=True)
    iv_line = (iv_ver.stdout or "").splitlines()
    results = {"schema_version": 1, "leaf": "SXT-028e-sse", "sim": "iverilog",
               "sim_version": iv_line[0].strip() if iv_line else "UNKNOWN",
               "model_revision": model_revision(),
               "tb": os.path.relpath(TB, REPO),
               "ws_rom": os.path.relpath(WSROM, REPO),
               "cases": [], "mutant_controls": []}

    nb = 48 if args.quick else 128

    # --- stimulus beds (also reused by the mutant controls) ---------------
    beds = {}
    exps_d, in_d, ctrl_d, init_d, sat_d = build_case(
        nb, [SYNTH_A, SYNTH_B], None, 11, os.path.join(workdir, "prs-dual"))
    beds["dual"] = dict(exp=exps_d, ninst=2, n=nb, reset=None,
                        files=(in_d, ctrl_d, init_d))
    nbd = 48
    exps_g, in_g, ctrl_g, init_g, sat_g = build_case(
        nbd, [SYNTH_DIGI], 24, 23, os.path.join(workdir, "bed-digital"))
    beds["digital"] = dict(exp=exps_g, ninst=1, n=nbd, reset=24,
                           files=(in_g, ctrl_g, init_g))
    exps_s, in_s, ctrl_s, init_s, sat_s = build_case(
        nbd, [SYNTH_SINE], None, 29, os.path.join(workdir, "bed-sine"))
    beds["sine"] = dict(exp=exps_s, ninst=1, n=nbd, reset=None,
                        files=(in_s, ctrl_s, init_s))

    tr = simulate(TB, "prs-dual", workdir, nb, 2, in_d, ctrl_d, init_d,
                  rev8=rev8)
    results["cases"].append(judge(
        f"prs-dual-{nb}", exps_d, tr, 2, rev8, nb,
        "two instances, models 7 and 6, independent state", sat_d))

    tr = simulate(TB, "bed-digital", workdir, nbd, 1, in_g, ctrl_g, init_g,
                  reset_at=24, rev8=rev8)
    results["cases"].append(judge(
        f"digital-reset24-{nbd}", exps_g, tr, 1, rev8, nbd,
        "model 4: skipDriveNorm + the /64 drive interpolation, reset "
        "mid-render so the drive ramp restarts", sat_g))

    tr = simulate(TB, "bed-sine", workdir, nbd, 1, in_s, ctrl_s, init_s,
                  rev8=rev8)
    results["cases"].append(judge(
        f"sine-{nbd}", exps_s, tr, 1, rev8, nbd,
        "model 3: the round-to-nearest SSE table index convention", sat_s))

    # --- reset mid-render (fx-rebuild / panic)
    ra = nb // 2
    exps_r, in_r, ctrl_r, init_r, sat_r = build_case(
        nb, [SYNTH_A, SYNTH_B], ra, 11, os.path.join(workdir, "prs-reset"))
    tr = simulate(TB, "prs-reset", workdir, nb, 2, in_r, ctrl_r, init_r,
                  reset_at=ra, rev8=rev8)
    results["cases"].append(judge(f"prs-reset{ra}-{nb}", exps_r, tr, 2, rev8,
                                  nb, "core reset mid-render", sat_r))

    # --- one case per reachable FX model, plus the parameter corners
    extra = list(MODEL_CASES.items()) + list(CORNERS.items())
    if args.quick:
        extra = extra[:2]
    for cname, cp in extra:
        e, i_, c_, n_, s_ = build_case(48, [cp], None, 7,
                                       os.path.join(workdir, cname))
        tr = simulate(TB, cname, workdir, 48, 1, i_, c_, n_, rev8=rev8)
        results["cases"].append(judge(cname, e, tr, 1, rev8, 48,
                                      CASE_NOTES[cname], s_))

    # --- declared tail span: the full 1600-block ringout fade
    if not args.quick:
        tb_blocks = 64 + RINGOUT_TIME - 1
        e, i_, c_, n_, s_ = build_case(tb_blocks, [SYNTH_A], None, 5,
                                       os.path.join(workdir, "ringout"),
                                       render0=64, ringout_from=64)
        tr = simulate(TB, "ringout", workdir, tb_blocks, 1, i_, c_, n_,
                      rev8=rev8, render0=64)
        results["cases"].append(judge(
            f"ringout-tail-{tb_blocks}", e, tr, 1, rev8, tb_blocks,
            "declared tail span (1600-block ringout, model 7)", s_))

        rt_blocks = 64 + 256
        rt_reset = 64 + 96
        e, i_, c_, n_, s_ = build_case(rt_blocks, [SYNTH_A, SYNTH_B], rt_reset,
                                       13, os.path.join(workdir,
                                                        "reset-mid-tail"),
                                       render0=64, ringout_from=64)
        tr = simulate(TB, "reset-mid-tail", workdir, rt_blocks, 2, i_, c_, n_,
                      reset_at=rt_reset, rev8=rev8, render0=64)
        results["cases"].append(judge(
            f"reset-mid-tail-{rt_reset}-{rt_blocks}", e, tr, 2, rev8,
            rt_blocks, "fx-rebuild/panic reset 96 blocks into the ringout "
                       "tail", s_))

    # --- mutants (negative controls) on the bed that can EXPOSE each one
    for mname, (repl, bedname, target) in MUTANTS.items():
        mpath = make_mutant(mname, repl)
        bed = beds[bedname]
        wd = os.path.join(workdir, mname)
        os.makedirs(wd, exist_ok=True)
        trace = os.path.join(wd, "tb_trace.txt")
        in_h, ctrl_h, init_h = bed["files"]
        plus = [f"+NINST={bed['ninst']}", f"+NBLOCKS={bed['n']}",
                "+RENDER0=0", f"+TRACE={trace}", f"+INFILE={in_h}",
                f"+CTRLFILE={ctrl_h}", f"+INITFILE={init_h}",
                f"+WSROM={WSROM}", f"+REV={rev8}"]
        if bed["reset"] is not None:
            plus.append(f"+RESETAT={bed['reset']}")
        try:
            run_sim(mpath, plus, wd)
            _, got = parse_tb_trace(trace)
            checked, fails = compare_case(bed["exp"], got, bed["ninst"])
            ok = bool(fails)
            res = {"case": mname, "bed": bedname, "targets": target,
                   "blocks": bed["n"], "ninst": bed["ninst"],
                   "exact": not fails, "mismatches": len(fails),
                   "checked": checked, "ok": ok,
                   "verdict": ("CONTROL-OK (mutant FAILS the exactness check)"
                               if ok else "CONTROL-BROKEN (mutant PASSED!)"),
                   "first_failures": fails[:5]}
        except subprocess.CalledProcessError as e:
            res = {"case": mname, "bed": bedname, "targets": target,
                   "ok": True, "exact": False,
                   "verdict": f"CONTROL-OK (mutant refused to elaborate/run: {e})"}
        results["mutant_controls"].append(res)
        print(mname, "->", res["verdict"])

    # --- stale-stub control: the same trace judged against a wrong pin
    stale = judge("stale-revision-pin", exps_d,
                  simulate(TB, "stale", workdir, nb, 2, in_d, ctrl_d, init_d,
                           rev8="deadbeef"),
                  2, rev8, nb, "harness pinned to a stale model revision")
    stale["ok"] = not stale["exact"]
    stale["targets"] = "a stale/stub frozen-model revision reported as PASS"
    stale["verdict"] = ("CONTROL-OK (stale revision pin REFUSES to report PASS)"
                        if stale["ok"] else "CONTROL-BROKEN (stale pin passed!)")
    results["mutant_controls"].append(stale)
    print("stale-revision-pin ->", stale["verdict"])

    ok_all = all(c["exact"] for c in results["cases"]) and \
        all(m["ok"] for m in results["mutant_controls"])
    results["status"] = "PASS" if ok_all else "FAIL"
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    for c in results["cases"]:
        print(c["case"], "exact" if c["exact"] else "FAIL", c.get("checked", ""))
        if not c["exact"]:
            for ff in c["first_failures"]:
                print("   ", ff)
    print("status:", results["status"])
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
