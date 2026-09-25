#!/usr/bin/env python3
"""SXT-028g exactness harness: RTL trace vs frozen Phaser model trace.

CLAIM SCOPE: this tool establishes exactly ONE of the three claims of
AGENTS.md — that the RTL (rtl/effects/type-phaser/tb_phaser.sv) matches the
frozen fixed-point model (model/effects/type-phaser/phaser_model.py) with
INTEGER EQUALITY. It says NOTHING about model-vs-pinned-engine agreement
(tools/compare_phaser_reference.py, oracle-gated) and NOTHING about musical
quality.

Compared with integer equality (any mismatch = FAIL):
  * every per-instance output sample of every render block (O lines),
  * every declared checkpoint's per-instance state (T lines): dL/dR, the
    feedback + tone lipol v/dv/new_v, the widthS/mix ramp current+target,
    the tone lp/hp coefficient lags and TDF2 registers, the order-sensitive
    64-bit hash over EVERY live APF biquad state word, and the
    external-memory counters (which must stay 0 — the Phaser owns no line),
  * every cascade checkpoint (X lines): the post-stage (dL, dR) pair for
    each stage of the first four samples — this pins the cascade ORDER,
  * the frozen-revision pin (a stale trace revision is REFUSED, never PASS).

Cases:
  prs-dual-128      2 phaser instances, different params (4 and 8 stages),
                    disjoint state, serial chaining; per-instance equality
  prs-clamp-96      near-self-oscillation corner (|feedback| = 0.95, +-8
                    stimulus): the Phaser.h +-32 recursive-node clamp is live
  prs-reset48-128   same as prs-dual-128 + core reset (panic / fx rebuild)
                    before block 48
  prs-patch64-160   PATCH CHANGE MID-TAIL: input goes silent at block 48 and
                    the instance parameters change at block 64 while the tail
                    is still ringing (the tail must continue, not restart)
  prs-legacy-96     legacy branch (stages = 1) + deactivated mod rate + tone
                    deactivated, dual instance
  prs-maxstages-48  Phaser.h max_stages = 16 (32 APF biquad units)

Mutant negative controls (generated from tb_phaser.sv by source
substitution into a scratch directory; each MUST FAIL the check it targets —
a control that passes is a broken control):
  mutant-shared     the two instances' APF/dL histories pooled into one
                    (rtl/effects/tb_fx_shared_line.sv pattern)
  mutant-stageorder the APF cascade walked in reverse stage order
  mutant-lagcoef    the biquad coefficient-lag rate doubled
  mutant-noclamp    the +-32 feedback clamp removed

Usage: python3 tools/compare_rtl_model_phaser.py [--quick] [--out JSON]
Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-phaser"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

from phaser_model import (  # noqa: E402
    PhaserModel, PhaserParams, model_revision, BLOCK,
)
from corners import CORNERS  # noqa: E402

IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")
TB = os.path.join(REPO, "rtl", "effects", "type-phaser", "tb_phaser.sv")
STAGE_SAMPLES = 4
CHECK_STRIDE = 16

# Parameter corners live in ONE place (model/effects/type-phaser/corners.py)
# and are also written out as model/effects/fx_inputs/type-phaser-synth-*.json
# — SYNTHETIC corners, explicitly not preset extractions and carrying no
# support/coverage/fidelity claim.
SYNTH_A = CORNERS["synth-a"]
SYNTH_B = CORNERS["synth-b"]
SYNTH_C = CORNERS["synth-c"]
SYNTH_MAXST = CORNERS["synth-maxst"]
SYNTH_LEGACY_A = CORNERS["synth-legacy-a"]
SYNTH_LEGACY_B = CORNERS["synth-legacy-b"]
# near-self-oscillation corner: |feedback| = 0.95 with a +-8 full-scale
# stimulus drives the recursive node past the Phaser.h +-32 clamp, so the
# clamp is a LIVE path in that case (the mutant-noclamp control is scored
# against this stimulus, never against a case that never reaches it).
SYNTH_CLAMP_A = CORNERS["synth-clamp-a"]
SYNTH_CLAMP_B = CORNERS["synth-clamp-b"]
CLAMP_AMP = 8      # Q10.21 full-scale multiplier for the clamp corner


def qhex(v, bits=64):
    m = (1 << bits) - 1
    return f"{v & m:0{bits // 4}x}"


def n_units(n_stages):
    """Biquad units configured by Phaser::setvars for a stage count."""
    return 4 if n_stages < 2 else 2 * n_stages


def ctrl_words(m):
    """The control-plane record the RTL consumes for one instance/block."""
    st, p, c = m.st, m.p, m.ctrl
    nu = n_units(st.n_stages)
    flags = (int(bool(c["setvars"]))
             | (int(not p.tone_deactivated) << 1)
             | (st.n_stages << 4))
    w = [flags, c["mix_raw"], c["ws_raw"], st.feedback.new_v, st.tone.new_v]
    w += list(st.lp.tgt) + list(st.hp.tgt)
    for u in range(nu):
        w += list(st.apf[u].tgt)
    return w


def _state_map(st):
    return {
        "dl": st.dl, "dr": st.dr,
        "fbv": st.feedback.v, "fbdv": st.feedback.dv,
        "fbnew": st.feedback.new_v,
        "tonev": st.tone.v, "tonedv": st.tone.dv, "tonenew": st.tone.new_v,
        "mixc": st.mix.current, "mixt": st.mix.target,
        "wsc": st.width_s.current, "wst": st.width_s.target,
        **{f"lp{j}": st.lp.lag[j] for j in range(5)},
        **{f"hp{j}": st.hp.lag[j] for j in range(5)},
        "lpr0": st.lp.reg0[0], "lpr1": st.lp.reg1[0],
        "lpr0b": st.lp.reg0[1], "lpr1b": st.lp.reg1[1],
        "hpr0": st.hp.reg0[0], "hpr1": st.hp.reg1[0],
        "hpr0b": st.hp.reg0[1], "hpr1b": st.hp.reg1[1],
        "apfhash": st.apf_hash(),
        "er": st.ext_reads, "ew": st.ext_writes,
    }


def _capture(b, n_blocks, render0):
    return (b == render0 or b == n_blocks - 1
            or (b >= render0 and (b - render0) % CHECK_STRIDE == 0))


def build_case(wd, n_blocks, param_dicts, seed, reset_at=None,
               silence_at=None, patch_at=None, patch_dicts=None, render0=0,
               amp=1):
    """Run the frozen model over a deterministic PRS stimulus; write the RTL
    stimulus/control hex files; return the expected records.

    Also reports whether the Phaser.h +-32 feedback clamp was reached, so a
    control that targets the clamp is never scored against a stimulus that
    never exercises it."""
    os.makedirs(wd, exist_ok=True)
    models = [PhaserModel(PhaserParams(dict(p)), f"i{i}")
              for i, p in enumerate(param_dicts)]
    for m in models:
        m.initialize()
    rs = random.Random(seed)
    in_hex = os.path.join(wd, "in.hex")
    ctrl_hex = os.path.join(wd, "ctrl.hex")
    exps = []
    peak_node = 0
    with open(in_hex, "w") as fi, open(ctrl_hex, "w") as fc:
        for b in range(n_blocks):
            if silence_at is not None and b >= silence_at:
                il = [0] * BLOCK
                ir = [0] * BLOCK
            else:
                il = [rs.randint(-(amp << 21), amp << 21) for _ in range(BLOCK)]
                ir = [rs.randint(-(amp << 21), amp << 21) for _ in range(BLOCK)]
            if patch_at is not None and b == patch_at:
                for m, pd in zip(models, patch_dicts):
                    m.set_params(PhaserParams(dict(pd)))
            rec = {"b": b, "O": {}, "X": {}, "T": {}}
            prev = (il, ir)
            rows = []
            want = _capture(b, n_blocks, render0)
            for i, m in enumerate(models):
                if reset_at is not None and b == reset_at:
                    m.reset()
                for v in prev[0]:
                    fi.write(qhex(v, 32) + "\n")
                for v in prev[1]:
                    fi.write(qhex(v, 32) + "\n")
                store = []
                if want:
                    def hook(k, trace, _s=store):
                        if k < STAGE_SAMPLES:
                            _s.append(list(trace))
                    out = m.process_block(prev[0], prev[1], stage_hook=hook)
                else:
                    out = m.process_block(prev[0], prev[1])
                rows += [qhex(v) for v in ctrl_words(m)]
                rec["O"][i] = list(out[0]) + list(out[1])
                if want:
                    flat = [v for blk in store for pair in blk for v in pair]
                    rec["X"][i] = flat
                    rec["T"][i] = _state_map(m.st)
                prev = out
            for wtext in rows:
                fc.write(wtext + "\n")
            exps.append(rec)
    peak_node = sum(m.st.clamp_hits for m in models)
    return exps, in_hex, ctrl_hex, peak_node


def _int_or_none(v):
    try:
        return int(v)
    except ValueError:
        return None


def parse_tb_trace(path):
    rev = None
    o, x, t = {}, {}, {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "R":
                rev = parts[1]
            elif parts[0] == "O":
                o[(int(parts[1]), int(parts[2]))] = \
                    [_int_or_none(v) for v in parts[3:]]
            elif parts[0] == "X":
                x[(int(parts[1]), int(parts[2]))] = \
                    [_int_or_none(v) for v in parts[3:]]
            elif parts[0] == "T":
                d = {}
                for j in range(3, len(parts) - 1, 2):
                    d[parts[j]] = _int_or_none(parts[j + 1])
                t[(int(parts[1]), int(parts[2]))] = d
    return rev, {"O": o, "X": x, "T": t}


def run_sim(tb_source, plusargs, workdir):
    vvp = os.path.join(workdir, "tb.vvp")
    subprocess.run([IV, "-g2012", "-o", vvp, tb_source], check=True,
                   cwd=workdir)
    subprocess.run([VVP, vvp] + plusargs, check=True, cwd=workdir,
                   stdout=subprocess.DEVNULL)


def compare_case(exp, got, ninst, limit=20):
    fails = []
    checked = {"outputs": 0, "stage_points": 0, "checkpoints": 0, "fields": 0}
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
                            fails.append(f"b{b} i{i} out[{k}]: "
                                         f"model={a} rtl={bv}")
                            if len(fails) > limit:
                                return checked, fails
            wx = rec["X"].get(i)
            if wx is not None:
                gx = got["X"].get((b, i))
                checked["stage_points"] += len(wx)
                if gx != wx:
                    fails.append(f"b{b} i{i}: cascade checkpoint mismatch")
                    if gx is not None:
                        for kk, (a, bv) in enumerate(zip(wx, gx)):
                            if a != bv:
                                fails.append(f"  first stage diff [{kk}]: "
                                             f"model={a} rtl={bv}")
                                break
                    if len(fails) > limit:
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
                        fails.append(f"b{b} i{i} {kk}: model={want_v} "
                                     f"rtl={gt.get(kk)}")
                        if len(fails) > limit:
                            return checked, fails
    return checked, fails


def simulate(tb, wd, n_blocks, ninst, in_hex, ctrl_hex, rev8,
             reset_at=None, render0=0):
    os.makedirs(wd, exist_ok=True)
    trace = os.path.join(wd, "tb_trace.txt")
    plus = [f"+NINST={ninst}", f"+NBLOCKS={n_blocks}", f"+RENDER0={render0}",
            f"+TRACE={trace}", f"+INFILE={in_hex}", f"+CTRLFILE={ctrl_hex}",
            f"+REV={rev8}"]
    if reset_at is not None:
        plus.append(f"+RESETAT={reset_at}")
    run_sim(tb, plus, wd)
    return trace


def judge(name, exp, trace, ninst, rev8, n_blocks, note=""):
    rev_got, got = parse_tb_trace(trace)
    checked, fails = compare_case(exp, got, ninst)
    pin_ok = rev_got == rev8
    return {"case": name, "blocks": n_blocks, "ninst": ninst,
            "note": note,
            "exact": (not fails) and pin_ok,
            "revision_pin": {"ok": pin_ok, "rtl_trace": rev_got,
                             "expected": rev8},
            "checked": checked, "mismatches": len(fails),
            "first_failures": fails[:8]}


MUTANT_SUBS = {
    "mutant-shared": [(
        "    task phaser_block(input integer inst);\n        begin\n",
        "    task phaser_block(input integer inst);\n        begin\n"
        "            inst = 0;   // MUTANT: pool both instances' histories\n")],
    "mutant-stageorder": [(
        "                for (s = 0; s < nstg[inst]; s = s + 1) begin\n"
        "                    apf_sample(inst, 2*s,     dlv, dlv);\n"
        "                    apf_sample(inst, 2*s + 1, drv, drv);",
        "                for (s = nstg[inst] - 1; s >= 0; s = s - 1) begin\n"
        "                    apf_sample(inst, 2*s,     dlv, dlv);\n"
        "                    apf_sample(inst, 2*s + 1, drv, drv);")],
    "mutant-lagcoef": [(
        "    localparam signed [63:0] DLP_r  = 64'sh00000083126E979;",
        "    localparam signed [63:0] DLP_r  = 64'sh0000010624DD2F2;")],
    "mutant-noclamp": [(
        "                dlv = clipi(dlv, -CLAMP_A, CLAMP_A);\n"
        "                drv = clipi(drv, -CLAMP_A, CLAMP_A);",
        "                // MUTANT: +-32 feedback clamp removed")],
}

# which stimulus each control is scored against (a control must be run on a
# stimulus that exercises the path it targets)
MUTANT_STIM = {
    "mutant-shared": "prs-dual-128",
    "mutant-stageorder": "prs-dual-128",
    "mutant-lagcoef": "prs-dual-128",
    "mutant-noclamp": "prs-clamp-96",
}


def make_mutant(name, subs, outdir):
    with open(TB) as f:
        text = f.read()
    for old, new in subs:
        assert old in text, (name, old[:60])
        text = text.replace(old, new)
    path = os.path.join(outdir, f"tb_phaser_{name.replace('-', '_')}.sv")
    with open(path, "w") as f:
        f.write(text)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028g", "rtl-exactness.json"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    rev8 = model_revision()[:8]
    workdir = args.workdir or tempfile.mkdtemp(prefix="sxt028g-rtl-")
    try:
        sim_version = subprocess.run([IV, "-V"], capture_output=True,
                                     text=True).stdout.splitlines()[0].strip()
    except (OSError, IndexError):
        print("iverilog not available: RTL exactness is NOT_RUN "
              "(never reported as PASS)", file=sys.stderr)
        return 2

    results = {"schema_version": 1, "leaf": "SXT-028g",
               "claim": "RTL-vs-frozen-model integer equality ONLY (claim 1 "
                        "of AGENTS.md); reference agreement and musical "
                        "quality are separate claims and are NOT addressed "
                        "by this record",
               "sim": "iverilog", "sim_version": sim_version,
               "model_revision": model_revision(),
               "tb": os.path.relpath(TB, REPO),
               "cases": [], "mutant_controls": []}

    cases = [
        ("prs-dual-128", dict(n_blocks=128, param_dicts=[SYNTH_A, SYNTH_B],
                              seed=11), 2,
         "two instances, 4 and 8 stages, disjoint per-instance state"),
        ("prs-clamp-96", dict(n_blocks=96,
                              param_dicts=[SYNTH_CLAMP_A, SYNTH_CLAMP_B],
                              seed=11, amp=CLAMP_AMP), 2,
         "near-self-oscillation corner (|feedback| = 0.95, +-8 stimulus): the "
         "Phaser.h +-32 recursive-node clamp is a LIVE path here"),
        ("prs-reset48-128", dict(n_blocks=128, param_dicts=[SYNTH_A, SYNTH_B],
                                 seed=11, reset_at=48), 2,
         "panic / fx-rebuild reset before block 48"),
        ("prs-patch64-160", dict(n_blocks=160,
                                 param_dicts=[SYNTH_A, SYNTH_B], seed=5,
                                 silence_at=48, patch_at=64,
                                 patch_dicts=[SYNTH_C, dict(
                                     SYNTH_B, center_f=0.5, mix_f=1.0,
                                     mod_wave_i=2)]), 2,
         "input silent from block 48; parameters change at block 64 while "
         "the tail is still ringing (tail continues, does not restart)"),
        ("prs-legacy-96", dict(n_blocks=96,
                               param_dicts=[SYNTH_LEGACY_A, SYNTH_LEGACY_B],
                               seed=3), 2,
         "legacy branch (stages=1), deactivated mod rate on instance 1"),
        ("prs-maxstages-48", dict(n_blocks=48,
                                  param_dicts=[SYNTH_MAXST, SYNTH_C],
                                  seed=7), 2,
         "Phaser.h max_stages = 16 (32 APF biquad units) alongside a "
         "tone-deactivated 4-stage instance"),
    ]
    if args.quick:
        cases = cases[:2]

    stims = {}
    for name, kw, ninst, note in cases:
        wd = os.path.join(workdir, name)
        exp, in_hex, ctrl_hex, clamp_hits = build_case(wd, **kw)
        trace = simulate(TB, wd, kw["n_blocks"], ninst, in_hex, ctrl_hex,
                         rev8, reset_at=kw.get("reset_at"))
        res = judge(name, exp, trace, ninst, rev8, kw["n_blocks"], note)
        res["clamp_engagements"] = clamp_hits
        results["cases"].append(res)
        print(res["case"], "exact" if res["exact"] else "FAIL", res["checked"])
        stims[name] = (exp, in_hex, ctrl_hex, ninst, kw["n_blocks"],
                       clamp_hits)

    # --- negative controls: each mutant MUST FAIL the check it targets, on a
    #     stimulus that actually exercises the path the mutant breaks
    mut_dir = os.path.join(workdir, "mutants")
    os.makedirs(mut_dir, exist_ok=True)
    for mname, subs in MUTANT_SUBS.items():
        stim_name = MUTANT_STIM[mname]
        if stim_name not in stims:
            results["mutant_controls"].append(
                {"case": mname, "ok": False, "exact": None,
                 "verdict": f"NOT_RUN (stimulus {stim_name} not built)"})
            continue
        exp_d, in_d, ctrl_d, ninst, nb, clamp_hits = stims[stim_name]
        wd = os.path.join(workdir, mname)
        os.makedirs(wd, exist_ok=True)
        coverage = {"stimulus": stim_name,
                    "clamp_engagements_in_stimulus": clamp_hits}
        if mname == "mutant-noclamp" and clamp_hits == 0:
            results["mutant_controls"].append(
                {"case": mname, "ok": False, "exact": None,
                 "coverage": coverage,
                 "verdict": "CONTROL-BROKEN (stimulus never reaches the "
                            "+-32 clamp, so this control cannot fire)"})
            print(mname, "-> CONTROL-BROKEN (path never exercised)")
            continue
        try:
            mpath = make_mutant(mname, subs, mut_dir)
            trace = os.path.join(wd, "tb_trace.txt")
            run_sim(mpath, [f"+NINST={ninst}", f"+NBLOCKS={nb}", "+RENDER0=0",
                            f"+TRACE={trace}", f"+INFILE={in_d}",
                            f"+CTRLFILE={ctrl_d}", f"+REV={rev8}"], wd)
            _, got = parse_tb_trace(trace)
            checked, fails = compare_case(exp_d, got, ninst)
            ok = bool(fails)
            res = {"case": mname, "blocks": nb, "ninst": ninst,
                   "coverage": coverage,
                   "exact": not fails, "mismatches": len(fails),
                   "checked": checked, "ok": ok,
                   "verdict": ("CONTROL-OK (mutant FAILS the exactness check)"
                               if ok else "CONTROL-BROKEN (mutant PASSED!)"),
                   "first_failures": fails[:5]}
        except subprocess.CalledProcessError as e:
            res = {"case": mname, "ok": True, "exact": False,
                   "coverage": coverage,
                   "verdict": f"CONTROL-OK (mutant refused to run: {e})"}
        results["mutant_controls"].append(res)
        print(mname, "->", res["verdict"])

    ok_all = (all(c["exact"] for c in results["cases"])
              and all(m["ok"] for m in results["mutant_controls"]))
    results["status"] = "PASS" if ok_all else "FAIL"
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    print("status:", results["status"])
    if args.workdir is None:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
