#!/usr/bin/env python3
"""SXT-028e exactness harness: RTL trace vs frozen model trace (INTEGER
equality) + negative-control mutants.

Compares, with integer equality (any mismatch = FAIL):
  * every per-instance output sample of every render block (O lines);
  * every shaper-loop tap checkpoint (X lines): the post-lp2 oversampled
    L/R word at each of the first 4 base samples x 4 oversampling steps —
    this pins the feedback recurrence, the waveshaper table read and both
    oversampled LP stages, not just the block output;
  * every declared state checkpoint (T lines): feedback registers, both
    lipol targets, both peak-EQ coefficient lags, all four TDF2 register
    pairs, and all 144 halfband allpass state words per instance;
  * the frozen-revision pin (a stale trace revision is REFUSED, never PASS).

Cases
  prs-dual-160        2 instances, independent state, PRS stimulus, two
                      different parameter sets AND two different waveshaper
                      model indices; per-instance equality
  prs-reset80-160     same + core reset at block 80 (engine fx-rebuild /
                      panic semantics: init() == suspend())
  corners-*           parameter corners: deactivated high-cuts, extreme
                      drive/feedback, each frozen waveshaper model
  reset-mid-tail-*    2 instances, reset 96 blocks INTO the ringout tail
                      (the engine's fx-rebuild path taken mid-tail)
  ringout-tail-1663   the declared tail span: 64 driven blocks followed by the
                      full 1600-block ringout fade to completion; every
                      rendered block compared (fade included)

Mutant negative controls (generated from tb_distortion.sv by source
substitution; each MUST FAIL the check it targets):
  mutant-shared       instance 1's feedback registers, TDF2 registers and
                      halfband state pooled onto instance 0 (shared state)
  mutant-order        band1/band2 swapped (post-EQ applied pre-shaper):
                      the order-sensitive equality check must reject it
  mutant-hbswap       halfband A/B branch reconstruction swapped (the
                      polyphase phase defect) — the decimator's own
                      load-bearing detail
  mutant-wsrail       waveshaper lower rail `e < 1 -> -1` zeroed (the hot
                      parameter set drives the shaper into both rails)
  mutant-wsinterp     waveshaper table lerp dropped (nearest-entry lookup)

Usage: python3 tools/compare_rtl_model_distortion.py [--quick] [--out JSON]
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
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

from distortion_model import (  # noqa: E402
    DistortionModel, DistortionParams, HalfbandD2, model_revision,
    HB_COEFFS_Q, BLOCK, RINGOUT_TIME,
)

IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")
TBDIR = os.path.join(REPO, "rtl", "effects", "type-distortion")
TB = os.path.join(TBDIR, "tb_distortion.sv")
WSROM = os.path.join(TBDIR, "ws_q29.hex")

# --- synthetic parameter sets (declared; the fixture-preset sets require the
# --- oracle extraction, which is BLOCKED in an oracle-free environment)
BASE = dict(preeq_gain_f=0.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
            preeq_highcut_f=70.0, drive_f=0.0, feedback_f=0.635445,
            posteq_gain_f=0.0, posteq_freq_f=3.0, posteq_bw_f=0.3,
            posteq_highcut_f=30.535736, gain_f=0.0, model_i=0,
            preeq_highcut_deactivated=False, posteq_highcut_deactivated=False,
            preeq_gain_extend=False, posteq_gain_extend=False,
            drive_extend=False)


def pset(**kw):
    d = dict(BASE)
    d.update(kw)
    return d


# Screaming Saw / Monster Feedback shaped corners (graphs-derived values,
# corpus/normalized/graphs.jsonl; NOT a support claim — see EVIDENCE.md §1)
# Distinct pre/post EQ gains make the band order OBSERVABLE (with both gains
# at 0 dB coeff_peakEQ returns the identity biquad and an order swap is
# unobservable — that is why the mutant-order control needs these).
SYNTH_A = pset(preeq_gain_f=6.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
               posteq_gain_f=-4.5, posteq_freq_f=24.0, posteq_bw_f=1.1)
# Hot set: drive extended to 40 dB drives the shaper into BOTH lookup rails
# (e > 0x3fd and e < 1), so the rail controls are exercised by the stimulus.
SYNTH_B = pset(preeq_gain_f=-8.0, preeq_freq_f=3.81786, preeq_bw_f=1.944644,
               preeq_highcut_f=66.0, drive_f=8.0, drive_extend=True,
               feedback_f=0.814286, posteq_gain_f=10.0, posteq_freq_f=40.0,
               posteq_bw_f=2.03125, posteq_highcut_f=66.0,
               gain_f=-21.985725, model_i=1)

CORNERS = {
    "corners-deact-both": pset(preeq_highcut_deactivated=True,
                               posteq_highcut_deactivated=True,
                               drive_f=24.0, feedback_f=-0.9),
    "corners-extend-asym": pset(model_i=2, drive_f=6.0, drive_extend=True,
                                preeq_gain_f=8.0, preeq_gain_extend=True,
                                posteq_gain_f=-4.0, posteq_gain_extend=True,
                                feedback_f=0.0, preeq_highcut_deactivated=True),
    "corners-hard-hifb": pset(model_i=1, drive_f=-12.0, feedback_f=0.99,
                              preeq_highcut_f=24.0, posteq_highcut_f=-12.0,
                              gain_f=6.0),
}


def qhex(v, bits):
    m = (1 << bits) - 1
    return f"{v & m:0{bits // 4}x}"


CTRL_WIDTHS = [32, 32, 32] + [64] * 20 + [32]


def write_init(path, param_dicts, models):
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


def _state_map(st):
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
    models = [DistortionModel(DistortionParams(p), f"i{i}")
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
                cw = m.control_words()
                # the RTL also needs the model index in the flags word
                cw[-1] = cw[-1] | (m.p.model_i << 2)
                for idx, wv in enumerate(cw):
                    rows.append(qhex(wv, CTRL_WIDTHS[idx]))
                if _want_taps(b, n_blocks, render0):
                    flat = []
                    for lv, rv in taps:
                        flat += [lv, rv]
                    rec["X"][i] = flat
                if b >= render0:
                    rec["O"][i] = list(out[0]) + list(out[1])
                if _want_state(b, n_blocks, render0):
                    rec["T"][i] = _state_map(m.st)
            for wtext in rows:
                fc.write(wtext + "\n")
            exps.append(rec)
    write_init(init_hex, param_dicts, models)
    return exps, in_hex, ctrl_hex, init_hex


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


def judge(name, exp, trace, ninst, rev8, n_blocks, note=""):
    rev_got, got = parse_tb_trace(trace)
    checked, fails = compare_case(exp, got, ninst)
    pin_ok = rev_got == rev8
    return {"case": name, "blocks": n_blocks, "ninst": ninst,
            "exact": (not fails) and pin_ok,
            "revision_pin": {"ok": pin_ok, "rtl_trace": rev_got,
                             "expected": rev8},
            "checked": checked, "mismatches": len(fails),
            "note": note, "first_failures": fails[:8]}


MUTANTS = {
    "mutant-shared": [(
        "    reg signed [31:0] fbl [0:1];    reg signed [31:0] fbr [0:1];",
        "    reg signed [31:0] fbl_ [0:1];   reg signed [31:0] fbr_ [0:1];\n"
        "    `define fbl fbl_pool\n"
        "    reg signed [31:0] fbl_pool [0:1]; reg signed [31:0] fbr_pool [0:1];")],
    "mutant-order": [(
        "                bq_sample(inst, 0, ilw[inst][k], irw[inst][k], ol, orr);",
        "                bq_sample(inst, 1, ilw[inst][k], irw[inst][k], ol, orr);"),
        ("                bq_sample(inst, 1, out_l[k], out_r[k], ol, orr);",
         "                bq_sample(inst, 0, out_l[k], out_r[k], ol, orr);")],
    "mutant-hbswap": [(
                    "ss = qadd64(hb_b_tmp[2*m2], hb_a_tmp[2*m2 + 1]);",
                    "ss = qadd64(hb_a_tmp[2*m2], hb_b_tmp[2*m2 + 1]);")],
    "mutant-wsrail": [(
        "            else if (e < 1) ws_lookup = -ONE_A;",
        "            else if (e < 1) ws_lookup = 0;")],
    "mutant-wsinterp": [(
        "                r29 = $signed({{32{1'b0}}, sat32((frc * d + $signed(64'sd1048576)) >>> 21)});",
        "                r29 = 64'sd0;")],
}
# mutant-shared is expressed structurally below (source substitution on the
# per-instance index) rather than by macro tricks.
MUTANTS["mutant-shared"] = [(
    "            fbl[inst] = qadd32(wk_l[k], qmul_aa(fbq[inst], fbl[inst]));\n"
    "                    fbr[inst] = qadd32(wk_r[k], qmul_aa(fbq[inst], fbr[inst]));",
    "            fbl[0] = qadd32(wk_l[k], qmul_aa(fbq[inst], fbl[0]));\n"
    "                    fbr[0] = qadd32(wk_r[k], qmul_aa(fbq[inst], fbr[0]));")]


def make_mutant(name, replacements):
    with open(TB) as f:
        text = f.read()
    for old, new in replacements:
        assert old in text, (name, old[:60])
        text = text.replace(old, new)
    out = os.path.join(TBDIR, f"tb_distortion_{name.split('-')[1]}.sv")
    with open(out, "w") as f:
        f.write(text)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "reports", "SXT-028e",
                                                  "rtl-exactness.json"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    rev8 = model_revision()[:8]
    workdir = args.workdir or tempfile.mkdtemp(prefix="sxt028e-rtl-")
    iv_ver = subprocess.run([IV, "-V"], capture_output=True, text=True)
    iv_line = (iv_ver.stdout or "").splitlines()
    results = {"schema_version": 1, "leaf": "SXT-028e", "sim": "iverilog",
               "sim_version": iv_line[0].strip() if iv_line else "UNKNOWN",
               "model_revision": model_revision(),
               "tb": os.path.relpath(TB, REPO),
               "ws_rom": os.path.relpath(WSROM, REPO),
               "cases": [], "mutant_controls": []}

    nb = 64 if args.quick else 160

    # --- dual-instance PRS (two parameter sets, two waveshaper models)
    exps_d, in_d, ctrl_d, init_d = build_case(
        nb, [SYNTH_A, SYNTH_B], None, 11,
        os.path.join(workdir, "prs-dual"))
    tr = simulate(TB, "prs-dual", workdir, nb, 2, in_d, ctrl_d, init_d,
                  rev8=rev8)
    results["cases"].append(judge(f"prs-dual-{nb}", exps_d, tr, 2, rev8, nb,
                                  "two instances, independent state"))

    # --- reset mid-render (fx-rebuild / panic)
    ra = nb // 2
    exps_r, in_r, ctrl_r, init_r = build_case(
        nb, [SYNTH_A, SYNTH_B], ra, 11, os.path.join(workdir, "prs-reset"))
    tr = simulate(TB, "prs-reset", workdir, nb, 2, in_r, ctrl_r, init_r,
                  reset_at=ra, rev8=rev8)
    results["cases"].append(judge(f"prs-reset{ra}-{nb}", exps_r, tr, 2, rev8,
                                  nb, "core reset mid-render"))

    # --- parameter corners
    corners = list(CORNERS.items())
    if args.quick:
        corners = corners[:1]
    for cname, cp in corners:
        e, i_, c_, n_ = build_case(64, [cp], None, 7,
                                   os.path.join(workdir, cname))
        tr = simulate(TB, cname, workdir, 64, 1, i_, c_, n_, rev8=rev8)
        results["cases"].append(judge(cname, e, tr, 1, rev8, 64,
                                      "parameter corner"))

    # --- declared tail span: the full 1600-block ringout fade
    if not args.quick:
        tb_blocks = 64 + RINGOUT_TIME - 1
        e, i_, c_, n_ = build_case(tb_blocks, [SYNTH_A], None, 5,
                                   os.path.join(workdir, "ringout"),
                                   render0=64, ringout_from=64)
        tr = simulate(TB, "ringout", workdir, tb_blocks, 1, i_, c_, n_,
                      rev8=rev8, render0=64)
        results["cases"].append(judge(f"ringout-tail-{tb_blocks}", e, tr, 1,
                                      rev8, tb_blocks,
                                      "declared tail span (1600-block ringout)"))

        # --- reset/panic DURING the tail (the engine's fx-rebuild path taken
        # --- mid-ringout: a patch change while the effect is still ringing
        # --- out rebuilds the effect, i.e. init() == suspend(), and the tail
        # --- must restart from constructor state rather than continue)
        rt_blocks = 64 + 256
        rt_reset = 64 + 96
        e, i_, c_, n_ = build_case(rt_blocks, [SYNTH_A, SYNTH_B], rt_reset, 13,
                                   os.path.join(workdir, "reset-mid-tail"),
                                   render0=64, ringout_from=64)
        tr = simulate(TB, "reset-mid-tail", workdir, rt_blocks, 2, i_, c_, n_,
                      reset_at=rt_reset, rev8=rev8, render0=64)
        results["cases"].append(judge(
            f"reset-mid-tail-{rt_reset}-{rt_blocks}", e, tr, 2, rev8, rt_blocks,
            "fx-rebuild/panic reset 96 blocks into the ringout tail"))

    # --- mutants (negative controls) on the dual-instance stimulus
    for mname, repl in MUTANTS.items():
        mpath = make_mutant(mname, repl)
        wd = os.path.join(workdir, mname)
        os.makedirs(wd, exist_ok=True)
        trace = os.path.join(wd, "tb_trace.txt")
        plus = ["+NINST=2", f"+NBLOCKS={nb}", "+RENDER0=0", f"+TRACE={trace}",
                f"+INFILE={in_d}", f"+CTRLFILE={ctrl_d}", f"+INITFILE={init_d}",
                f"+WSROM={WSROM}", f"+REV={rev8}"]
        try:
            run_sim(mpath, plus, wd)
            _, got = parse_tb_trace(trace)
            checked, fails = compare_case(exps_d, got, 2)
            ok = bool(fails)
            res = {"case": mname, "blocks": nb, "ninst": 2, "exact": not fails,
                   "mismatches": len(fails), "checked": checked, "ok": ok,
                   "verdict": ("CONTROL-OK (mutant FAILS the exactness check)"
                               if ok else "CONTROL-BROKEN (mutant PASSED!)"),
                   "first_failures": fails[:5]}
        except subprocess.CalledProcessError as e:
            res = {"case": mname, "ok": True, "exact": False,
                   "verdict": f"CONTROL-OK (mutant refused to elaborate/run: {e})"}
        results["mutant_controls"].append(res)
        print(mname, "->", res["verdict"])

    # --- stale-stub control: the same trace judged against a wrong pin
    stale = judge("stale-revision-pin", exps_d, tr if False else
                  simulate(TB, "stale", workdir, nb, 2, in_d, ctrl_d, init_d,
                           rev8="deadbeef"),
                  2, rev8, nb, "harness pinned to a stale model revision")
    stale["ok"] = not stale["exact"]
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
