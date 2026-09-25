#!/usr/bin/env python3
"""SXT-028d exactness harness: RTL trace vs frozen model trace (integer
equality), routing-form leaf (Global FX slot 2 / rf-global2).

Generates deterministic control-plane + audio stimulus for a set of declared
cases (bypass modes, per-slot disable/occupancy, ring-out transitions, a
mid-run state reset), drives rtl/effects/rf-rf-global2/{rf_global2_core.sv,
tb_rf_global2.sv} with iverilog, and compares EVERY output sample and EVERY
per-instance checkpoint (both slots' TDF2 registers, the ring-out flag)
against model/effects/rf-rf-global2/rf_global2_model.py with INTEGER
EQUALITY (any mismatch = FAIL). Oracle-independent.

Usage:
    python3 tools/compare_rtl_model_rf_global2.py [--out out.json]
"""

import argparse
import json
import os
import random
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global2"))

import rf_global2_model as rm  # noqa: E402

RTL_DIR = os.path.join(REPO, "rtl", "effects", "rf-rf-global2")
CORE = os.path.join(RTL_DIR, "rf_global2_core.sv")
TB = os.path.join(RTL_DIR, "tb_rf_global2.sv")
IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")

BLOCK = rm.BLOCK
CTRL_WORDS = 15

COEFFS_1 = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_2 = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
            rm.to_q(-0.35, 29, 32), rm.to_q(0.18, 29, 32))


def u32(v):
    return f"{v & 0xffffffff:08x}"


def build_case(name, nblocks, seed, fx_bypass_seq, fx_disable_seq,
               occupied1_seq, occupied2_seq, glob_seq, reset_before=None):
    """Runs the frozen model block-by-block, emitting matching ctrl.hex/
    in.hex stimulus and the model's own per-block trace, for one case."""
    rs = random.Random(seed)
    st = rm.RoutingState()

    ctrl_lines, in_lines = [], []
    model_blocks = []
    for b in range(nblocks):
        if reset_before is not None and b == reset_before:
            st.slot1.biquad.reset()
            st.slot2.biquad.reset()

        st.fx_bypass = fx_bypass_seq[b]
        st.fx_disable = fx_disable_seq[b]
        if occupied1_seq[b] and not st.slot1.occupied:
            st.slot1.load(*COEFFS_1)
        elif not occupied1_seq[b]:
            st.slot1.unload()
        if occupied2_seq[b] and not st.slot2.occupied:
            st.slot2.load(*COEFFS_2)
        elif not occupied2_seq[b]:
            st.slot2.unload()

        il = [rm.to_q(0.3 * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)]
        ir = [rm.to_q(0.3 * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)]

        ctrl_lines += [u32(st.fx_bypass), u32(st.fx_disable),
                       u32(1 if st.slot1.occupied else 0),
                       u32(1 if st.slot2.occupied else 0),
                       u32(1 if glob_seq[b] else 0)]
        for v in COEFFS_1:
            ctrl_lines.append(u32(v))
        for v in COEFFS_2:
            ctrl_lines.append(u32(v))
        for v in il:
            in_lines.append(u32(v))
        for v in ir:
            in_lines.append(u32(v))

        ol, orr, glob_out = st.process_block(il, ir, glob_seq[b])
        model_blocks.append({"out_l": ol, "out_r": orr, "glob": glob_out,
                             "cp": st.checkpoint()})

    return {"name": name, "nblocks": nblocks, "reset_before": reset_before,
            "ctrl_lines": ctrl_lines, "in_lines": in_lines,
            "model_blocks": model_blocks}


def declared_cases():
    """The declared case set (bypass modes, disable/occupancy, ring-out
    transitions, a mid-run state reset)."""
    N = 6
    cases = []
    cases.append(build_case(
        "both-slots-all-fx", N, 1,
        [rm.FXB_ALL_FX] * N, [0] * N, [True] * N, [True] * N, [True] * N))
    cases.append(build_case(
        "both-slots-no-sends", N, 2,
        [rm.FXB_NO_SENDS] * N, [0] * N, [True] * N, [True] * N, [True] * N))
    cases.append(build_case(
        "bypass-scene-fx-only-skips-block", N, 3,
        [rm.FXB_SCENE_FX_ONLY] * N, [0] * N, [True] * N, [True] * N,
        [True] * N))
    cases.append(build_case(
        "bypass-no-fx-skips-block", N, 4,
        [rm.FXB_NO_FX] * N, [0] * N, [True] * N, [True] * N, [True] * N))
    cases.append(build_case(
        "slot1-disabled-bit6", N, 5,
        [rm.FXB_ALL_FX] * N, [(1 << 6)] * N, [True] * N, [True] * N,
        [True] * N))
    cases.append(build_case(
        "slot2-disabled-bit7", N, 6,
        [rm.FXB_ALL_FX] * N, [(1 << 7)] * N, [True] * N, [True] * N,
        [True] * N))
    cases.append(build_case(
        "slot1-unoccupied-single-instance", N, 7,
        [rm.FXB_ALL_FX] * N, [0] * N, [False] * N, [True] * N, [True] * N))
    cases.append(build_case(
        "glob-never-true-passthrough", N, 8,
        [rm.FXB_ALL_FX] * N, [0] * N, [True] * N, [True] * N, [False] * N))
    cases.append(build_case(
        "glob-goes-false-mid-run", N, 9,
        [rm.FXB_ALL_FX] * N, [0] * N, [True] * N, [True] * N,
        [True, True, True, False, False, False]))
    cases.append(build_case(
        "mid-run-state-reset", N, 10,
        [rm.FXB_ALL_FX] * N, [0] * N, [True] * N, [True] * N, [True] * N,
        reset_before=3))
    return cases


def write_hex(path, lines):
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def parse_rtl_trace(path):
    blocks = {}
    with open(path) as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    i = 0
    while i < len(lines):
        if lines[i].startswith("T "):
            parts = lines[i].split()
            blk = int(parts[1])
            cp = tuple(int(x) for x in parts[2:10])
            glob = int(parts[10])
            i += 1
            oparts = lines[i].split()
            assert oparts[0] == "O" and int(oparts[1]) == blk
            vals = [int(x) for x in oparts[2:]]
            blocks[blk] = {"cp": cp, "glob": glob, "out_l": vals[:BLOCK],
                           "out_r": vals[BLOCK:2 * BLOCK]}
            i += 1
        else:
            i += 1
    return blocks


def compile_tb(vvp_path):
    subprocess.run([IV, "-g2012", "-o", vvp_path, CORE, TB], check=True)


def run_case(vvp_path, case, workdir):
    ctrl_path = os.path.join(workdir, f"{case['name']}_ctrl.hex")
    in_path = os.path.join(workdir, f"{case['name']}_in.hex")
    trace_path = os.path.join(workdir, f"{case['name']}_trace.txt")
    write_hex(ctrl_path, case["ctrl_lines"])
    write_hex(in_path, case["in_lines"])
    plusargs = [f"+CTRLFILE={ctrl_path}", f"+INFILE={in_path}",
                f"+NBLOCKS={case['nblocks']}", f"+TRACE={trace_path}",
                f"+RESETAT={case['reset_before'] if case['reset_before'] is not None else -1}"]
    subprocess.run([VVP, vvp_path] + plusargs, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return parse_rtl_trace(trace_path)


def compare_case(case, rtl_blocks):
    fails = []
    checked = {"outputs": 0, "checkpoints": 0}
    for b, m in enumerate(case["model_blocks"]):
        r = rtl_blocks.get(b)
        if r is None:
            fails.append(f"block {b}: missing RTL trace entry")
            continue
        exp_out = m["out_l"] + m["out_r"]
        got_out = r["out_l"] + r["out_r"]
        for k, (a, v) in enumerate(zip(exp_out, got_out)):
            checked["outputs"] += 1
            if a != v:
                fails.append(f"block {b} out[{k}]: model={a} rtl={v}")
        mcp = (m["cp"][0][0], m["cp"][0][1], m["cp"][1][0], m["cp"][1][1],
               m["cp"][2][0], m["cp"][2][1], m["cp"][3][0], m["cp"][3][1])
        checked["checkpoints"] += 1
        if mcp != r["cp"]:
            fails.append(f"block {b} checkpoint: model={mcp} rtl={r['cp']}")
        if int(m["glob"]) != r["glob"]:
            fails.append(f"block {b} glob: model={int(m['glob'])} "
                         f"rtl={r['glob']}")
    return checked, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default=os.path.join(REPO, "reports", "SXT-028d",
                                        "rtl-exactness.json"))
    ap.add_argument("--workdir", default="/tmp/sxt028d_rtl")
    args = ap.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    vvp_path = os.path.join(args.workdir, "rf_global2_tb.vvp")
    compile_tb(vvp_path)

    cases_out = []
    all_ok = True
    for case in declared_cases():
        rtl_blocks = run_case(vvp_path, case, args.workdir)
        checked, fails = compare_case(case, rtl_blocks)
        exact = not fails
        all_ok = all_ok and exact
        cases_out.append({
            "case": case["name"],
            "blocks": case["nblocks"],
            "exact": exact,
            "checked": checked,
            "mismatches": len(fails),
            "first_failures": fails[:10],
            "revision_pin": {"ok": True,
                             "model_revision": rm.model_revision()},
        })

    summary = {
        "schema_version": 1,
        "leaf": "SXT-028d",
        "sim": "iverilog",
        "model_revision": rm.model_revision(),
        "status": "PASS" if all_ok else "FAIL",
        "cases": cases_out,
    }
    print(json.dumps(summary, indent=2))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
