#!/usr/bin/env python3
"""SXT-028c exactness harness: RTL trace vs frozen model trace (integer
equality) + negative-control mutants.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every per-instance output sample of every render block (O lines),
  * every declared checkpoint's per-instance state (T lines): wpos, per-voice
    time-lag state/targets, lipol targets, biquad coefficient lags, TDF2
    registers, per-instance line hash and external-memory counters,
  * every tap-interpolation checkpoint (X lines): per voice per captured
    sample the (i_dtime, sinc phase, read position) triple — the tap/interp
    path is pinned exactly, including the unmasked padding-wrap reads,
  * the frozen-revision pin (a stale trace revision is REFUSED, never PASS).

Cases:
  prs-dual-128          2 chorus instances (disjoint memories), PRS stimulus,
                        serial chaining; per-instance equality
  prs-reset48-128       same + bulk clear + core reset at block 48 (engine
                        fx-rebuild semantics)
  canonical fixtures    committed runner traces (model truth from the oracle-
                        host chain runs) replayed at the chorus boundary

Mutant negative controls (generated from tb_chorus.sv by source substitution;
each must FAIL the check it targets):
  mutant-interp         sinc phase clamp removed (wrong table phase/row)
  mutant-shared         instance memories pooled into one region
  mutant-lagramp        time-lag recurrence coefficient doubled (the
                        LFO-trajectory-class defect)

Usage: python3 tools/compare_rtl_model_chorus.py [--quick] [--out JSON]
Original to this repository (Apache-2.0).
"""

import argparse
import gzip
import json
import os
import random
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-chorus"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

from chorus_model import (  # noqa: E402
    ChorusModel, ChorusParams, model_revision, G_FMT, BLOCK,
)
from model.effects.qmath import to_q  # noqa: E402
from model.effects.delay.delay_model import db_to_linear_d  # noqa: E402

IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")
TB = os.path.join(REPO, "rtl", "effects", "type-chorus", "tb_chorus.sv")
SINC = os.path.join(REPO, "rtl", "effects", "sinc_q29.hex")
ZEROS = os.path.join(REPO, "rtl", "effects", "line_zeros.hex")
ART = os.path.join(REPO, "reports", "SXT-028c", "artifacts")

SETTLE = 375   # int(0.25 s x 48 kHz) / 32 = 375 (the fixture harness settle)
TAP_CHECK = 16

SYNTH_A = {"time_f": -6.0, "rate_f": -2.0, "depth_f": 0.35, "feedback_f": 0.4,
           "lowcut_f": -30.0, "highcut_f": 40.0, "mix_f": 0.7, "width_f": 4.0,
           "lowcut_deactivated": False, "highcut_deactivated": False}
SYNTH_B = {"time_f": -4.5, "rate_f": -3.2, "depth_f": 0.6, "feedback_f": 0.15,
           "lowcut_f": -18.0, "highcut_f": 55.0, "mix_f": 0.45, "width_f": -3.0,
           "lowcut_deactivated": False, "highcut_deactivated": False}


def init_words(p_dict):
    """The plain setvars(true) init-time lipol targets (per instance)."""
    fb = 0.5 * max(0.0, p_dict["feedback_f"]) ** 3
    return [to_q(fb, G_FMT), to_q(p_dict["mix_f"], G_FMT),
            to_q(db_to_linear_d(p_dict["width_f"]), G_FMT)]


def ctrl_words(m):
    ctrl = m.ctrl
    w = [ctrl["fb_raw"], ctrl["mix_raw"], ctrl["ws_raw"]]
    w += list(ctrl["time_tgts"])
    w += list(m.st.lp.tgt) + list(m.st.hp.tgt)
    w.append(int(ctrl["lp_on"]) | (int(ctrl["hp_on"]) << 1))
    return w


def qhex(v, bits):
    m = (1 << bits) - 1
    return f"{v & m:0{bits // 4}x}"


def _tap_hook(store):
    def hook(k, taps):
        if k < 4:
            store.append([(i, p, r) for i, p, r in taps])
    return hook


def _want_taps(b, n_blocks, settle):
    return (b in (settle - 1, settle, settle + 1, n_blocks - 1)
            or (b >= settle and (b - settle) % TAP_CHECK == 0))


def _want_state(b, n_blocks, settle):
    return (b in (settle - 1, settle, settle + 1, n_blocks - 1)
            or (b >= settle and (b - settle) % 64 == 0))


def _state_map(st):
    return {
        "wpos": st.wpos,
        **{f"tlv{j}": st.time[j].v for j in range(4)},
        **{f"tlt{j}": st.time[j].target for j in range(4)},
        "fb": st.feedback.target, "mix": st.mix.target, "ws": st.width_s.target,
        **{f"lp{j}": st.lp.lag[j] for j in range(5)},
        **{f"hp{j}": st.hp.lag[j] for j in range(5)},
        "lpr0": st.lp.reg0[0], "lpr1": st.lp.reg1[0],
        "lpr0b": st.lp.reg0[1], "lpr1b": st.lp.reg1[1],
        "hpr0": st.hp.reg0[0], "hpr1": st.hp.reg1[0],
        "hpr0b": st.hp.reg0[1], "hpr1b": st.hp.reg1[1],
        "hash": st.line_hash & ((1 << 64) - 1),
        "er": st.ext_reads, "ew": st.ext_writes,
    }


def _state_map_trace(inst):
    out = {"wpos": inst["wpos"]}
    for j in range(4):
        out[f"tlv{j}"] = inst["time_v"][j]
        out[f"tlt{j}"] = inst["time_tgt"][j]
    out["fb"] = inst["fb_tgt"]
    out["mix"] = inst["mix_tgt"]
    out["ws"] = inst["ws_tgt"]
    for j in range(5):
        out[f"lp{j}"] = inst["lp_lag"][j]
        out[f"hp{j}"] = inst["hp_lag"][j]
    out["lpr0"], out["lpr1"] = inst["lp_reg0"][0], inst["lp_reg1"][0]
    out["lpr0b"], out["lpr1b"] = inst["lp_reg0"][1], inst["lp_reg1"][1]
    out["hpr0"], out["hpr1"] = inst["hp_reg0"][0], inst["hp_reg1"][0]
    out["hpr0b"], out["hpr1b"] = inst["hp_reg0"][1], inst["hp_reg1"][1]
    out["hash"] = inst["line_hash"]
    out["er"] = inst["ext_reads"]
    out["ew"] = inst["ext_writes"]
    return out


def build_prs(n_blocks, param_dicts, reset_at, seed, wd, settle):
    """Run the frozen model over PRS stimulus; write in/ctrl/init hex;
    return expected records."""
    os.makedirs(wd, exist_ok=True)
    models = [ChorusModel(ChorusParams(p), f"i{i}")
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
            il = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
            ir = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
            rec = {"b": b, "O": {}, "X": {}, "T": {}}
            prev = (il, ir)
            rows = []
            for i, m in enumerate(models):
                if reset_at is not None and b == reset_at:
                    m.initialize()
                for v in prev[0]:
                    fi.write(qhex(v, 32) + "\n")
                for v in prev[1]:
                    fi.write(qhex(v, 32) + "\n")
                out = m.process_block(prev[0], prev[1],
                                      tap_hook=_tap_hook(store := [])) \
                    if _want_taps(b, n_blocks, settle) else m.process_block(prev[0], prev[1])
                # control words AFTER process_block: they are the words the
                # model's own control pass computed for this block
                # (fb/mix/ws + flags are 32-bit; lag targets + biquad
                # coefficients are 64-bit)
                cw = ctrl_words(m)
                for idx, wv in enumerate(cw):
                    bits = 32 if idx in (0, 1, 2, 17) else 64
                    rows.append(qhex(wv, bits))
                if _want_taps(b, n_blocks, settle):
                    flat = [v for k in store for trip in k for v in trip]
                    rec["X"][i] = flat if flat else None
                rec["O"][i] = list(out[0]) + list(out[1])
                if _want_state(b, n_blocks, settle):
                    rec["T"][i] = _state_map(m.st)
                prev = out
            for wtext in rows:
                fc.write(wtext + "\n")
            exps.append(rec)
    with open(init_hex, "w") as f:
        for p in param_dicts:
            for wv in init_words(p):
                f.write(qhex(wv, 32) + "\n")
    return exps, in_hex, ctrl_hex, init_hex


def exp_from_trace(path, n_blocks, ninst, settle=SETTLE):
    """Per-instance expected records from a committed runner trace.

    Render block k of the fixture corresponds to trace block settle+k (the
    runner replays the fixture's settle phase before the render span)."""
    with gzip.open(path, "rt") as f:
        trace = json.load(f)
    blocks = {rec["b"]: rec for rec in trace["blocks"]}
    exps = []
    for b in range(n_blocks):
        rec = blocks.get(settle + b)
        e = {"b": b, "O": {}, "X": {}, "T": {}}
        if rec is not None:
            for i, inst in enumerate(rec["instances"][:ninst]):
                if "out" in inst:
                    e["O"][i] = list(inst["out"]["L"]) + list(inst["out"]["R"])
                if inst.get("taps"):
                    flat = []
                    for k in range(4):
                        for trip in inst["taps"][k]:
                            flat += list(trip)
                    e["X"][i] = flat if flat else None
                if (settle + b) in trace["checkpoint_blocks"]:
                    e["T"][i] = _state_map_trace(inst)
        exps.append(e)
    return exps


def _int_or_x(v):
    """Mutant traces can carry 'x' (poisoned state): keep them as None so the
    comparator reports a mismatch (the control must FAIL)."""
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
                O[(int(parts[1]), int(parts[2]))] = [_int_or_x(v) for v in parts[3:]]
            elif parts[0] == "X":
                X[(int(parts[1]), int(parts[2]))] = [_int_or_x(v) for v in parts[3:]]
            elif parts[0] == "T":
                d = {}
                for j in range(3, len(parts), 2):
                    d[parts[j]] = _int_or_x(parts[j + 1])
                T[(int(parts[1]), int(parts[2]))] = d
    return rev, {"O": O, "X": X, "T": T}


def run_sim(tb_source, plusargs, workdir):
    vvp = os.path.join(workdir, "tb.vvp")
    subprocess.run([IV, "-g2012", "-o", vvp, tb_source], check=True,
                   cwd=workdir)
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
            if want is None:
                if g is not None:
                    fails.append(f"b{b} i{i}: unexpected O line")
                continue
            if g is None:
                fails.append(f"b{b} i{i}: missing O line")
                continue
            for k, (a, bv) in enumerate(zip(want, g)):
                checked["outputs"] += 1
                if a != bv:
                    fails.append(f"b{b} i{i} out[{k}]: model={a} rtl={bv}")
                    if len(fails) > 20:
                        return checked, fails
            wx = rec["X"].get(i)
            if wx is not None:
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
                    got_v = gt.get(kk)
                    if got_v != want_v:
                        fails.append(f"b{b} i{i} {kk}: model={want_v} rtl={got_v}")
                        if len(fails) > 20:
                            return checked, fails
    return checked, fails


def simulate_case(name, workdir, n_blocks, ninst, in_hex, ctrl_hex, init_hex,
                  reset_at=None, rev8="00000000", settle=SETTLE):
    wd = os.path.join(workdir, name)
    os.makedirs(wd, exist_ok=True)
    trace = os.path.join(wd, "tb_trace.txt")
    plus = [f"+NINST={ninst}", f"+NBLOCKS={n_blocks}", f"+RENDER0={settle}",
            f"+TRACE={trace}", f"+INFILE={in_hex}", f"+CTRLFILE={ctrl_hex}",
            f"+INITFILE={init_hex}", f"+SINC={SINC}", f"+ZEROS={ZEROS}",
            f"+REV={rev8}"]
    if reset_at is not None:
        plus.append(f"+RESETAT={reset_at}")
    run_sim(TB, plus, wd)
    return trace


def judge(name, exp, trace, ninst, rev8, n_blocks, ninst_r, reset_note=""):
    rev_got, got = parse_tb_trace(trace)
    checked, fails = compare_case(exp, got, ninst)
    pin_ok = rev_got == rev8
    return {"case": name, "blocks": n_blocks, "ninst": ninst,
            "exact": not fails and pin_ok,
            "revision_pin": {"ok": pin_ok, "rtl_trace": rev_got,
                             "expected": rev8},
            "checked": checked, "mismatches": len(fails),
            "first_failures": fails[:8]}


def make_mutants():
    """Generate the three mutant tb sources (negative controls)."""
    with open(TB) as f:
        src = f.read()
    out = {}
    out["mutant-interp"] = make_mutant(
        "tb_chorus_mutant_interp.sv", src,
        [("sinc_phase = clipi(scaled, 0, 255);", "sinc_phase = scaled;")])
    out["mutant-shared"] = make_mutant(
        "tb_chorus_mutant_shared.sv", src,
        [("            if (inst == 0) begin\n                if (we) begin\n"
          "                    o64 = $signed({{32{line_mem0[a][31]}}, line_mem0[a]});",
          "            if (1) begin\n                if (we) begin\n"
          "                    o64 = $signed({{32{line_mem0[a][31]}}, line_mem0[a]});")])
    out["mutant-lagramp"] = make_mutant(
        "tb_chorus_mutant_lagramp.sv", src,
        [("localparam signed [63:0] LPT_r  = 64'sh00000020C49BC00;",
          "localparam signed [63:0] LPT_r  = 64'sh00000040893B7C1;")])
    return out


def make_mutant(name, src, replacements):
    out = os.path.join(REPO, "rtl", "effects", "type-chorus", name)
    text = src
    for old, new in replacements:
        assert old in text, (name, old[:50])
        text = text.replace(old, new)
    with open(out, "w") as f:
        f.write(text)
    return out


def canonical_case(workdir, rev8, slug, seq, n_blocks, ninst, params):
    """Canonical fixture case: committed model trace + runner stimulus."""
    wd = os.path.join(workdir, f"canonical-{slug}-{n_blocks}")
    os.makedirs(wd, exist_ok=True)
    exp = exp_from_trace(os.path.join(ART, f"trace_{slug}__{seq}.json.gz"),
                         n_blocks, ninst, settle=SETTLE)
    # trim the runner stimulus to the render span (skip the settle blocks)
    per_block_in = 64 * ninst
    in_lines = open(os.path.join(ART, "rtl", f"{slug}__{seq}_in.hex")
                    ).read().splitlines()
    ctrl_lines = open(os.path.join(ART, "rtl", f"{slug}__{seq}_ctrl.hex")
                      ).read().splitlines()
    in_hex = os.path.join(wd, "in.hex")
    ctrl_hex = os.path.join(wd, "ctrl.hex")
    with open(in_hex, "w") as f:
        f.write("\n".join(in_lines[SETTLE * per_block_in:
                                        (SETTLE + n_blocks) * per_block_in]) + "\n")
    per_block_ctrl = 17 * ninst
    with open(ctrl_hex, "w") as f:
        f.write("\n".join(ctrl_lines[SETTLE * per_block_ctrl:
                                            (SETTLE + n_blocks) * per_block_ctrl]) + "\n")
    init_hex = os.path.join(wd, "init.hex")
    cfg = json.load(open(os.path.join(
        REPO, "model", "effects", "fx_inputs", f"type-chorus-{slug}.json")))
    entries = [e for e in cfg["chain"]["ains"] + cfg["chain"]["sends"]
               + cfg["chain"].get("globals", []) if e["type"] == "chorus"]
    with open(init_hex, "w") as f:
        for e in entries[:ninst]:
            for wv in init_words(e["params"]):
                f.write(qhex(wv, 32) + "\n")
    trace = simulate_case(f"canonical-{slug}", wd, n_blocks, ninst,
                          in_hex, ctrl_hex, init_hex, rev8=rev8, settle=0)
    return judge(f"canonical-{slug}-{n_blocks}b", exp, trace, ninst, rev8,
                 n_blocks, ninst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "reports", "SXT-028c",
                                                  "rtl-exactness.json"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    rev8 = model_revision()[:8]
    workdir = args.workdir or tempfile.mkdtemp(prefix="sxt028c-rtl-")
    results = {"schema_version": 1, "leaf": "SXT-028c",
               "sim": "iverilog",
               "sim_version": subprocess.run([IV, "-V"], capture_output=True,
                                             text=True).stdout.split()[1],
               "model_revision": model_revision(),
               "tb": os.path.relpath(TB, REPO),
               "cases": [], "mutant_controls": []}

    # --- canonical cases come first when artifacts exist (ONE canonical per
    # claim; committed runner traces are the model truth)
    canonicals = []
    for slug, seq, nb in (("fmcombo", "seq-notes-coverage-v1", 512),
                          ("fmtwang2", "seq-notes-coverage-v1", 256),
                          ("alienappears", "seq-notes-coverage-v1", 256)):
        tp = os.path.join(ART, f"trace_{slug}__{seq}.json.gz")
        if os.path.exists(tp):
            cfg = json.load(open(os.path.join(
                REPO, "model", "effects", "fx_inputs",
                f"type-chorus-{slug}.json")))
            entries = [e for e in cfg["chain"]["ains"] + cfg["chain"]["sends"]
                       + cfg["chain"].get("globals", [])
                       if e["type"] == "chorus"]
            canonicals.append((slug, seq, nb, len(entries)))
    if args.quick:
        canonicals = canonicals[:1]

    # --- PRS cases
    exps_d, in_d, ctrl_d, init_d = build_prs(
        128, [SYNTH_A, SYNTH_B], None, 11,
        os.path.join(workdir, "prs-dual-128"), settle=0)
    trace_d = simulate_case("prs-dual-128", workdir, 128, 2,
                            in_d, ctrl_d, init_d, rev8=rev8, settle=0)
    results["cases"].append(judge("prs-dual-128", exps_d, trace_d, 2, rev8,
                                  128, 2))

    exps_r, in_r, ctrl_r, init_r = build_prs(
        128, [SYNTH_A, SYNTH_B], 48, 11,
        os.path.join(workdir, "prs-reset48-128"), settle=0)
    trace_r = simulate_case("prs-reset48-128", workdir, 128, 2,
                            in_r, ctrl_r, init_r, reset_at=48, rev8=rev8,
                            settle=0)
    results["cases"].append(judge("prs-reset48-128", exps_r, trace_r, 2, rev8,
                                  128, 2))

    # --- canonical fixture cases (committed model traces as truth)
    for slug, seq, nb, ninst in canonicals:
        res = canonical_case(workdir, rev8, slug, seq, nb, ninst, None)
        results["cases"].append(res)
        print(res["case"], "exact" if res["exact"] else "FAIL",
              res.get("checked", ""))

    # --- mutants (negative controls) on the dual-instance PRS stimulus
    for mname, mpath in make_mutants().items():
        wd = os.path.join(workdir, mname)
        os.makedirs(wd, exist_ok=True)
        trace = os.path.join(wd, "tb_trace.txt")
        plus = ["+NINST=2", "+NBLOCKS=128", f"+RENDER0={SETTLE}",
                f"+TRACE={trace}", f"+INFILE={in_d}", f"+CTRLFILE={ctrl_d}",
                f"+INITFILE={init_d}", f"+SINC={SINC}", f"+ZEROS={ZEROS}",
                f"+REV={rev8}"]
        try:
            run_sim(mpath, plus, wd)
            _, got = parse_tb_trace(trace)
            checked, fails = compare_case(exps_d, got, 2)
            ok = bool(fails)   # the control MUST fail
            res = {"case": mname, "blocks": 128, "ninst": 2,
                   "exact": not fails, "mismatches": len(fails),
                   "checked": checked,
                   "verdict": ("CONTROL-OK (mutant FAILS the exactness check)"
                               if ok else
                               "CONTROL-BROKEN (mutant PASSED!)"),
                   "ok": ok, "first_failures": fails[:5]}
        except subprocess.CalledProcessError as e:
            res = {"case": mname, "ok": True,
                   "verdict": "CONTROL-OK (mutant refused to run cleanly "
                              "counts as failing the check: %s)" % e,
                   "exact": False}
        results["mutant_controls"].append(res)
        print(mname, "->", res["verdict"])

    ok_all = all(c["exact"] for c in results["cases"]) and \
        all(m["ok"] for m in results["mutant_controls"])
    results["status"] = "PASS" if ok_all else "FAIL"
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    for c in results["cases"]:
        print(c["case"], "exact" if c["exact"] else "FAIL",
              c.get("checked", ""))
    print("status:", results["status"])
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
