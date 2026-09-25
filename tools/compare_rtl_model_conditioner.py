#!/usr/bin/env python3
"""SXT-028b exactness harness: Conditioner RTL vs the frozen model.

Claim (1) ONLY: rtl/effects/type-conditioner/tb_conditioner.sv reproduces
model/effects/type-conditioner/conditioner_model.py with INTEGER EQUALITY on
every output sample of every block of every instance, and on every declared
per-block checkpoint field (bufpos, envelope trackers, gain, the four lipol
cur/tgt pairs, the 15 biquad coefficient lags + channel-0 TDF2 registers,
and a position-weighted hash over the look-ahead ring and squared-peak
leaves). It says nothing about agreement with the pinned Surge engine
(claim 2 is BLOCKED on this host: no oracle checkout, no surgepy).

Stimuli are synthetic (seeded PRS noise with a stepped loudness envelope
that drives the limiter into gain reduction); parameters are the corners of
tools/conditioner_corners.py (loader defaults, all-min, all-max, and the
four fixture presets' stored values from graphs.jsonl). Lifecycle is driven
through the model's Effect::process_ringout, so the ring-out tail
(99 process() blocks, then process_only_control), a resume after
control-only, an engine suspend (stopSound/panic) mid-tail and a fresh
re-spawn (patch change) mid-tail are all inside the exactness check.

A case PASSes only if: every compared field is equal, the trace carries the
live frozen-model revision (stale -> REFUSED), and -- for cases that declare
a tail -- the compared blocks cover the declared tail span
(conditioner_model.tail_coverage_check).

Negative controls (each must FAIL the check it targets; a passing control
is a broken control):
  mutant-shared     RTL with the two instances' look-ahead ring, leaves,
                    bufpos and envelope pooled into instance 0 (the
                    tb_fx_shared_line pattern) -> dual-instance exactness
  mutant-nolimiter  RTL with the compressor gain forced to 1.0 -> exactness
  permuted-slots    correct RTL, the two slots' parameter/control content
                    swapped (tools/ablate_fx.py permute pattern) -> exactness
  stale-stub        correct RTL, trace revision word != live model -> REFUSED
  dropped-tail      correct RTL, run stopped before the declared tail span
                    -> tail-coverage check FAILS although every compared
                    block matches

Usage: python3 tools/compare_rtl_model_conditioner.py [--out JSON] [--quick]
Original to this repository (Apache-2.0).
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-conditioner"))

from conditioner_model import (  # noqa: E402
    ConditionerModel, ConditionerParams, model_revision, tail_coverage_check,
    BLOCK, CTRL_WORDS, FLAG_CONTROL_ONLY,
)
from conditioner_corners import all_corners  # noqa: E402

IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")
RTL_DIR = os.path.join(REPO, "rtl", "effects", "type-conditioner")
TB = os.path.join(RTL_DIR, "tb_conditioner.sv")
ONE_A = 1 << 21

# second instance of the lifecycle case: every stage active, side HP at a
# musical frequency, fast attack / slow release, off-centre balance
SYNTH_B = {"bass_db": -4.5, "treble_db": 7.25, "width_f": 0.6,
           "balance_f": -0.35, "threshold_db": -20.0, "attack_f": 0.8,
           "release_f": -0.6, "gain_db": -3.0, "hpwidth_semitones": 12.0,
           "bass_deactivated": False, "treble_deactivated": False,
           "hpwidth_deactivated": False}


def qhex(v, bits=64):
    return f"{v & ((1 << bits) - 1):0{bits // 4}x}"


class Stim:
    """Seeded stereo PRS noise with a stepped loudness envelope (8-block
    segments at 0.05 / 0.3 / 1.0 / 2.2 x full scale) and a shared L=R
    component so the M/S path carries both mid and side energy."""

    LEVELS = (0.05, 0.3, 1.0, 2.2)

    def __init__(self, seed):
        self.rs = random.Random(seed)

    def block(self, b, present):
        if not present:
            return [0] * BLOCK, [0] * BLOCK
        amp = int(self.LEVELS[(b // 8) % len(self.LEVELS)] * ONE_A)
        ls, rs_ = [], []
        for _ in range(BLOCK):
            c = self.rs.randint(-amp, amp) // 2
            ls.append(max(-(1 << 31), min((1 << 31) - 1,
                                          c + self.rs.randint(-amp, amp) // 2)))
            rs_.append(max(-(1 << 31), min((1 << 31) - 1,
                                           c + self.rs.randint(-amp, amp) // 2)))
        return ls, rs_


def build_case(name, params_list, present, events, seed, wd):
    """Run the model through Effect::process_ringout; write the RTL stimulus
    (in.hex, ctrl.hex) and return the expected per-block records."""
    os.makedirs(wd, exist_ok=True)
    models = [ConditionerModel(ConditionerParams(dict(p)), f"i{i}")
              for i, p in enumerate(params_list)]
    for m in models:
        m.initialize()
    stims = [Stim(seed * 10 + i) for i in range(len(models))]
    exps, ctrl_recs = [], []
    cov = {"process_blocks": 0, "control_only_blocks": 0, "suspends": 0,
           "fresh_respawns": 0, "min_gain_q43": 1 << 43,
           "blocks_with_gain_reduction": 0}
    in_hex = os.path.join(wd, "in.hex")
    ctrl_hex = os.path.join(wd, "ctrl.hex")
    with open(in_hex, "w") as fi:
        for b, pres in enumerate(present):
            rec = {"b": b, "O": {}, "T": {}}
            crec = []
            for i, m in enumerate(models):
                ev = events.get(b, {}).get(i)
                if ev == "suspend":
                    m.suspend()
                    cov["suspends"] += 1
                elif ev == "fresh":
                    m.initialize()
                    cov["fresh_respawns"] += 1
                il, ir = stims[i].block(b, pres)
                for v in il + ir:
                    fi.write(qhex(v) + "\n")
                ol, orr, processed = m.process_ringout(il, ir, pres)
                cw = list(m.ctrl)
                assert bool(cw[-1] & FLAG_CONTROL_ONLY) == (not processed)
                crec.append(cw)
                cov["process_blocks" if processed else "control_only_blocks"] += 1
                if m.st.gain < (1 << 43):
                    cov["blocks_with_gain_reduction"] += 1
                cov["min_gain_q43"] = min(cov["min_gain_q43"], m.st.gain)
                rec["O"][i] = ol + orr
                rec["T"][i] = m.st.checkpoint()
            exps.append(rec)
            ctrl_recs.append(crec)
    write_ctrl(ctrl_hex, ctrl_recs)
    cov["min_gain"] = cov["min_gain_q43"] / float(1 << 43)
    h = hashlib.sha256(json.dumps(exps, sort_keys=True).encode()).hexdigest()
    return exps, in_hex, ctrl_hex, ctrl_recs, cov, h


def write_ctrl(path, ctrl_recs, permute=False):
    with open(path, "w") as fc:
        for crec in ctrl_recs:
            order = list(reversed(crec)) if permute else crec
            for cw in order:
                assert len(cw) == CTRL_WORDS
                for w in cw:
                    fc.write(qhex(w) + "\n")


def _int(v):
    try:
        return int(v)
    except ValueError:
        return None


def parse_trace(path):
    rev, O, T = None, {}, {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "R":
                rev = parts[1]
            elif parts[0] == "O":
                O[(int(parts[1]), int(parts[2]))] = [_int(v) for v in parts[3:]]
            elif parts[0] == "T":
                T[(int(parts[1]), int(parts[2]))] = {
                    parts[j]: _int(parts[j + 1]) for j in range(3, len(parts), 2)}
    return rev, O, T


def compare(exps, trace, ninst, n_blocks):
    rev, O, T = parse_trace(trace)
    fails = []
    checked = {"blocks": 0, "output_samples": 0, "checkpoint_fields": 0}
    for rec in exps[:n_blocks]:
        b = rec["b"]
        checked["blocks"] += 1
        for i in range(ninst):
            got = O.get((b, i))
            if got is None:
                fails.append(f"b{b} i{i}: missing O line")
                continue
            for k, (w, g) in enumerate(zip(rec["O"][i], got)):
                checked["output_samples"] += 1
                if w != g:
                    fails.append(f"b{b} i{i} out[{k}] model={w} rtl={g}")
            gt = T.get((b, i), {})
            for key, w in rec["T"][i].items():
                checked["checkpoint_fields"] += 1
                if gt.get(key) != w:
                    fails.append(f"b{b} i{i} {key} model={w} rtl={gt.get(key)}")
    return rev, checked, fails


def run_sim(tb_source, wd, ninst, n_blocks, in_hex, ctrl_hex, rev8):
    os.makedirs(wd, exist_ok=True)
    vvp = os.path.join(wd, "tb.vvp")
    trace = os.path.join(wd, "tb_trace.txt")
    subprocess.run([IV, "-g2012", "-o", vvp, tb_source], check=True, cwd=wd)
    subprocess.run([VVP, vvp, f"+NINST={ninst}", f"+NBLOCKS={n_blocks}",
                    f"+TRACE={trace}", f"+INFILE={in_hex}",
                    f"+CTRLFILE={ctrl_hex}", f"+REV={rev8}"],
                   check=True, cwd=wd, stdout=subprocess.DEVNULL)
    return trace


def judge(case, exps, trace, ninst, n_blocks, rev8, last_present=None):
    rev, checked, fails = compare(exps, trace, ninst, n_blocks)
    pin_ok = rev == rev8
    res = {"case": case, "ninst": ninst, "blocks_compared": n_blocks,
           "checked": checked, "mismatches": len(fails),
           "first_mismatches": fails[:6],
           "revision_pin": {"ok": pin_ok, "trace": rev, "expected": rev8}}
    tail_ok = True
    if last_present is not None:
        tail_ok, required = tail_coverage_check(n_blocks, last_present)
        res["tail_coverage"] = {"ok": tail_ok, "required_blocks": required,
                                "last_input_present_block": last_present}
    if not pin_ok:
        res["status"] = "REFUSED (stale frozen-model revision)"
    elif fails:
        res["status"] = "FAIL"
    elif not tail_ok:
        res["status"] = "FAIL (declared tail span not covered)"
    else:
        res["status"] = "PASS"
    return res


def make_mutant(fname, replacements):
    with open(TB) as f:
        text = f.read()
    for old, new in replacements:
        assert old in text, (fname, old)
        text = text.replace(old, new)
    path = os.path.join(RTL_DIR, fname)
    with open(path, "w") as f:
        f.write("// GENERATED negative-control mutant of tb_conditioner.sv by\n"
                "// tools/compare_rtl_model_conditioner.py -- must FAIL exactness.\n"
                + text)
    return path


def mutants():
    pooled = [(f"{arr}[inst]", f"{arr}[0]") for arr in
              ("dly_l", "dly_r", "lamax", "bufpos", "flam", "flam2", "gain_r")]
    return {
        "mutant-shared": make_mutant("tb_conditioner_mutant_shared.sv", pooled),
        "mutant-nolimiter": make_mutant(
            "tb_conditioner_mutant_nolimiter.sv",
            [("gain_r[inst] = recip_c(flam2[inst]);", "gain_r[inst] = ONE_C;")]),
    }


def lifecycle_schedule():
    present = [True] * 40 + [False] * 110 + [True] * 20 + [False] * 30
    events = {180: {0: "suspend", 1: "fresh"}}
    return present, events, 39


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "reports", "SXT-028b",
                                                  "rtl-exactness.json"))
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    rev_full = model_revision()
    rev8 = rev_full[:8]
    wd = args.workdir or tempfile.mkdtemp(prefix="sxt028b-rtl-")
    ivv = subprocess.run([IV, "-V"], capture_output=True, text=True).stdout.split("\n")[0]
    corners = {n: (p, prov) for n, p, prov in all_corners()}
    out = {"schema_version": 1, "leaf": "SXT-028b", "claim": "RTL == frozen "
           "model (claim 1) only; no reference-agreement claim",
           "simulator": ivv, "tb": os.path.relpath(TB, REPO),
           "model_revision": rev_full, "cases": [], "controls": []}

    # ---- case 1: dual-instance lifecycle (tails, resume, suspend, fresh)
    present, events, last_present = lifecycle_schedule()
    pl = [corners["doomsday-slot06"][0], SYNTH_B]
    exps, in_hex, ctrl_hex, crecs, cov, h = build_case(
        "dual-lifecycle", pl, present, events, 1, os.path.join(wd, "life"))
    n = len(present)
    tr = run_sim(TB, os.path.join(wd, "life"), 2, n, in_hex, ctrl_hex, rev8)
    r = judge("dual-lifecycle", exps, tr, 2, n, rev8, last_present)
    r.update(params=["doomsday-slot06", "SYNTH_B"], coverage=cov,
             expected_trace_sha256=h,
             schedule={"input_present_blocks": "0-39, 150-169",
                       "events": {"180": {"inst0": "engine suspend (stopSound/"
                                          "panic) mid-tail",
                                          "inst1": "fresh re-spawn (patch "
                                          "change) mid-tail"}}})
    out["cases"].append(r)
    print(r["case"], r["status"], r["checked"], cov)
    life = (exps, in_hex, ctrl_hex, crecs, n, last_present)

    # ---- cases 2-4: parameter corners (2 instances each)
    pairs = [("loader-defaults", "extreme-min"), ("extreme-max", "aoe-slot00"),
             ("computerlanguage1-slot00", "piercing-slot07")]
    cpresent = [True] * 24 + [False] * 24
    for ci, (a, bname) in enumerate(pairs):
        name = f"corners-{a}+{bname}"
        cwd = os.path.join(wd, f"corners{ci}")
        exps_c, ih, ch, _, cov_c, hc = build_case(
            name, [corners[a][0], corners[bname][0]], cpresent, {}, 10 + ci, cwd)
        tr = run_sim(TB, cwd, 2, len(cpresent), ih, ch, rev8)
        rc = judge(name, exps_c, tr, 2, len(cpresent), rev8)
        rc.update(params=[a, bname], coverage=cov_c, expected_trace_sha256=hc,
                  provenance=[corners[a][1], corners[bname][1]])
        out["cases"].append(rc)
        print(name, rc["status"], rc["checked"])
        if ci == 0:
            stale_src = (exps_c, ih, ch, cwd)

    # ---- negative controls ------------------------------------------------
    exps, in_hex, ctrl_hex, crecs, n, last_present = life
    for mname, mpath in mutants().items():
        mwd = os.path.join(wd, mname)
        tr = run_sim(mpath, mwd, 2, n, in_hex, ctrl_hex, rev8)
        rm = judge(mname, exps, tr, 2, n, rev8, last_present)
        out["controls"].append(_control(mname, rm, "exactness",
                                        os.path.relpath(mpath, REPO)))

    pwd = os.path.join(wd, "permuted")
    os.makedirs(pwd, exist_ok=True)
    pctrl = os.path.join(pwd, "ctrl.hex")
    write_ctrl(pctrl, crecs, permute=True)
    tr = run_sim(TB, pwd, 2, n, in_hex, pctrl, rev8)
    out["controls"].append(_control(
        "permuted-slots", judge("permuted-slots", exps, tr, 2, n, rev8, last_present),
        "order-sensitive exactness", None))

    exps_c, ih, ch, cwd = stale_src
    stale = f"{int(rev8, 16) ^ 0x5a5a5a5a:08x}"
    tr = run_sim(TB, os.path.join(wd, "stale"), 2, len(cpresent), ih, ch, stale)
    out["controls"].append(_control(
        "stale-stub", judge("stale-stub", exps_c, tr, 2, len(cpresent), rev8),
        "revision pin", None))

    short = tail_coverage_check(0, last_present)[1] - 20
    tr = run_sim(TB, os.path.join(wd, "dropped"), 2, short, in_hex, ctrl_hex, rev8)
    rd = judge("dropped-tail", exps, tr, 2, short, rev8, last_present)
    out["controls"].append(_control("dropped-tail", rd, "tail coverage", None))

    cases_ok = all(c["status"] == "PASS" for c in out["cases"])
    controls_ok = all(c["ok"] for c in out["controls"])
    out["status"] = "PASS" if cases_ok and controls_ok else "FAIL"
    out["cases_status"] = "PASS" if cases_ok else "FAIL"
    out["controls_status"] = "PASS" if controls_ok else "FAIL (broken control)"
    for c in out["controls"]:
        print(c["control"], "->", c["verdict"])
    print("status:", out["status"])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0 if out["status"] == "PASS" else 1


def _control(name, res, target, mutant_path):
    failed = res["status"] != "PASS"
    return {"control": name, "targets": target, "mutant_tb": mutant_path,
            "check_result": res["status"], "mismatches": res["mismatches"],
            "tail_coverage": res.get("tail_coverage"),
            "revision_pin": res["revision_pin"],
            "first_mismatches": res["first_mismatches"][:3],
            "ok": failed,
            "verdict": ("CONTROL-OK (fails the check it targets: "
                        f"{res['status']})" if failed else
                        "CONTROL-BROKEN (control PASSED the check)")}


if __name__ == "__main__":
    sys.exit(main())
