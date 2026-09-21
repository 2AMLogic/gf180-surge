#!/usr/bin/env python3
"""SXT-025: integrated RTL-vs-frozen-model exactness runner.

Runs rtl/integration/tb_sxt025.sv (control_top + reverb1_core in ONE
simulation on one clock, kernel gated by the control block schedule) against
the committed SXT-025 integration stimulus, and compares with EXACT integer
equality:

  1. control-plane T (block-start snapshots) and E (decisions) lines vs the
     landed SXT-021 model's trace (the integration run's control_rows);
  2. kernel per-block checkpoints + every s32i output word vs the frozen
     SXT-024 Reverb1 model over the same send blocks;
  3. every external-memory transaction (R/W addr+data in issue order) vs
     the model's logged hooks;
  4. per-block kernel cycle counts (stall-inclusive) vs the declared
     per-block budget at the 192 MHz candidate clock (A-CLK arithmetic);
  5. the injected-defect MUTANT (rtl/effects/reverb1/reverb1_broken_mutant.sv)
     must FAIL the kernel comparison -- a stale/silent stub in the
     integration slot is detected.

The RTL/host boundary is declared in rtl/integration/tb_sxt025.sv and
model/integration/README.md (voice stage host-side; finding F-1).

Usage: python3 tools/run_sxt025_rtl.py [--blocks 1024] [--keep]
Original to this repository (Apache-2.0).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))

ART = os.path.join(REPO, "reports", "sxt025", "artifacts")
OUT = os.path.join(REPO, "reports", "sxt025")
RTL = os.path.join(REPO, "rtl")


# ------------------------------------------------------------- parsing ----
def parse_blocks_hex(path):
    vals = [int(line, 16) for line in open(path)]
    n = vals[0]
    bl, br = [], []
    for b in range(n):
        base = 1 + b * 65
        hdr = vals[base]
        assert hdr & 0x8000 == 0, "reset blocks not used in SXT-025"
        assert (hdr & 0x7FFF) == b, (hdr, b)
        bl.append([vals[base + 1 + k] - (1 << 32)
                   if vals[base + 1 + k] >> 31 else vals[base + 1 + k]
                   for k in range(32)])
        br.append([vals[base + 33 + k] - (1 << 32)
                   if vals[base + 33 + k] >> 31 else vals[base + 33 + k]
                   for k in range(32)])
    return bl, br


def s24_words(arr):
    return [int(v) & 0xFFFFFFFF for v in arr]


def write_blocks_head(path, bl, br, n):
    words = [n]
    for b in range(n):
        words.append(b & 0xFFFFFFFF)
        words += s24_words(bl[b])
        words += s24_words(br[b])
    with open(path, "w") as f:
        for w in words:
            f.write(f"{w:08x}\n")


def parse_ctl_trace(path):
    """Raw T/E lines (stripped, as written) + the underrun count."""
    T, E = [], []
    underruns = None
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == "T":
            T.append(line.strip())
        elif p[0] == "E":
            E.append(line.strip())
        elif p[0] == "Z" and len(p) >= 2 and p[1] == "underruns":
            underruns = int(p[2])
    return T, E, underruns


def model_ctl_lines(control_rows):
    """Expected control trace lines, byte-equal to the tb's $fwrite output."""
    T, E = [], []
    for rec in control_rows:
        snap = rec["snapshot_after"]
        parts = [f"T {rec['b']} {snap['qcount']} {snap['patch_id']} "
                 f"{snap['active_count']}"]
        for v in snap["voices"]:
            parts.append(f"{1 if v['active'] else 0} {v['note']} {v['seq']}")
        T.append(" ".join(parts))
        for d in rec["decisions"]:
            E.append(f"E {rec['b']} {d['seq']} {d['type']} {d['p1']} {d['p2']}"
                     f" {d['slot']} {d['steal']} {d['status']} {d['flushes']}")
    return T, E


def parse_txns_filtered(path):
    out = []
    for line in open(path):
        p = line.split()
        if not p or p[0] in ("K", "Z"):
            continue
        if p[0] == "X":
            out.append(("X",))
        else:
            out.append((p[0], int(p[1]), int(p[2])))
    return out


def parse_kernel_cycles(path):
    worst = 0
    total = 0
    n = 0
    for line in open(path):
        p = line.split()
        if p and p[0] == "K":
            c = int(p[2])
            worst = max(worst, c)
            total += c
            n += 1
    return n, worst, total


def sha(lines):
    import hashlib

    h = hashlib.sha256()
    for x in lines:
        h.update(("|".join(str(y) for y in x) + "\n").encode())
    return h.hexdigest()


# ------------------------------------------------------------ model side ---
def plane_from_cfg_hex(path):
    """Rebuild the frozen coefficient plane FROM the committed cfg.hex words.

    The cfg.hex is the single pinned coefficient artifact (written by
    model/integration/run_model.py under the pinned interpreter, whose libm
    the [PROPOSED] plane derivation depends on at the last ulp). Rebuilding
    the plane from its quantized words is EXACT (word = round(v * 2^k)), so
    the model-side expected trace consumes bit-identical coefficients to the
    RTL regardless of the ambient interpreter.
    """
    vals = [int(line, 16) for line in open(path)]
    assert len(vals) == 86, len(vals)

    def s32(v):
        return v - (1 << 32) if v >> 31 else v

    def q31f(v):
        return s32(v) / float(1 << 31)

    def q30f(v):
        return s32(v) / float(1 << 30)

    def q29f(v):
        return s32(v) / float(1 << 29)

    flags = vals[6]
    return {
        "pdtime": s32(vals[0]),
        "damp": q31f(vals[1]),
        "damp_m1": q31f(vals[2]),
        "mix": q30f(vals[3]),
        "mix_m1": q30f(vals[4]),
        "width_s": q30f(vals[5]),
        "lowcut_active": bool(flags & 1),
        "hicut_active": bool(flags & 2),
        "delay_time": [s32(v) for v in vals[7:23]],
        "delay_fb": [q31f(v) for v in vals[23:39]],
        "pan_l": [q31f(v) for v in vals[39:55]],
        "pan_r": [q31f(v) for v in vals[55:71]],
        "locut": [q29f(v) for v in vals[71:76]],
        "band1": [q29f(v) for v in vals[76:81]],
        "hicut": [q29f(v) for v in vals[81:86]],
        "shape": 0, "roomsize": 0.0, "decaytime": 0.0,
    }


def model_expected(bl, br, cfg_path):
    sys.path.insert(0, os.path.join(REPO, "tools"))
    from tools.run_reverb_rtl import (ExtLog, format_trace_block,
                                      parse_txn_text, parse_trace_text)

    import reverb1_fixed as rf

    model = rf.Reverb1Fixed(plane_from_cfg_hex(cfg_path))
    log = ExtLog(model)
    model.attach_ext_memory(log.read, log.write)
    trace = []
    for b in range(len(bl)):
        ol, orr = model.process_block(bl[b], br[b])
        trace.append(format_trace_block(b, model.checkpoint(), ol, orr))
    return "".join(trace), log.lines


def coefficient_words(c):
    from tools.run_reverb_rtl import coefficient_words as cw

    return cw(c)


# ---------------------------------------------------------------- iverilog --
def run_iverilog(workdir, dut_core):
    cmd = ["iverilog", "-g2012", "-s", "tb_sxt025", "-o", "sim.out",
           os.path.join(RTL, "integration", "tb_sxt025.sv"),
           os.path.join(RTL, "control", "control_top.sv"),
           dut_core]
    r = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"iverilog failed: {r.stderr[-3000:]}")
    r = subprocess.run(["./sim.out"], cwd=workdir, capture_output=True,
                       text=True, timeout=7200)
    if r.returncode != 0:
        raise RuntimeError(f"sim failed: {r.stderr[-2000:]}")


# --------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=1024)
    ap.add_argument("--sequence", default="sxt025-smoke-v1")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    if shutil.which("iverilog") is None:
        print(json.dumps({"status": "NO_VERDICT", "reason": "no iverilog"}))
        return 3

    trace = json.load(open(os.path.join(
        ART, f"trace__{args.sequence}.json")))
    bl, br = parse_blocks_hex(os.path.join(ART, "rtl", args.sequence, "blocks.hex"))
    n = min(args.blocks, len(bl))
    bl, br = bl[:n], br[:n]

    base = tempfile.mkdtemp(prefix="sxt025-rtl-",
                            dir="/var/folders/fb/l4j31ymn3bn0mc6v1qbvvl8c0000gn/T/opencode")
    results = {
        "issue": "SXT-025 (#18)",
        "claim": "integrated RTL (control_top + reverb1_core, one sim, one "
                 "clock, schedule-coupled) vs the frozen models EXACT; "
                 "external-memory traffic reconciled; mutant control FAILS",
        "sequence": args.sequence,
        "blocks": n,
        "rtl_host_boundary": "voice stage + gain staging host-side (declared "
                             "adaptation, finding F-1); in-chip: control "
                             "plane + Reverb1 kernel + ext writable memory",
        "cases": [],
    }
    ok = True
    try:
        for name, core in (("integrated", os.path.join(RTL, "effects",
                                                       "reverb1",
                                                       "reverb1_core.sv")),
                           ("mutant", os.path.join(RTL, "effects", "reverb1",
                                                   "reverb1_broken_mutant.sv"))):
            wd = os.path.join(base, name)
            os.makedirs(os.path.join(wd, "rtl/integration/sim"), exist_ok=True)
            os.makedirs(os.path.join(wd, "out/sxt025/rtl"), exist_ok=True)
            shutil.copy(os.path.join(ART, "rtl", args.sequence, "cfg.hex"),
                        os.path.join(wd, "rtl/integration/sim/cfg.hex"))
            shutil.copy(os.path.join(ART, "rtl", args.sequence, "events.hex"),
                        os.path.join(wd, "rtl/integration/sim/events.hex"))
            write_blocks_head(os.path.join(wd, "rtl/integration/sim/blocks.hex"),
                              bl, br, n)
            # truncate the event stream to the simulated window: the tb runs
            # nsamples = n*32; committed events.hex already matches the full
            # sequence but nsamples must equal n*32 here
            evs = open(os.path.join(ART, "rtl", args.sequence,
                        "events.hex")).read().split()
            with open(os.path.join(wd, "rtl/integration/sim/events.hex"),
                      "w") as f:
                f.write(evs[0] + "\n")
                f.write(f"{n * 32:x}\n")
                for wtext in evs[2:]:
                    f.write(wtext + "\n")
            run_iverilog(wd, core)

            # control comparison
            rtl_T, rtl_E, underruns = parse_ctl_trace(
                os.path.join(wd, "out/sxt025/rtl/ctl_trace.txt"))
            mT, mE = model_ctl_lines(trace["control_rows"][:n])
            ctl_T_exact = rtl_T == mT
            ctl_E_exact = rtl_E == mE

            # kernel comparison
            from tools.run_reverb_rtl import (parse_trace, parse_txn_text,
                                              parse_trace_text)

            rtl_kT, rtl_kO = parse_trace(
                os.path.join(wd, "out/sxt025/rtl/kernel_trace.txt"))
            model_trace, model_txn = model_expected(
                    bl, br, os.path.join(ART, "rtl", args.sequence, "cfg.hex"))
            mod_kT, mod_kO = parse_trace_text(model_trace)
            kern_exact = (rtl_kT == mod_kT) and (rtl_kO == mod_kO)
            rtl_txn = parse_txns_filtered(
                os.path.join(wd, "out/sxt025/rtl/txn_rtl.txt"))
            txn_exact = rtl_txn == parse_txn_text(model_txn)
            nk, worst_c, total_c = parse_kernel_cycles(
                os.path.join(wd, "out/sxt025/rtl/txn_rtl.txt"))

            res = {
                "case": name,
                "blocks": n,
                "control_snapshots_exact": bool(ctl_T_exact),
                "control_decisions_exact": bool(ctl_E_exact),
                "control_t_lines_rtl": len(rtl_T),
                "control_e_lines_rtl": len(rtl_E),
                "underruns": underruns,
                "kernel_checkpoints_outputs_exact": bool(kern_exact),
                "kernel_blocks_compared": len(mod_kT),
                "txn_log_exact": bool(txn_exact),
                "txn_lines_rtl": len(rtl_txn),
                "txn_log_sha256": {"rtl": sha(rtl_txn),
                                   "model": sha(parse_txn_text(model_txn))},
                "kernel_cycles": {"blocks": nk, "worst_block": worst_c,
                                  "total": total_c,
                                  "per_block_budget_192mhz": 102400,
                                  "within_budget": bool(
                                      worst_c <= 102400)},
                "words_per_frame_measured": len(rtl_txn) // max(1, nk * 32),
            }
            if name == "integrated":
                res["exact"] = bool(ctl_T_exact and ctl_E_exact and kern_exact
                                    and txn_exact and underruns == 0
                                    and res["kernel_cycles"]["within_budget"])
                res["traffic_exact_34_per_frame"] = bool(
                    res["words_per_frame_measured"] == 34)
                res["exact"] = res["exact"] and res["traffic_exact_34_per_frame"]
                ok = ok and res["exact"]
            else:
                res["verdict"] = ("CONTROL-OK (mutant FAILS the kernel "
                                  "comparison)" if not kern_exact else
                                  "CONTROL-BROKEN (mutant PASSED -- finding!)")
                ok = ok and not kern_exact
            results["cases"].append(res)
            status = res.get('exact') or res.get('verdict', '')
            print(f"{name}: {status} "
                  f"ctlT={ctl_T_exact} ctlE={ctl_E_exact} kern={kern_exact} "
                  f"txn={txn_exact} underruns={underruns} "
                  f"worst_cycles={worst_c}")

        results["status"] = "PASS" if ok else "FAIL"
    finally:
        if args.keep:
            keep = os.path.join(OUT, "rtl-run")
            shutil.copytree(base, keep, dirs_exist_ok=True)
        shutil.rmtree(base, ignore_errors=True)

    outp = os.path.join(OUT, "rtl-exactness.json")
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {os.path.relpath(outp, REPO)} status={results['status']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
