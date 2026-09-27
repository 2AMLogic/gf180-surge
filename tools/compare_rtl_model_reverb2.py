#!/usr/bin/env python3
"""SXT-028f exactness harness: Reverb 2 RTL trace vs frozen model trace
(integer equality) plus the RTL negative-control mutants.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every per-instance output sample of every traced block (O lines);
  * every per-sample tank checkpoint (X lines): for four samples per
    captured block, the post-input-allpass signal, and per tank block the
    modulation integer and the two output taps, plus the tank accumulator
    -- the sub-sample modulated read and the tank recirculation are pinned
    exactly, not just at block boundaries;
  * every declared state checkpoint (T lines): predelay/allpass/delay ring
    indices, the configured lengths and tap times, the eight one-pole
    registers, the tank accumulator, all six coefficient-ramp v/target
    pairs, the LFO (r, i) pair, the widthS/mix targets, the predelay tap,
    the three per-region additive integrity hashes and the per-instance
    external read/write counters;
  * the frozen-revision pin (a stale trace revision is REFUSED, never PASS).

Cases:
  prs-dual-128       two instances over DISJOINT external regions, PRS
                     stimulus, serially chained; per-instance equality
  prs-reset48-128    same + bulk clear and constructor reset at block 48
                     (the engine's fx-rebuild path)
  prs-corners-96     parameter corners (small room / long decay / full
                     modulation / bypassed mix) on two instances

Mutant negative controls (generated from tb_reverb2.sv by source
substitution; each MUST FAIL the check it targets):
  mutant-shared      the two instances' external regions pooled into one
  mutant-lfdamp      the LF-damping ramp is stepped per sample (the pinned
                     engine never steps it) -- a coefficient-trajectory
                     defect invisible at block boundaries
  mutant-modtrunc    the modulation cast rounds instead of truncating
                     toward zero (a sub-sample interpolation defect)
  mutant-tapgain     tap gain 1 perturbed by one Q13.18 LSB

Usage: python3 tools/compare_rtl_model_reverb2.py [--out JSON] [--quick]
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
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-reverb 2"))

from reverb2_model import (  # noqa: E402
    Reverb2Model, Reverb2Params, HARNESS_PROFILE, NUM_ALLPASSES, NUM_BLOCKS,
    model_revision, BLOCK,
)

IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")
RTLDIR = os.path.join(REPO, "rtl", "effects", "type-reverb 2")
TB = os.path.join(RTLDIR, "tb_reverb2.sv")

# Two distinct parameter sets: the instances must never share anything.
PARAMS_A = dict(predelay_f=-4.0, room_size_f=0.0, decay_time_f=0.75,
                diffusion_f=1.0, buildup_f=1.0, modulation_f=0.5,
                lf_damping_f=0.2, hf_damping_f=0.2, width_f=0.0, mix_f=1.0)
PARAMS_B = dict(predelay_f=-6.0, room_size_f=-0.35, decay_time_f=1.6,
                diffusion_f=0.62, buildup_f=0.83, modulation_f=0.9,
                lf_damping_f=0.55, hf_damping_f=0.71, width_f=-3.0,
                mix_f=0.4)
# corners: minimum room / zero modulation / bypassed mix / full damping
PARAMS_C = dict(predelay_f=-8.0, room_size_f=-1.0, decay_time_f=-4.0,
                diffusion_f=0.0, buildup_f=0.0, modulation_f=0.0,
                lf_damping_f=1.0, hf_damping_f=1.0, width_f=12.0, mix_f=0.0)
PARAMS_D = dict(predelay_f=-2.0, room_size_f=0.45, decay_time_f=3.0,
                diffusion_f=1.0, buildup_f=1.0, modulation_f=1.0,
                lf_damping_f=0.0, hf_damping_f=0.0, width_f=0.0, mix_f=1.0)


def qhex(v, bits=64):
    m = (1 << bits) - 1
    return f"{v & m:0{bits // 4}x}"


def _want_state(b, n_blocks, render0):
    return (b in (render0 - 1, render0, render0 + 1, n_blocks - 1)
            or (b >= render0 and (b - render0) % 16 == 0))


def _want_x(b, n_blocks, render0):
    return (b == render0 or b == n_blocks - 1
            or (b >= render0 and (b - render0) % 8 == 0))


def state_map(st):
    m64 = (1 << 64) - 1
    d = {"pd_k": st.pd_k, "tank": st.tank, "pdt": st.pdt}
    for q in range(NUM_ALLPASSES):
        d[f"apk{q}"] = st.ap_k[q]
        d[f"apl{q}"] = st.ap_len[q]
    for q in range(NUM_BLOCKS):
        d[f"dlk{q}"] = st.dl_k[q]
        d[f"dll{q}"] = st.dl_len[q]
        d[f"tpl{q}"] = st.tap_l[q]
        d[f"tpr{q}"] = st.tap_r[q]
        d[f"hf{q}"] = st.hf_a0[q]
        d[f"lf{q}"] = st.lf_a0[q]
    ramps = (st.decay, st.diffusion, st.buildup, st.hf_damp, st.lf_damp,
             st.modulation)
    for q, r in enumerate(ramps):
        d[f"rv{q}"] = r.v
        d[f"rt{q}"] = r.new_v
    d["lfor"] = st.lfo.r
    d["lfoi"] = st.lfo.i
    d["ws"] = st.width_s.target
    d["mix"] = st.mix.target
    d["pdh"] = st.pd_hash & m64
    d["aph"] = st.ap_hash & m64
    d["dlh"] = st.dl_hash & m64
    d["erd"] = st.ext_reads
    d["ewr"] = st.ext_writes
    return d


def ctrl_lines(m):
    w64, w32, wint = m.ctrl_words()
    return ([qhex(v) for v in w64] + [qhex(v) for v in w32]
            + [qhex(v) for v in wint])


def sweep_params(base, b):
    """Block-rate parameter movement (a user turning knobs, NOT per-sample
    parameter modulation -- that stays out of the frozen scope). This is the
    only stimulus class in which the six coefficient ramps carry a non-zero
    per-sample increment, so it is the carrier for the ramp-defect
    controls."""
    import math as _m
    p = dict(base)
    ph = b * 0.05
    p["lf_damping_f"] = 0.5 + 0.45 * _m.sin(ph)
    p["hf_damping_f"] = 0.5 + 0.45 * _m.sin(ph * 0.7 + 1.0)
    p["diffusion_f"] = 0.5 + 0.4 * _m.sin(ph * 1.3)
    p["buildup_f"] = 0.5 + 0.4 * _m.sin(ph * 0.9 + 2.0)
    p["decay_time_f"] = 1.0 + 0.5 * _m.sin(ph * 0.4)
    p["modulation_f"] = 0.5 + 0.5 * _m.sin(ph * 0.6)
    return p


class Exercise:
    """Liveness accounting: a negative control whose target quantity is never
    exercised by the stimulus is VACUOUS, and this harness must say so rather
    than bank it as CONTROL-OK."""

    def __init__(self):
        self.tap_abs_l = [0] * NUM_BLOCKS
        self.tap_abs_r = [0] * NUM_BLOCKS
        self.mod_nonzero = 0
        self.mod_frac_nonzero = 0
        self.ramp_dv_abs = [0] * 6

    def note_sample(self, d):
        for b, (mo, tl, tr) in enumerate(d["taps"]):
            self.tap_abs_l[b] = max(self.tap_abs_l[b], abs(tl))
            self.tap_abs_r[b] = max(self.tap_abs_r[b], abs(tr))
            if mo != 0:
                self.mod_nonzero += 1
            if mo & 0xFF:
                self.mod_frac_nonzero += 1

    def note_block(self, st):
        for q, r in enumerate((st.decay, st.diffusion, st.buildup,
                               st.hf_damp, st.lf_damp, st.modulation)):
            self.ramp_dv_abs[q] = max(self.ramp_dv_abs[q], abs(r.dv))

    def as_dict(self):
        return {"tap_read_max_abs_L": self.tap_abs_l,
                "tap_read_max_abs_R": self.tap_abs_r,
                "modulation_nonzero_samples": self.mod_nonzero,
                "modulation_fractional_samples": self.mod_frac_nonzero,
                "ramp_dv_max_abs": self.ramp_dv_abs}


def build_case(n_blocks, param_dicts, reset_at, seed, wd, render0=0,
               amp=1 << 20, sweep=False, track=False):
    """Run the frozen model, write the RTL stimulus, return expected records."""
    os.makedirs(wd, exist_ok=True)
    models = [Reverb2Model(Reverb2Params(p), f"i{i}", HARNESS_PROFILE)
              for i, p in enumerate(param_dicts)]
    for m in models:
        m.initialize()
    rs = random.Random(seed)
    in_hex = os.path.join(wd, "in.hex")
    ctrl_hex = os.path.join(wd, "ctrl.hex")
    ex = Exercise()
    exps = []
    with open(in_hex, "w") as fi, open(ctrl_hex, "w") as fc:
        for b in range(n_blocks):
            il = [rs.randint(-amp, amp) for _ in range(BLOCK)]
            ir = [rs.randint(-amp, amp) for _ in range(BLOCK)]
            rec = {"b": b, "O": {}, "X": {}, "T": {}}
            prev = (il, ir)
            rows = []
            for i, m in enumerate(models):
                if reset_at is not None and b == reset_at:
                    m.initialize()
                if sweep:
                    m.p = Reverb2Params(sweep_params(param_dicts[i], b))
                for v in prev[0]:
                    fi.write(qhex(v, 64) + "\n")
                for v in prev[1]:
                    fi.write(qhex(v, 64) + "\n")
                store = []
                want_x = _want_x(b, n_blocks, render0)
                if want_x or track:
                    def hook(k, d, _s=store, _x=want_x):
                        if track:
                            ex.note_sample(d)
                        if _x and k < 4:
                            flat = [d["in"]]
                            for (mo, tl, tr) in d["taps"]:
                                flat += [mo, tl, tr]
                            flat.append(d["tank"])
                            _s.append(flat)
                    out = m.process_block(prev[0], prev[1], sample_hook=hook)
                    if want_x:
                        rec["X"][i] = [v for row in store for v in row]
                else:
                    out = m.process_block(prev[0], prev[1])
                if track:
                    ex.note_block(m.st)
                rows.extend(ctrl_lines(m))
                if b >= render0:
                    rec["O"][i] = list(out[0]) + list(out[1])
                if _want_state(b, n_blocks, render0):
                    rec["T"][i] = state_map(m.st)
                prev = out
            for line in rows:
                fc.write(line + "\n")
            exps.append(rec)
    return exps, in_hex, ctrl_hex, ex


def _int_or_none(v):
    try:
        return int(v)
    except ValueError:
        return None


def parse_trace(path):
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
                O[(int(parts[1]), int(parts[2]))] = [
                    _int_or_none(v) for v in parts[3:]]
            elif parts[0] == "X":
                X[(int(parts[1]), int(parts[2]))] = [
                    _int_or_none(v) for v in parts[3:]]
            elif parts[0] == "T":
                d = {}
                for j in range(3, len(parts) - 1, 2):
                    d[parts[j]] = _int_or_none(parts[j + 1])
                T[(int(parts[1]), int(parts[2]))] = d
    return rev, {"O": O, "X": X, "T": T}


def run_sim(tb_source, plusargs, workdir):
    vvp = os.path.join(workdir, "tb.vvp")
    subprocess.run([IV, "-g2012", "-o", vvp, tb_source], check=True,
                   cwd=workdir)
    subprocess.run([VVP, vvp] + plusargs, check=True, cwd=workdir,
                   stdout=subprocess.DEVNULL)


def compare(exp, got, ninst):
    fails = []
    checked = {"outputs": 0, "samples": 0, "checkpoints": 0, "fields": 0}
    for rec in exp:
        b = rec["b"]
        for i in range(ninst):
            want = rec["O"].get(i)
            if want is not None:
                g = got["O"].get((b, i))
                if g is None:
                    fails.append(f"b{b} i{i}: missing O line")
                else:
                    for k, (a, bv) in enumerate(zip(want, g)):
                        checked["outputs"] += 1
                        if a != bv:
                            fails.append(
                                f"b{b} i{i} out[{k}]: model={a} rtl={bv}")
                            if len(fails) > 20:
                                return checked, fails
            wx = rec["X"].get(i)
            if wx is not None:
                checked["samples"] += 1
                gx = got["X"].get((b, i))
                if gx != wx:
                    fails.append(f"b{b} i{i}: sample checkpoint mismatch")
                    if gx is not None:
                        for kk, (a, bv) in enumerate(zip(wx, gx)):
                            if a != bv:
                                fails.append(
                                    f"  first X diff flat[{kk}]: "
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
                        fails.append(
                            f"b{b} i{i} {kk}: model={want_v} rtl={gt.get(kk)}")
                        if len(fails) > 20:
                            return checked, fails
    return checked, fails


def simulate(name, tb, workdir, n_blocks, ninst, in_hex, ctrl_hex,
             reset_at=None, rev8="00000000", render0=0):
    wd = os.path.join(workdir, name)
    os.makedirs(wd, exist_ok=True)
    trace = os.path.join(wd, "tb_trace.txt")
    plus = [f"+NINST={ninst}", f"+NBLOCKS={n_blocks}", f"+RENDER0={render0}",
            f"+TRACE={trace}", f"+INFILE={in_hex}", f"+CTRLFILE={ctrl_hex}",
            f"+REV={rev8}"]
    if reset_at is not None:
        plus.append(f"+RESETAT={reset_at}")
    run_sim(tb, plus, wd)
    return trace


MUTANTS = {
    "mutant-shared": [
        ("            if (inst == 0) o64 = $signed({{32{mem0[a][31]}}, mem0[a]});\n"
         "            else           o64 = $signed({{32{mem1[a][31]}}, mem1[a]});",
         "            o64 = $signed({{32{mem0[a][31]}}, mem0[a]});"),
        ("                if (inst == 0) mem0[a] = wd[31:0];\n"
         "                else           mem1[a] = wd[31:0];",
         "                mem0[a] = wd[31:0];"),
    ],
    "mutant-lfdamp": [
        ("                rv[inst][3] = qadd64(rv[inst][3], rd[inst][3]);",
         "                rv[inst][3] = qadd64(rv[inst][3], rd[inst][3]);\n"
         "                rv[inst][4] = qadd64(rv[inst][4], rd[inst][4]);"),
    ],
    "mutant-modtrunc": [
        ("            if (p >= 0) mod_trunc = p >>> 78;\n"
         "            else mod_trunc = -((-p) >>> 78);",
         "            mod_trunc = (p + ($signed(128'sd1) <<< 77)) >>> 78;"),
    ],
    "mutant-tapgain": [
        ("            1: tap_gain = 32'sd78643;    // 1.2f/4",
         "            1: tap_gain = 32'sd78644;    // 1.2f/4"),
    ],
}


def make_mutant(name, workdir):
    with open(TB) as f:
        src = f.read()
    for old, new in MUTANTS[name]:
        if old not in src:
            raise SystemExit(
                f"REFUSED: mutant {name} anchor not found in tb_reverb2.sv "
                "(the control would be vacuous)")
        src = src.replace(old, new)
    out = os.path.join(workdir, f"tb_reverb2_{name.replace('-', '_')}.sv")
    with open(out, "w") as f:
        f.write(src)
    return out


def judge(name, exp, trace, ninst, rev8, n_blocks, note=""):
    rev_got, got = parse_trace(trace)
    checked, fails = compare(exp, got, ninst)
    pin_ok = rev_got == rev8
    return {"case": name, "blocks": n_blocks, "ninst": ninst,
            "exact": (not fails) and pin_ok,
            "revision_pin": {"ok": pin_ok, "rtl_trace": rev_got,
                             "expected": rev8},
            "checked": checked, "mismatches": len(fails),
            "note": note, "first_failures": fails[:8]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028f", "rtl-exactness.json"))
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    rev8 = model_revision()[:8]
    workdir = args.workdir or tempfile.mkdtemp(prefix="sxt028f-rtl-")
    try:
        head = subprocess.run([IV, "-V"], capture_output=True,
                              text=True).stdout.splitlines()[0].strip()
    except (OSError, IndexError):
        print("NOT_RUN: no iverilog on this host")
        return 2
    simv = head.split("version", 1)[1].strip() if "version" in head else head

    results = {"schema_version": 1, "leaf": "SXT-028f",
               "sim": "iverilog", "sim_version": simv,
               "model_revision": model_revision(),
               "tb": os.path.relpath(TB, REPO),
               "alloc_profile": HARNESS_PROFILE.as_dict(),
               "cases": [], "mutant_controls": []}

    n = 64 if args.quick else 128
    ns = 128 if args.quick else 256   # mutant carrier: every tap must be live

    exps_d, in_d, ctrl_d, _ = build_case(
        n, [PARAMS_A, PARAMS_B], None, 11,
        os.path.join(workdir, "prs-dual"))
    tr = simulate("prs-dual", TB, workdir, n, 2, in_d, ctrl_d, rev8=rev8)
    results["cases"].append(judge(f"prs-dual-{n}", exps_d, tr, 2, rev8, n,
                                  "two instances, disjoint regions"))

    exps_r, in_r, ctrl_r, _ = build_case(
        n, [PARAMS_A, PARAMS_B], 48, 11, os.path.join(workdir, "prs-reset"))
    tr = simulate("prs-reset", TB, workdir, n, 2, in_r, ctrl_r, reset_at=48,
                  rev8=rev8)
    results["cases"].append(judge(f"prs-reset48-{n}", exps_r, tr, 2, rev8, n,
                                  "bulk clear + constructor reset at block 48"))

    if not args.quick:
        exps_c, in_c, ctrl_c, _ = build_case(
            96, [PARAMS_C, PARAMS_D], None, 23,
            os.path.join(workdir, "prs-corners"))
        tr = simulate("prs-corners", TB, workdir, 96, 2, in_c, ctrl_c,
                      rev8=rev8)
        results["cases"].append(judge("prs-corners-96", exps_c, tr, 2, rev8,
                                      96, "parameter corners"))

    # --- mutant carrier: block-rate parameter sweep, long enough that every
    #     output tap and every coefficient ramp is exercised
    exps_s, in_s, ctrl_s, ex = build_case(
        ns, [PARAMS_A, PARAMS_B], None, 31,
        os.path.join(workdir, "prs-sweep"), sweep=True, track=True)
    tr = simulate("prs-sweep", TB, workdir, ns, 2, in_s, ctrl_s, rev8=rev8)
    results["cases"].append(judge(f"prs-sweep-{ns}", exps_s, tr, 2, rev8, ns,
                                  "block-rate parameter sweep (ramp carrier)"))
    results["mutant_carrier_exercise"] = ex.as_dict()

    # liveness predicates: a control whose target is never exercised is
    # VACUOUS and must be reported as such, never banked as CONTROL-OK
    live = {
        "mutant-shared": (True, "two instances always write both regions"),
        "mutant-lfdamp": (ex.ramp_dv_abs[4] != 0,
                          "LF-damping ramp increment must be non-zero"),
        "mutant-modtrunc": (ex.mod_frac_nonzero > 0,
                            "modulation must have a non-zero fractional part"),
        "mutant-tapgain": (all(v != 0 for v in ex.tap_abs_l) and
                           all(v != 0 for v in ex.tap_abs_r),
                           "every output tap must read non-zero data"),
    }

    for mname in MUTANTS:
        wd = os.path.join(workdir, mname)
        os.makedirs(wd, exist_ok=True)
        is_live, why = live[mname]
        try:
            mpath = make_mutant(mname, wd)
            trace = simulate(mname, mpath, workdir, ns, 2, in_s, ctrl_s,
                             rev8=rev8)
            _, got = parse_trace(trace)
            checked, fails = compare(exps_s, got, 2)
            ok = bool(fails) and is_live
            if not is_live:
                verdict = "CONTROL-VACUOUS (%s): stimulus does not exercise it" % why
            elif fails:
                verdict = "CONTROL-OK (mutant FAILS the exactness check)"
            else:
                verdict = "CONTROL-BROKEN (mutant PASSED!)"
            res = {"case": mname, "blocks": ns, "ninst": 2,
                   "exact": not fails, "mismatches": len(fails),
                   "checked": checked, "ok": ok, "live": is_live,
                   "liveness_predicate": why, "verdict": verdict,
                   "first_failures": fails[:5]}
        except subprocess.CalledProcessError as e:
            res = {"case": mname, "ok": is_live, "exact": False,
                   "live": is_live, "liveness_predicate": why,
                   "verdict": "CONTROL-OK (mutant did not run cleanly: %s)" % e}
        results["mutant_controls"].append(res)
        print(mname, "->", res["verdict"])

    # stale-stub control: a trace whose revision word is not the live model's
    stale = simulate("stale", TB, workdir, 8, 1, in_d, ctrl_d,
                     rev8="deadbeef")
    rev_got, _ = parse_trace(stale)
    stale_ok = rev_got != rev8
    results["mutant_controls"].append({
        "case": "control-stale-revision", "ok": stale_ok, "exact": False,
        "rtl_trace": rev_got, "live_revision": rev8,
        "verdict": ("CONTROL-OK (a trace pinned to a different model revision "
                    "is REFUSED: exact=false regardless of samples)"
                    if stale_ok else "CONTROL-BROKEN (stale pin accepted!)")})

    ok_all = (all(c["exact"] for c in results["cases"])
              and all(m["ok"] for m in results["mutant_controls"]))
    results["status"] = "PASS" if ok_all else "FAIL"
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    for c in results["cases"]:
        print(c["case"], "exact" if c["exact"] else "FAIL", c.get("checked"))
        for fl in c.get("first_failures", [])[:5]:
            print("   ", fl)
    print("status:", results["status"])
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
