#!/usr/bin/env python3
"""SXT-028j exactness harness: RTL trace vs frozen model trace (integer
equality), routing-form leaf (Global FX slots 3-4 / rf-global34, the
extended rack half of the master global-FX chain).

Generates deterministic control-plane + audio stimulus for a set of declared
cases (the global bus's two active bypass modes and its two skipped ones,
per-slot disable bits 14/15 incl. the real-corpus both-disabled shape,
occupancy shapes, ring transitions, a multi-block arithmetic tail after the
input goes silent, a per-slot patch-change reload mid-tail, a slot-off
mid-tail, a panic/reset mid-tail, a same-class dual-occupant case, a
saturating full-scale case and a randomized control stream), drives
rtl/effects/rf-rf-global34/{rf_global34_core.sv, tb_rf_global34.sv} with
iverilog, and compares EVERY output sample and EVERY per-instance checkpoint
(both slots' TDF2 registers, the ring flag) against
model/effects/rf-rf-global34/rf_global34_model.py with INTEGER EQUALITY (any
mismatch = FAIL). Oracle-independent.

Frozen-revision pin (stale-harness control, issue #62 NC-E): every emitted
record carries the model's own `model_revision()`; `--assert-model-revision
<hex>` makes the harness REFUSE to report PASS when the pinned revision does
not match the live model (exit 2, status "REFUSED"). The negative-control
tool drives exactly that path.

Usage:
    python3 tools/compare_rtl_model_rf_global34.py [--out out.json]
    python3 tools/compare_rtl_model_rf_global34.py --assert-model-revision <hex>
"""

import argparse
import json
import os
import random
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global34"))

import rf_global34_model as rm  # noqa: E402

RTL_DIR = os.path.join(REPO, "rtl", "effects", "rf-rf-global34")
CORE = os.path.join(RTL_DIR, "rf_global34_core.sv")
TB = os.path.join(RTL_DIR, "tb_rf_global34.sv")
IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")

BLOCK = rm.BLOCK
CTRL_WORDS = 17

# Two distinct occupant coefficient sets (arbitrary control-plane stimulus --
# NOT derived from any Surge FX class's parameters; see the frozen model's
# "FORM SCOPE ONLY" note). Distinct on purpose: series composition of two
# different filters is order-sensitive, which is what makes the wrong-order
# control meaningful.
COEFFS_3 = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_4 = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
            rm.to_q(-0.35, 29, 32), rm.to_q(0.18, 29, 32))
# A deliberately long-ringing occupant (poles at |z| ~ 0.97): its arithmetic
# tail stays nonzero for many blocks after the input goes silent, which is
# what the tail acceptance case and the dropped-tail control need.
COEFFS_TAIL = (rm.to_q(0.06, 29, 32), 0, 0,
               rm.to_q(-1.90, 29, 32), rm.to_q(0.945, 29, 32))
# High-gain occupant used only to exercise the 32-bit audio-output saturation
# path (sat32) on a near-full-scale input.
COEFFS_HOT = (rm.to_q(3.9, 29, 32), rm.to_q(2.5, 29, 32), rm.to_q(-1.5, 29, 32),
              rm.to_q(0.2, 29, 32), rm.to_q(-0.1, 29, 32))

# Declared tail span (blocks of silent input during which the occupant's
# arithmetic tail must still be rendered) -- used by the tail acceptance case
# and asserted by the dropped-tail negative control.
TAIL_SIGNAL_BLOCKS = 2
TAIL_SPAN_BLOCKS = 6

# Real-corpus fx_disable mask that disables BOTH of this leaf's slots at once
# (John Valentine/Winds/Bassoon.fxp carries exactly 49152 = bits 14|15 with
# both slots occupied -- see model/effects/fx_inputs/rf-rf-global34-bassoon.json).
BOTH_DISABLED_MASK = (1 << rm.FXSLOT_GLOBAL3) | (1 << rm.FXSLOT_GLOBAL4)


def u32(v):
    return f"{v & 0xffffffff:08x}"


def rand_in(rs, amp=0.3):
    return ([rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)])


def silent_in():
    return ([0] * BLOCK, [0] * BLOCK)


def build_case(name, ctrl_blocks, in_blocks, panic_before=None):
    """Runs the frozen model block-by-block over an explicit per-block control
    stream, emitting matching ctrl.hex / in.hex stimulus and the model's own
    per-block trace.

    ctrl_blocks entries: dicts with keys fx_bypass, fx_disable, occ3, rld3,
    c3, occ4, rld4, c4, glob_in.
    """
    rack = rm.ExtendedGlobalRack()
    ctrl_lines, in_lines = [], []
    model_blocks = []
    assert len(ctrl_blocks) == len(in_blocks)
    for b, (cb, (il, ir)) in enumerate(zip(ctrl_blocks, in_blocks)):
        if panic_before is not None and b == panic_before:
            rack.panic_reset()

        rack.apply_control(cb["fx_bypass"], cb["fx_disable"],
                           cb["occ3"], cb["rld3"], cb["c3"],
                           cb["occ4"], cb["rld4"], cb["c4"])

        ctrl_lines += [u32(cb["fx_bypass"]), u32(cb["fx_disable"]),
                       u32(1 if cb["occ3"] else 0), u32(1 if cb["rld3"] else 0),
                       u32(1 if cb["occ4"] else 0), u32(1 if cb["rld4"] else 0),
                       u32(1 if cb["glob_in"] else 0)]
        for v in cb["c3"]:
            ctrl_lines.append(u32(v))
        for v in cb["c4"]:
            ctrl_lines.append(u32(v))
        for v in il:
            in_lines.append(u32(v))
        for v in ir:
            in_lines.append(u32(v))

        ol, orr, glob_out = rack.process_block(il, ir, cb["glob_in"])
        model_blocks.append({"out_l": ol, "out_r": orr, "glob": glob_out,
                             "cp": rack.checkpoint()})

    return {"name": name, "nblocks": len(ctrl_blocks),
            "panic_before": panic_before,
            "ctrl_lines": ctrl_lines, "in_lines": in_lines,
            "model_blocks": model_blocks}


def ctrl(fx_bypass=rm.FXB_ALL_FX, fx_disable=0, occ3=True, rld3=False,
         c3=COEFFS_3, occ4=True, rld4=False, c4=COEFFS_4, glob_in=True):
    return {"fx_bypass": fx_bypass, "fx_disable": fx_disable,
            "occ3": occ3, "rld3": rld3, "c3": c3,
            "occ4": occ4, "rld4": rld4, "c4": c4, "glob_in": glob_in}


def uniform_case(name, n, seed, amp=0.3, **kw):
    rs = random.Random(seed)
    return build_case(name, [ctrl(**kw) for _ in range(n)],
                      [rand_in(rs, amp) for _ in range(n)])


def declared_cases():
    """The declared case set. Each entry states what it exercises; the table
    is reproduced in reports/SXT-028j/EVIDENCE.md."""
    N = 6
    cases = [
        uniform_case("both-slots-all-fx", N, 1),
        uniform_case("both-slots-no-sends", N, 2, fx_bypass=rm.FXB_NO_SENDS),
        # global-specific: the global stage is SKIPPED in SCENE_FX_ONLY
        # (unlike the scene insert bus, which the sibling rf-bins12 leaf
        # shows still runs there).
        uniform_case("bypass-scene-fx-only-skips-block", N, 3,
                     fx_bypass=rm.FXB_SCENE_FX_ONLY),
        uniform_case("bypass-no-fx-skips-block", N, 4,
                     fx_bypass=rm.FXB_NO_FX),
        uniform_case("slot3-disabled-bit14", N, 5,
                     fx_disable=(1 << rm.FXSLOT_GLOBAL3)),
        uniform_case("slot4-disabled-bit15", N, 6,
                     fx_disable=(1 << rm.FXSLOT_GLOBAL4)),
        # real-corpus shape: Bassoon.fxp occupies BOTH slots and disables
        # BOTH of them (fx_disable = 49152).
        uniform_case("both-slots-disabled-bits14-15", N, 7,
                     fx_disable=BOTH_DISABLED_MASK),
        # carrier shape: Jigsaw/Pixel/Lazy all occupy global3 only
        uniform_case("slot4-unoccupied-global3-only", N, 8, occ4=False),
        uniform_case("slot3-unoccupied-global4-only", N, 9, occ3=False),
        # real-corpus shape: String Contrabass.fxp hosts the SAME FX class
        # (Airwindows, same sub-algorithm) in both slots. Identical
        # coefficients must still give two INDEPENDENT histories.
        uniform_case("same-class-dual-occupants", N, 10, c4=COEFFS_3),
        uniform_case("ring-never-true-passthrough", N, 11, glob_in=False),
    ]

    # ring flag drops mid-run (global stage stops processing)
    rs = random.Random(12)
    live = [True, True, True, False, False, False]
    cases.append(build_case(
        "ring-goes-false-mid-run",
        [ctrl(glob_in=v) for v in live],
        [rand_in(rs) for _ in range(len(live))]))

    # multi-block arithmetic tail: TAIL_SIGNAL_BLOCKS of signal, then
    # TAIL_SPAN_BLOCKS of SILENT input while the ring flag stays true -- the
    # occupant's own ringing must continue to be rendered from its registers.
    nt = TAIL_SIGNAL_BLOCKS + TAIL_SPAN_BLOCKS
    rs = random.Random(13)
    cases.append(build_case(
        "tail-span-silent-input",
        [ctrl(c3=COEFFS_TAIL) for _ in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_in()
         for b in range(nt)]))

    # per-slot patch change (loadFx) mid-tail: global3 is reloaded at block 3
    # while the tail rings -- ONLY global3's history clears; global4 keeps its
    # own.
    rs = random.Random(14)
    cases.append(build_case(
        "slot3-reload-mid-tail",
        [ctrl(c3=COEFFS_TAIL, rld3=(b == 3)) for b in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_in()
         for b in range(nt)]))

    # slot goes off mid-tail (enqueueFXOff): global4 released at block 3 --
    # its history is gone and the stage no-ops from then on.
    rs = random.Random(15)
    cases.append(build_case(
        "slot4-off-mid-tail",
        [ctrl(c3=COEFFS_TAIL, occ4=(b < 3)) for b in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_in()
         for b in range(nt)]))

    # panic / all-notes-off mid-tail: BOTH instances' histories drop.
    rs = random.Random(16)
    cases.append(build_case(
        "panic-reset-mid-tail",
        [ctrl(c3=COEFFS_TAIL) for _ in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_in()
         for b in range(nt)],
        panic_before=4))

    # near-full-scale input through a high-gain occupant: exercises the
    # 32-bit audio-output saturation path (sat32) in both model and RTL.
    rs = random.Random(17)
    cases.append(build_case(
        "saturating-full-scale",
        [ctrl(c3=COEFFS_HOT, c4=COEFFS_HOT) for _ in range(4)],
        [rand_in(rs, 120.0) for _ in range(4)]))

    # randomized control stream: bypass mode, disable mask, occupancy, reload
    # pulses and the ring flag all move per block.
    rs = random.Random(18)
    nrand = 12
    rctrl = []
    for _ in range(nrand):
        rctrl.append(ctrl(
            fx_bypass=rs.choice([rm.FXB_ALL_FX, rm.FXB_NO_SENDS,
                                 rm.FXB_SCENE_FX_ONLY, rm.FXB_NO_FX]),
            fx_disable=rs.choice([0, 1 << rm.FXSLOT_GLOBAL3,
                                  1 << rm.FXSLOT_GLOBAL4,
                                  BOTH_DISABLED_MASK,
                                  0xFFFF & ~BOTH_DISABLED_MASK]),
            occ3=rs.random() > 0.2, rld3=rs.random() > 0.8,
            occ4=rs.random() > 0.2, rld4=rs.random() > 0.8,
            glob_in=rs.random() > 0.25))
    cases.append(build_case("random-control-stream", rctrl,
                            [rand_in(rs, 0.2) for _ in range(nrand)]))
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


def compile_tb(vvp_path, core=CORE, defines=()):
    """Compile the harness against `core` (the production core by default;
    rf_global34_mutants.sv with a -D defect for the negative-control
    benches)."""
    cmd = [IV, "-g2012"] + [f"-D{d}" for d in defines] + \
        ["-o", vvp_path, core, TB]
    subprocess.run(cmd, check=True)


def run_case(vvp_path, case, workdir):
    ctrl_path = os.path.join(workdir, f"{case['name']}_ctrl.hex")
    in_path = os.path.join(workdir, f"{case['name']}_in.hex")
    trace_path = os.path.join(workdir, f"{case['name']}_trace.txt")
    write_hex(ctrl_path, case["ctrl_lines"])
    write_hex(in_path, case["in_lines"])
    panic = case["panic_before"] if case["panic_before"] is not None else -1
    plusargs = [f"+CTRLFILE={ctrl_path}", f"+INFILE={in_path}",
                f"+NBLOCKS={case['nblocks']}", f"+TRACE={trace_path}",
                f"+RESETAT={panic}"]
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
            fails.append(f"block {b} glob_out: model={int(m['glob'])} "
                         f"rtl={r['glob']}")
    return checked, fails


def revision_pin_ok(pinned_revision):
    """Frozen-revision pin check (issue #62 NC-E, "stale stub"). A harness
    whose pinned model revision does not match the LIVE model file must
    refuse to report PASS. `None` means "no pin asserted on this run" and is
    accepted (the record still carries the live revision)."""
    if pinned_revision is None:
        return True
    return pinned_revision == rm.model_revision()


def tail_nonzero_blocks(case):
    """Number of blocks in `case` whose output is not all-zero -- used to
    assert that the declared tail span really carries audio (a tail control
    that truncates silence would prove nothing)."""
    return sum(1 for m in case["model_blocks"]
               if any(v != 0 for v in m["out_l"] + m["out_r"]))


def dual_instance_states_differ(case):
    """True when the case's final checkpoint shows the two slots holding
    DIFFERENT histories -- the observable form of per-instance state."""
    cp = case["model_blocks"][-1]["cp"]
    return (cp[0], cp[1]) != (cp[2], cp[3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default=os.path.join(REPO, "reports", "SXT-028j",
                                         "rtl-exactness.json"))
    ap.add_argument("--workdir", default="/tmp/sxt028j_rtl")
    ap.add_argument("--assert-model-revision", default=None,
                    help="refuse to report PASS unless the live frozen model "
                         "has this sha256 revision (stale-harness control)")
    ap.add_argument("--no-write", action="store_true",
                    help="do not write the report file (control runs)")
    args = ap.parse_args()

    pin_ok = revision_pin_ok(args.assert_model_revision)
    if not pin_ok:
        summary = {
            "schema_version": 1,
            "leaf": "SXT-028j",
            "sim": "iverilog",
            "model_revision": rm.model_revision(),
            "asserted_model_revision": args.assert_model_revision,
            "status": "REFUSED",
            "reason": "stale harness: asserted frozen-model revision does not "
                      "match the live model file; refusing to report PASS",
            "cases": [],
        }
        print(json.dumps(summary, indent=2))
        return 2

    os.makedirs(args.workdir, exist_ok=True)
    vvp_path = os.path.join(args.workdir, "rf_global34_tb.vvp")
    compile_tb(vvp_path)

    cases_out = []
    all_ok = True
    for case in declared_cases():
        rtl_blocks = run_case(vvp_path, case, args.workdir)
        checked, fails = compare_case(case, rtl_blocks)
        exact = not fails
        all_ok = all_ok and exact
        entry = {
            "case": case["name"],
            "blocks": case["nblocks"],
            "exact": exact,
            "checked": checked,
            "mismatches": len(fails),
            "first_failures": fails[:10],
            "revision_pin": {"ok": True,
                             "model_revision": rm.model_revision()},
        }
        if case["name"] == "tail-span-silent-input":
            entry["tail"] = {
                "signal_blocks": TAIL_SIGNAL_BLOCKS,
                "declared_tail_span_blocks": TAIL_SPAN_BLOCKS,
                "blocks_with_nonzero_output": tail_nonzero_blocks(case),
            }
        if case["name"] == "same-class-dual-occupants":
            entry["dual_instance"] = {
                "identical_coefficients_in_both_slots": True,
                "final_histories_differ": dual_instance_states_differ(case),
            }
        cases_out.append(entry)

    summary = {
        "schema_version": 1,
        "leaf": "SXT-028j",
        "sim": "iverilog",
        "model_revision": rm.model_revision(),
        "asserted_model_revision": args.assert_model_revision,
        "status": "PASS" if all_ok else "FAIL",
        "cases": cases_out,
    }
    print(json.dumps(summary, indent=2))
    if not args.no_write:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2, sort_keys=True)
            f.write("\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
