#!/usr/bin/env python3
"""SXT-028a: RTL-vs-frozen-model EXACTNESS runner (issue #53 acceptance:
"RTL matches the frozen fixed-point model exactly").

Generates stimulus for rtl/effects/aw-49/tb_galactic.sv from the frozen
fixed-point model (model/effects/aw-49/galactic_model.py), runs iverilog,
and compares -- with exact integer equality:

  1. every s32i output word of every block,
  2. every per-block checkpoint (countM, 12 line counters, iirA/iirB,
     8 feedback registers),
  3. every external-memory transaction (R/W addr + data, issue order),
  4. the final external-memory image (canonical case),
  5. the FROZEN-REVISION pin: the stimulus embeds the model file's sha256
     word; the tb echoes it into the trace header - a stale harness (trace
     missing/mismatched) refuses to report PASS,
  6. the dual-instance schedule: two instances time-multiplexed through one
     core with disjoint memory regions keep independent histories,
  7. injected-defect MUTANTS must FAIL the comparison:
       - wrong-coefficient (regen halved in the RTL), and
       - shared-memory (mem_base dropped: both instances pool one region)
     a mutant that passes is a broken control (finding).

NO_VERDICT when iverilog is absent. Exit 0 iff all real cases match exactly
and both mutants fail.

Usage: python3 tools/compare_rtl_model_aw49.py [--keep] [--smoke-only]
Original to this repository (Apache-2.0).
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-49"))

import galactic_model as gm  # noqa: E402

RTL_DIR = os.path.join(REPO, "rtl", "effects", "aw-49")
OUT = os.path.join(REPO, "reports", "sxt-028a")
FIXTURES = os.path.join(OUT, "fixtures")
CANONICAL_NPZ = os.path.join(FIXTURES, "temple__seq-notes-coverage-v1-aw49-taps.npz")


class ExtLog:
    """External-memory logging hooks mirroring the RTL harness log format."""

    def __init__(self, model):
        self.model = model
        self.lines = []

    def read(self, addr):
        v = self.model._ext(addr)
        self.lines.append(f"R {addr} {v}")
        return v

    def write(self, addr, val):
        self.model._ext(addr, val)
        self.lines.append(f"W {addr} {val}")

    def reset_marker(self):
        self.lines.append("X RESET")


def coefficient_words(ctrl, n_instances=2):
    w = []
    rev = int(gm.frozen_revision()[:8], 16)
    w.append(rev)
    w.append(ctrl["regen"] & 0xFFFFFFFF)
    w.append(ctrl["attenuate"] & 0xFFFFFFFF)
    w.append(ctrl["lowpass"] & 0xFFFFFFFF)
    w.append(ctrl["lowpass_m1"] & 0xFFFFFFFF)
    w.append(ctrl["wet"] & 0xFFFFFFFF)
    w.append(ctrl["wet_m1"] & 0xFFFFFFFF)
    w.append(1 if ctrl["wet_active"] else 0)
    for n in ("I", "J", "K", "L", "A", "B", "C", "D", "E", "F", "G", "H"):
        w.append(ctrl["delays"][n] & 0xFFFFFFFF)
    w.append(gm.EXT_WORDS & 0xFFFFFFFF)
    assert len(w) == 21
    return w


def write_hex_words(path, words):
    with open(path, "w") as f:
        for w in words:
            f.write(f"{w & 0xFFFFFFFF:08x}\n")


class CaseModel:
    """Model driver with control-word + trace capture."""

    def __init__(self, ctrl, vib=None, mem_base=0):
        self.model = gm.Galactic49Fixed(ctrl, vib=vib, mem_base=mem_base)
        self.model.log_ctrl = []
        self.stim = []
        self.log = ExtLog(self.model)
        self.model.attach_ext_memory(self.log.read, self.log.write)
        self.trace = []

    def block(self, idx, in_l, in_r):
        m = self.model
        m.log_ctrl = []
        ol, orr = m.process_block(list(in_l), list(in_r))
        ck = m.checkpoint()
        line = [f"T {idx} {ck['counts']['M'] if 'M' in ck['counts'] else m.counts['M']}"]
        line.append(str(ck["counts"]["M"]))
        for n in ("I", "J", "K", "L", "A", "B", "C", "D", "E", "F", "G", "H"):
            line.append(str(ck["counts"][n]))
        line += [str(ck["iir_a"]["L"]), str(ck["iir_a"]["R"]),
                 str(ck["iir_b"]["L"]), str(ck["iir_b"]["R"])]
        for k in ("AL", "BL", "CL", "DL", "AR", "BR", "CR", "DR"):
            line.append(str(ck["fb"][k]))
        self.trace.append(" ".join(line) + "\n")
        self.trace.append("O %d " % idx + " ".join(str(v) for v in ol + orr) + "\n")
        # stimulus words: 32 x (inL, inR, baseL, fracL, baseR, fracR)
        words = []
        ctrl = m.log_ctrl
        assert len(ctrl) == gm.BLOCK
        for i in range(gm.BLOCK):
            b_l, f_l, b_r, f_r = ctrl[i]
            words += [in_l[i], in_r[i], b_l, f_l, b_r, f_r]
        return words, (ol, orr)


def prs_blocks(n_blocks, seed=20260922, scale=(1 << 24)):
    rs = np.random.RandomState(seed)
    v = rs.randint(-scale, scale, size=(n_blocks * gm.BLOCK * 2,))
    return v[0::2].astype(int), v[1::2].astype(int)


def run_iverilog(workdir, core_src, tb_src):
    cmd = f"iverilog -g2012 -s tb_galactic -o sim.out {core_src} {tb_src}"
    r = subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"iverilog compile failed: {r.stderr[-2000:]}")
    r = subprocess.run(["./sim.out"], cwd=workdir, capture_output=True, text=True,
                       timeout=7200)
    if r.returncode != 0:
        raise RuntimeError(f"sim failed: {r.stderr[-2000:]}\n{r.stdout[-500:]}")


def parse_trace(path):
    R, T, O = [], [], []
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "R":
                R.append(int(p[1]))
            elif p[0] == "T":
                T.append([int(v) for v in p[1:]])
            elif p[0] == "O":
                O.append([int(v) for v in p[1:]])
    return R, T, O


def parse_trace_text(text):
    R, T, O = [], [], []
    for line in text.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "R":
            R.append(int(p[1]))
        elif p[0] == "T":
            T.append([int(v) for v in p[1:]])
        elif p[0] == "O":
            O.append([int(v) for v in p[1:]])
    return R, T, O


def parse_txns(path):
    out = []
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "X":
                out.append(("X",))
            else:
                out.append((p[0], int(p[1]), int(p[2])))
    return out


def parse_txn_text(lines):
    out = []
    for line in lines:
        p = line.split()
        if not p:
            continue
        if p[0] == "X":
            out.append(("X",))
        else:
            out.append((p[0], int(p[1]), int(p[2])))
    return out


def parse_mem(path, words):
    vals = []
    with open(path) as f:
        for line in f:
            vals.append(int(line.strip(), 16))
    assert len(vals) == words, (len(vals), words)
    return vals


def sha(lines):
    h = hashlib.sha256()
    for x in lines:
        h.update(("|".join(str(y) for y in x) + "\n").encode())
    return h.hexdigest()


def compare_case(name, model_trace, model_txn, model_mem, workdir, want_mem):
    rrev, rtl_T, rtl_O = parse_trace(os.path.join(workdir, "out/aw-49/rtl/tb_trace.txt"))
    mrev, mod_T, mod_O = parse_trace_text(model_trace)
    res = {"case": name, "claim": "RTL-vs-frozen-model EXACT"}
    res["blocks"] = len(mod_T)
    res["outputs_exact"] = rtl_O == mod_O
    res["checkpoints_exact"] = rtl_T == mod_T
    rtl_txn = parse_txns(os.path.join(workdir, "out/aw-49/rtl/txn_rtl.txt"))
    mod_txn = parse_txn_text(model_txn)
    res["txn_log_exact"] = rtl_txn == mod_txn
    res["txn_lines_rtl"] = len(rtl_txn)
    res["txn_log_sha256"] = {"rtl": sha(rtl_txn), "model": sha(mod_txn)}
    reads = sum(1 for t in rtl_txn if t[0] == "R")
    writes = sum(1 for t in rtl_txn if t[0] == "W")
    res["rtl_measured_traffic"] = {
        "reads": reads, "writes": writes,
        "words_per_frame": (reads + writes) // max(len(mod_T), 1),
    }
    # frozen-revision pin (stale harness control)
    expected_rev = int(gm.frozen_revision()[:8], 16)
    res["revision_pin"] = {
        "expected": expected_rev, "rtl_trace": (rrev[0] if rrev else None),
        "ok": bool(rrev and rrev[0] == expected_rev),
    }
    if want_mem:
        mv = parse_mem(os.path.join(workdir, "out/aw-49/rtl/mem_rtl.hex"), gm.EXT_WORDS * 2)
        res["ext_mem_exact"] = mv == model_mem
    else:
        res["ext_mem_exact"] = None
    res["exact"] = (res["outputs_exact"] and res["checkpoints_exact"]
                    and res["txn_log_exact"]
                    and res["revision_pin"]["ok"]
                    and (res["ext_mem_exact"] is not False))
    return res


def build_case_stimulus(workdir, ctrl, cases_models, reset_blocks=()):
    """cases_models: list of CaseModel already run; writes cfg+blocks hex."""
    os.makedirs(os.path.join(workdir, "rtl/effects/aw-49/sim"), exist_ok=True)
    os.makedirs(os.path.join(workdir, "out/aw-49/rtl"), exist_ok=True)
    write_hex_words(os.path.join(workdir, "rtl/effects/aw-49/sim/cfg.hex"),
                    coefficient_words(ctrl))
    words = [sum(len(cm.stim) for cm in cases_models)]
    for cm in cases_models:
        for (hdr, stim) in cm.stim:
            words.append(hdr)
            words += stim
    write_hex_words(os.path.join(workdir, "rtl/effects/aw-49/sim/blocks.hex"), words)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--smoke-only", action="store_true",
                    help="PRS 128-block case only (<=4k samples)")
    args = ap.parse_args()
    if shutil.which("iverilog") is None:
        print(json.dumps({"status": "NO_VERDICT", "reason": "iverilog not found"}))
        return 3

    results = {"issue": "SXT-028a", "claim": "RTL-vs-frozen-model EXACT",
               "model_frozen_revision": gm.frozen_revision(),
               "cases": [], "mutant_controls": []}
    ok = True
    base = tempfile.mkdtemp(prefix="aw49-rtl-",
                            dir="/var/folders/fb/l4j31ymn3bn0mc6v1qbvvl8c0000gn/T/opencode")

    def emit(case_name, ctrl, blocks, reset_before=(), want_mem=False,
             core_src="galactic_core.sv", note=""):
        """blocks: list of (instance, in_l, in_r); vib stream per instance
        supplied via ctrl binding in the closure."""
        cases_models = {0: CaseModel(ctrl0, vib=vib0, mem_base=0),
                        1: CaseModel(ctrl1, vib=vib1, mem_base=gm.EXT_WORDS)}
        trace = []
        stim = []
        for bi, (inst, il, ir) in enumerate(blocks):
            cm = cases_models[inst]
            if bi in reset_before:
                for c in cases_models.values():
                    c.model.reset()
                cm.log.reset_marker()
            hdr = (bi & 0xFFFF)
            if inst:
                hdr |= 1 << 30
            if bi in reset_before:
                hdr |= 1 << 31
            sw, _ = cm.block(bi, il, ir)
            cm.stim.append((hdr, sw))
            trace.extend(cm.trace)
            cm.trace = []
        wd = os.path.join(base, case_name.replace("/", "_"))
        trace = [f"R {int(gm.frozen_revision()[:8], 16)}\n"] + trace
        build_case_stimulus(wd, ctrl, list(cases_models.values()))
        model_mem = None
        if want_mem:
            m = cases_models[0].model
            model_mem = [v & 0xFFFFFFFF for v in m.mem] + \
                        [v & 0xFFFFFFFF for v in cases_models[1].model.mem]
        run_iverilog(wd, os.path.join(RTL_DIR, core_src),
                     os.path.join(RTL_DIR, "tb_galactic.sv"))
        res = compare_case(case_name, "".join(trace),
                           sum((cm.log.lines for cm in cases_models.values()), []),
                           model_mem, wd, want_mem)
        res["note"] = note
        return res

    # NOTE: emit() closes over ctrl0/ctrl1/vib0/vib1 set per case below.
    try:
        # ---- Case A: PRS smoke (4096 samples), synthetic vibrato stream
        ctrl0 = gm.build_control({"a": 0.5, "b": 0.5, "c": 0.5, "d": 1.0,
                                  "e": 1.0}, {"fpdL": 101, "fpdR": 202})
        ctrl1 = gm.build_control({"a": 0.2, "b": 0.7, "c": 0.4, "d": 0.8,
                                  "e": 0.9}, {"fpdL": 303, "fpdR": 404})
        vib0 = gm.VibratoStream(ctrl0)
        vib1 = gm.VibratoStream(ctrl1)
        il, ir = prs_blocks(128)
        blocks = [(0, il[b*32:(b+1)*32], ir[b*32:(b+1)*32]) for b in range(128)]
        res = emit("prs-128b-smoke", ctrl0, blocks, want_mem=True,
                   note="deterministic PRS input, synthetic vibrato control "
                        "stream, full 2x EXT memory image compared")
        results["cases"].append(res)
        ok = ok and res["exact"]
        print(f"prs-128b-smoke: exact={res['exact']}")

        if not args.smoke_only:
            # ---- Case B: canonical real fixture (temple, first 512 blocks)
            npz = np.load(CANONICAL_NPZ)
            gal_in = npz["gal_in"]
            tapped = gm.TappedVibratoStream(None, npz["vibM"])
            ctrl_t = gm.build_control(
                {"a": 0.4884969890117645, "b": 0.43098101019859314,
                 "c": 0.37505799531936646, "d": 0.16005100309848785,
                 "e": 1.0}, {"fpdL": 0, "fpdR": 0})
            vib0 = tapped
            ctrl0 = ctrl_t
            blocks = [(0, gal_in[b, :, 0], gal_in[b, :, 1])
                      for b in range(512)]
            res = emit("canonical-temple-512b", ctrl_t, blocks, want_mem=True,
                       note="first 512 tapped blocks of the temple fixture "
                            "(real engine adapter input + tapped vibrato "
                            "control plane); full memory image compared")
            results["cases"].append(res)
            ok = ok and res["exact"]
            print(f"canonical-temple-512b: exact={res['exact']}")

            # ---- Case C: dual-instance (alternating, independent histories)
            il, ir = prs_blocks(64, seed=777)
            il2, ir2 = prs_blocks(64, seed=888, scale=(1 << 20))
            blocks = []
            for b in range(64):
                blocks.append((b % 2,
                               (il if b % 2 == 0 else il2)[b*32:(b+1)*32],
                               (ir if b % 2 == 0 else ir2)[b*32:(b+1)*32]))
            res = emit("dual-instance-64b", ctrl0, blocks,
                       note="instances 0/1 alternate blocks; disjoint "
                            "regions; per-instance equality enforced")
            results["cases"].append(res)
            ok = ok and res["exact"]
            print(f"dual-instance-64b: exact={res['exact']}")

            # ---- Case D: reset mid-stream
            il, ir = prs_blocks(128, seed=999)
            blocks = [(0, il[b*32:(b+1)*32], ir[b*32:(b+1)*32])
                      for b in range(128)]
            res = emit("prs-128b-reset48", ctrl0, blocks, reset_before={48},
                       want_mem=True,
                       note="host bulk clear + core reset before block 48")
            results["cases"].append(res)
            ok = ok and res["exact"]
            print(f"prs-128b-reset48: exact={res['exact']}")

        # ---- Mutant 1: wrong coefficient (regen halved in the RTL)
        mut = os.path.join(base, "galactic_regen_mutant.sv")
        src = open(os.path.join(RTL_DIR, "galactic_core.sv")).read()
        needle = "128'(fb) * cfg_regen"
        assert needle in src
        open(mut, "w").write(src.replace(needle, "128'(fb) * (cfg_regen >>> 1)"))
        il, ir = prs_blocks(64)
        blocks = [(0, il[b*32:(b+1)*32], ir[b*32:(b+1)*32]) for b in range(64)]
        res = emit("mutant-regen-halved", ctrl0, blocks, core_src="galactic_core.sv") \
            if False else None
        # run mutant against the SAME model trace with the mutant core
        wd = os.path.join(base, "mutant-regen")
        cases_models = {0: CaseModel(ctrl0, vib=gm.VibratoStream(ctrl0), mem_base=0),
                        1: CaseModel(ctrl1, vib=gm.VibratoStream(ctrl1), mem_base=gm.EXT_WORDS)}
        trace = []
        words = [64]
        for b in range(64):
            sw, _ = cases_models[0].block(b, il[b*32:(b+1)*32], ir[b*32:(b+1)*32])
            trace.extend(cases_models[0].trace)
            cases_models[0].trace = []
            words.append(b)
            words += sw
        os.makedirs(os.path.join(wd, "rtl/effects/aw-49/sim"), exist_ok=True)
        os.makedirs(os.path.join(wd, "out/aw-49/rtl"), exist_ok=True)
        write_hex_words(os.path.join(wd, "rtl/effects/aw-49/sim/cfg.hex"),
                        coefficient_words(ctrl0))
        write_hex_words(os.path.join(wd, "rtl/effects/aw-49/sim/blocks.hex"), words)
        run_iverilog(wd, mut, os.path.join(RTL_DIR, "tb_galactic.sv"))
        mres = compare_case("mutant-regen-halved", "".join(trace),
                            cases_models[0].log.lines, None, wd, False)
        mres["injected_defect"] = "feedback regen coefficient halved in the RTL"
        mres["verdict"] = ("CONTROL-OK (mutant FAILS the exactness comparison)"
                           if not mres["exact"]
                           else "CONTROL-BROKEN (mutant PASSED -- finding!)")
        results["mutant_controls"].append(mres)
        ok = ok and not mres["exact"]
        print(f"mutant-regen-halved: {mres['verdict']}")

        # ---- Mutant 2: shared memory (mem_base dropped -> pooled regions)
        mut2 = os.path.join(base, "galactic_shared_mutant.sv")
        src = open(os.path.join(RTL_DIR, "galactic_core.sv")).read()
        assert "mem_base + " in src
        open(mut2, "w").write(src.replace("mem_base + ", ""))
        wd = os.path.join(base, "mutant-shared")
        cases_models = {0: CaseModel(ctrl0, vib=gm.VibratoStream(ctrl0), mem_base=0),
                        1: CaseModel(ctrl1, vib=gm.VibratoStream(ctrl1), mem_base=gm.EXT_WORDS)}
        trace = []
        words = [64]
        for b in range(64):
            inst = b % 2
            src_in = il if inst == 0 else il2
            src_r = ir if inst == 0 else ir2
            sw, _ = cases_models[inst].block(b, src_in[b*32:(b+1)*32],
                                             src_r[b*32:(b+1)*32])
            trace.extend(cases_models[inst].trace)
            cases_models[inst].trace = []
            hdr = b | (inst << 30)
            words.append(hdr)
            words += sw
        os.makedirs(os.path.join(wd, "rtl/effects/aw-49/sim"), exist_ok=True)
        os.makedirs(os.path.join(wd, "out/aw-49/rtl"), exist_ok=True)
        write_hex_words(os.path.join(wd, "rtl/effects/aw-49/sim/cfg.hex"),
                        coefficient_words(ctrl0))
        write_hex_words(os.path.join(wd, "rtl/effects/aw-49/sim/blocks.hex"), words)
        run_iverilog(wd, mut2, os.path.join(RTL_DIR, "tb_galactic.sv"))
        mres2 = compare_case("mutant-shared-memory-dual",
                             "".join(trace),
                             cases_models[0].log.lines + cases_models[1].log.lines,
                             None, wd, False)
        mres2["injected_defect"] = ("mem_base dropped: both instances pool one "
                                    "delay-memory region (shared state)")
        mres2["verdict"] = ("CONTROL-OK (mutant FAILS the dual-instance "
                            "comparison)" if not mres2["exact"]
                            else "CONTROL-BROKEN (mutant PASSED -- finding!)")
        results["mutant_controls"].append(mres2)
        ok = ok and not mres2["exact"]
        print(f"mutant-shared-memory-dual: {mres2['verdict']}")

        results["status"] = "PASS" if ok else "FAIL"
        results["iverilog"] = subprocess.run(["iverilog", "-V"],
                                             capture_output=True,
                                             text=True).stdout.splitlines()[0]
    finally:
        if not args.keep:
            shutil.rmtree(base, ignore_errors=True)

    outp = os.path.join(OUT, "rtl-exactness.json")
    with open(outp, "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {os.path.relpath(outp, REPO)}  status={results['status']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
