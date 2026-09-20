#!/usr/bin/env python3
"""SXT-024: RTL-vs-frozen-model EXACTNESS runner (issue #17 acceptance:
"RTL vs model exact").

Generates stimulus for rtl/effects/reverb1/tb_reverb1.sv from the frozen
fixed-point model (model/effects/reverb1/reverb1_fixed.py) driven with the
committed Behemoth preset's engine state (the SXT-014 ablation carrier),
runs iverilog, and compares -- with exact integer equality:

  1. every s32i output word of every block,
  2. every per-block checkpoint (delay_pos, out_tap[16], biquad regs),
  3. every external-memory transaction (R/W addr + data, in issue order),
  4. the final external-memory image (all 557,056 words; case A),
  5. the injected-defect MUTANT (rtl/effects/reverb1/reverb1_broken_mutant.sv)
     must FAIL the same comparison -- the comparator demonstrably detects
     long-buffer state divergence (silent-stub control, SXT-022 standard).

The frozen model is driven with explicit external-memory logging hooks, so
the model-side transaction log is the reference; the RTL-side log is parsed
from the harness dump. NO_VERDICT cases are reported as such; exit 0 iff all
real cases match exactly AND the mutant fails.

Usage: python3 tools/run_reverb_rtl.py [--keep]
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
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))

import coefficient_plane as cp  # noqa: E402
import reverb1_fixed as rf  # noqa: E402

RTL_DIR = os.path.join(REPO, "rtl", "effects", "reverb1")
TRACES = os.path.join(REPO, "reports", "sxt-024", "traces")
OUT = os.path.join(REPO, "reports", "sxt-024")


# --------------------------------------------------------------------------
# stimulus / expected-trace generation (model side)
# --------------------------------------------------------------------------
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


def coefficient_words(c):
    """The 86 cfg.hex words (frozen quantized formats; mirrors
    Reverb1Fixed.__init__ quantization exactly)."""
    words = []
    words.append(int(c["pdtime"]) & 0xFFFFFFFF)
    for v in (rf.q31(c["damp"]), rf.q31(c["damp_m1"])):
        words.append(v & 0xFFFFFFFF)
    words.append(rf.q30(c["mix"]) & 0xFFFFFFFF)
    words.append(((1 << 30) - rf.q30(c["mix"])) & 0xFFFFFFFF)  # mix_m1
    words.append(rf.q30(c["width_s"]) & 0xFFFFFFFF)
    flags = (1 if c["lowcut_active"] else 0) | (2 if c["hicut_active"] else 0)
    words.append(flags)
    for v in c["delay_time"]:
        words.append(int(v) & 0xFFFFFFFF)
    for v in c["delay_fb"]:
        words.append(rf.q31(v) & 0xFFFFFFFF)
    for v in c["pan_l"]:
        words.append(rf.q31(v) & 0xFFFFFFFF)
    for v in c["pan_r"]:
        words.append(rf.q31(v) & 0xFFFFFFFF)
    for key in ("locut", "band1", "hicut"):
        for v in c[key]:
            words.append(rf.q29(v) & 0xFFFFFFFF)
    assert len(words) == 86, len(words)
    return words


def write_hex_words(path, words):
    with open(path, "w") as f:
        for w in words:
            f.write(f"{w & 0xFFFFFFFF:08x}\n")


def s24_words(arr):
    return [int(v) & 0xFFFFFFFF for v in arr]


def gen_blocks(path, blocks_in_l, blocks_in_r, reset_before=()):
    """blocks.hex: header nblocks, then per block: header word, 32 L, 32 R."""
    n = len(blocks_in_l)
    words = [n]
    for b in range(n):
        hdr = (0x8000 | b) if b in reset_before else b
        words.append(hdr & 0xFFFFFFFF)
        words += s24_words(blocks_in_l[b])
        words += s24_words(blocks_in_r[b])
    write_hex_words(path, words)


def format_trace_block(blk, cp_dict, out_l, out_r):
    line = [f"T {blk} {cp_dict['delay_pos']}"]
    line += [str(v) for v in cp_dict["out_tap"]]
    regs = cp_dict["regs"]
    line += [str(v) for r in regs for v in r]
    s = " ".join(line) + "\n"
    s += "O %d " % blk + " ".join(str(v) for v in out_l + out_r) + "\n"
    return s


def write_mem_hex(path, model):
    with open(path, "w") as f:
        for v in model.delay:
            f.write(f"{v & 0xFFFFFFFF:08x}\n")
        for v in model.predelay:
            f.write(f"{v & 0xFFFFFFFF:08x}\n")


def load_preset_coefficients():
    """Frozen coefficient plane from the committed Behemoth wet sidecar."""
    side = json.load(open(os.path.join(TRACES, "preset-notes-coverage-wet.json")))
    st = side["engine_patch_state"]
    deact = side.get("deactivated_flags_raw_fxp") or {}
    c = cp.build(st["params"],
                 deactivated={"lowcut": deact.get("lowcut", False),
                              "highcut": deact.get("highcut", False)})
    send = float(np.float32(st["scene_send_level"][0]) ** 3)
    ret = float(np.float32(st["return_level"]) ** 3)
    return c, send, ret


def quantize_send_input(dry_bus, send, n_samples):
    """s24-quantized FX input words from a committed float dry bus (the same
    quantization as tools/compare_reverb_model.py)."""
    n = min(n_samples, len(dry_bus[0]))
    il = np.clip(np.round(np.float32(dry_bus[0][:n] * send) * (1 << 23)),
                 rf.S24_MIN, rf.S24_MAX).astype(np.int64)
    ir = np.clip(np.round(np.float32(dry_bus[1][:n] * send) * (1 << 23)),
                 rf.S24_MIN, rf.S24_MAX).astype(np.int64)
    while len(il) < n_samples:
        il = np.append(il, 0)
        ir = np.append(ir, 0)
    return il, ir


def prs_blocks(n_blocks, seed=20260920):
    """Deterministic PRBS-ish stereo s24 stimulus (worst-case-ish toggling)."""
    rs = np.random.RandomState(seed)
    v = rs.randint(-8388608, 8388607, size=(n_blocks * rf.BLOCK * 2,))
    l = v[0::2]
    r = v[1::2]
    return [list(map(int, l[b*32:(b+1)*32])) for b in range(n_blocks)], \
           [list(map(int, r[b*32:(b+1)*32])) for b in range(n_blocks)]


def run_model_case(c, blocks_l, blocks_r, reset_before=()):
    """Run the frozen model over the case, with logging hooks. Returns
    (trace_text, txn_lines, model)."""
    model = rf.Reverb1Fixed(c)
    log = ExtLog(model)
    model.attach_ext_memory(log.read, log.write)
    trace = []
    for b in range(len(blocks_l)):
        if b in reset_before:
            model.reset()
            log.reset_marker()
        ol, orr = model.process_block(blocks_l[b], blocks_r[b])
        trace.append(format_trace_block(b, model.checkpoint(), ol, orr))
    return "".join(trace), log.lines, model


# --------------------------------------------------------------------------
# iverilog side
# --------------------------------------------------------------------------
def parse_trace(path):
    T, O = [], []
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "T":
                T.append([int(v) for v in p[1:]])
            elif p[0] == "O":
                O.append([int(v) for v in p[1:]])
    return T, O


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


def run_iverilog(workdir, core_src, tb_src):
    cmd = f"iverilog -g2012 -s tb_reverb1 -o sim.out {core_src} {tb_src}"
    r = subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"iverilog compile failed: {r.stderr[-2000:]}")
    r = subprocess.run(["./sim.out"], cwd=workdir, capture_output=True, text=True,
                       timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"sim failed: {r.stderr[-2000:]}\n{r.stdout[-500:]}")


def compare_case(name, model_trace, model_txn, model_mem, workdir, want_mem):
    rtl_T, rtl_O = parse_trace(os.path.join(workdir, "out/sxt-024/rtl/tb_trace.txt"))
    mod_T, mod_O = parse_trace_text(model_trace)
    res = {"case": name, "claim": "RTL-vs-frozen-model EXACT"}
    res["blocks"] = len(mod_T)
    res["outputs_exact"] = rtl_O == mod_O
    res["checkpoints_exact"] = rtl_T == mod_T
    rtl_txn = parse_txns(os.path.join(workdir, "out/sxt-024/rtl/txn_rtl.txt"))
    mod_txn = parse_txn_text(model_txn)
    res["txn_log_exact"] = rtl_txn == mod_txn
    res["txn_lines_rtl"] = len(rtl_txn)
    res["txn_lines_model"] = len(mod_txn)
    res["txn_log_sha256"] = {"rtl": sha(rtl_txn), "model": sha(mod_txn)}
    reads = sum(1 for t in rtl_txn if t[0] == "R")
    writes = sum(1 for t in rtl_txn if t[0] == "W")
    xmarks = sum(1 for t in rtl_txn if t[0] == "X")
    res["rtl_measured_traffic"] = {
        "reads": reads, "writes": writes,
        "words_per_frame": reads + writes,
        "reset_markers": xmarks,
        "per_frame_exact_34": (reads + writes) == 34 * len(mod_T) * rf.BLOCK,
    }
    if want_mem:
        mv = parse_mem(os.path.join(workdir, "out/sxt-024/rtl/mem_rtl.hex"),
                       rf.TAP_WORDS + rf.MAX_REV_DLY)
        res["ext_mem_exact"] = mv == model_mem
        res["ext_mem_words"] = len(mv)
    else:
        res["ext_mem_exact"] = None  # covered by the txn write log for this case
    res["exact"] = (res["outputs_exact"] and res["checkpoints_exact"]
                    and res["txn_log_exact"]
                    and (res["ext_mem_exact"] is not False))
    return res


def parse_trace_text(text):
    T, O = [], []
    for line in text.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "T":
            T.append([int(v) for v in p[1:]])
        elif p[0] == "O":
            O.append([int(v) for v in p[1:]])
    return T, O


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


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    if shutil.which("iverilog") is None:
        print(json.dumps({"status": "NO_VERDICT",
                          "reason": "iverilog not found"}))
        return 3

    c, send, ret = load_preset_coefficients()
    results = {"issue": "SXT-024", "claim": "RTL-vs-frozen-model EXACT",
               "preset": "Basses/Behemoth.fxp (SXT-014 Reverb1 carrier)",
               "cases": [], "mutant_control": None}
    ok = True

    cases = []
    # Case A: PRS stimulus, mid-stream state reset, full memory-image compare
    al, ar = prs_blocks(256)
    cases.append({
        "name": "prs-256b-reset48",
        "blocks_l": al, "blocks_r": ar,
        "reset_before": {48},
        "want_mem": True,
        "note": "deterministic PRS input; state reset (host bulk clear + core "
                "reset) before block 48; full 557,056-word external-memory "
                "image compared",
    })
    # Case B: real preset click input (send-scaled committed dry bus)
    dry = np.load(os.path.join(TRACES, "click-dry.npy")).astype(np.float64)
    il, ir = quantize_send_input(dry, send, 512 * rf.BLOCK)
    bl = [list(map(int, il[b*32:(b+1)*32])) for b in range(512)]
    br = [list(map(int, ir[b*32:(b+1)*32])) for b in range(512)]
    cases.append({
        "name": "click-512b",
        "blocks_l": bl, "blocks_r": br,
        "reset_before": set(),
        "want_mem": False,
        "note": "first 512 blocks of the committed click-dry send input; "
                "memory image implied by the write log (initial state zero)",
    })

    base = tempfile.mkdtemp(prefix="sxt024-rtl-", dir="/var/folders/fb/l4j31ymn3bn0mc6v1qbvvl8c0000gn/T/opencode")
    try:
        for case in cases:
            wd = os.path.join(base, case["name"])
            os.makedirs(os.path.join(wd, "rtl/effects/reverb1/sim"), exist_ok=True)
            os.makedirs(os.path.join(wd, "out/sxt-024/rtl"), exist_ok=True)
            write_hex_words(os.path.join(wd, "rtl/effects/reverb1/sim/cfg.hex"),
                            coefficient_words(c))
            gen_blocks(os.path.join(wd, "rtl/effects/reverb1/sim/blocks.hex"),
                       case["blocks_l"], case["blocks_r"], case["reset_before"])
            model_trace, model_txn, model = run_model_case(
                c, case["blocks_l"], case["blocks_r"], case["reset_before"])
            model_mem = None
            if case["want_mem"]:
                model_mem = ([v & 0xFFFFFFFF for v in model.delay]
                             + [v & 0xFFFFFFFF for v in model.predelay])
            src_core = os.path.join(RTL_DIR, "reverb1_core.sv")
            src_tb = os.path.join(RTL_DIR, "tb_reverb1.sv")
            run_iverilog(wd, src_core, src_tb)
            res = compare_case(case["name"], model_trace, model_txn, model_mem,
                               wd, case["want_mem"])
            res["note"] = case["note"]
            results["cases"].append(res)
            ok = ok and res["exact"]
            print(f"{case['name']}: exact={res['exact']} "
                  f"(outputs={res['outputs_exact']} ckpt={res['checkpoints_exact']} "
                  f"txn={res['txn_log_exact']} mem={res['ext_mem_exact']})")
            if args.keep:
                keep = os.path.join(OUT, "rtl", case["name"])
                shutil.copytree(wd, keep, dirs_exist_ok=True)

        # negative control: injected-defect mutant must FAIL the comparison
        wd = os.path.join(base, "mutant")
        os.makedirs(os.path.join(wd, "rtl/effects/reverb1/sim"), exist_ok=True)
        os.makedirs(os.path.join(wd, "out/sxt-024/rtl"), exist_ok=True)
        case = cases[0]
        write_hex_words(os.path.join(wd, "rtl/effects/reverb1/sim/cfg.hex"),
                        coefficient_words(c))
        gen_blocks(os.path.join(wd, "rtl/effects/reverb1/sim/blocks.hex"),
                   case["blocks_l"], case["blocks_r"], case["reset_before"])
        model_trace, model_txn, _ = run_model_case(
            c, case["blocks_l"], case["blocks_r"], case["reset_before"])
        src_core = os.path.join(RTL_DIR, "reverb1_broken_mutant.sv")
        src_tb = os.path.join(RTL_DIR, "tb_reverb1.sv")
        run_iverilog(wd, src_core, src_tb)
        mres = compare_case("mutant-tap7-stale-write", model_trace, model_txn,
                            None, wd, False)
        mres["injected_defect"] = ("S_TAP_WR skips the tap-7 buffer write "
                                   "(silent stale-buffer stub)")
        mres["verdict"] = ("CONTROL-OK (mutant FAILS the exactness comparison)"
                           if not mres["exact"]
                           else "CONTROL-BROKEN (mutant PASSED -- finding!)")
        results["mutant_control"] = mres
        ok = ok and not mres["exact"]
        print(f"mutant: {mres['verdict']}")

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
