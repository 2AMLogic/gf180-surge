#!/usr/bin/env python3
"""SXT-028h exactness harness: RTL trace vs frozen model trace (integer
equality), routing-form leaf (Scene-B insert FX bus, slots 1-2 / rf-bins12).

Generates deterministic control-plane + audio stimulus for a set of declared
cases (bypass modes incl. the insert-specific SCENE_FX_ONLY mode, per-slot
disable/occupancy, scene ring-out transitions, a multi-block arithmetic tail
after the input goes silent, a per-slot patch-change reload mid-tail, a
panic/reset mid-tail, a saturating full-scale case, and a randomized control
stream), drives rtl/effects/rf-rf-bins12/{rf_bins12_core.sv, tb_rf_bins12.sv}
with iverilog, and compares EVERY output sample and EVERY per-instance
checkpoint (both slots' TDF2 registers, the scene ring flag) against
model/effects/rf-rf-bins12/rf_bins12_model.py with INTEGER EQUALITY (any
mismatch = FAIL). Oracle-independent.

Frozen-revision pin (stale-harness control, issue #60 NC-E): every emitted
record carries the model's own `model_revision()`; `--assert-model-revision
<hex>` makes the harness REFUSE to report PASS when the pinned revision does
not match the live model (exit 2, status "REFUSED"). The negative-control
tool drives exactly that path.

Usage:
    python3 tools/compare_rtl_model_rf_bins12.py [--out out.json]
    python3 tools/compare_rtl_model_rf_bins12.py --assert-model-revision <hex>
"""

import argparse
import json
import os
import random
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-bins12"))

import rf_bins12_model as rm  # noqa: E402

RTL_DIR = os.path.join(REPO, "rtl", "effects", "rf-rf-bins12")
CORE = os.path.join(RTL_DIR, "rf_bins12_core.sv")
TB = os.path.join(RTL_DIR, "tb_rf_bins12.sv")
IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")

BLOCK = rm.BLOCK
CTRL_WORDS = 17

# Two distinct occupant coefficient sets (arbitrary control-plane stimulus --
# NOT derived from any Surge FX class's parameters; see the frozen model's
# "FORM SCOPE ONLY" note). Distinct on purpose: series composition of two
# different filters is order-sensitive, which is what makes the wrong-order
# control meaningful.
COEFFS_1 = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_2 = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
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

    ctrl_blocks entries: dicts with keys fx_bypass, fx_disable, occ1, rld1,
    c1, occ2, rld2, c2, sc_in.
    """
    bus = rm.SceneBInsertBus()
    ctrl_lines, in_lines = [], []
    model_blocks = []
    assert len(ctrl_blocks) == len(in_blocks)
    for b, (cb, (il, ir)) in enumerate(zip(ctrl_blocks, in_blocks)):
        if panic_before is not None and b == panic_before:
            bus.panic_reset()

        bus.apply_control(cb["fx_bypass"], cb["fx_disable"],
                          cb["occ1"], cb["rld1"], cb["c1"],
                          cb["occ2"], cb["rld2"], cb["c2"])

        ctrl_lines += [u32(cb["fx_bypass"]), u32(cb["fx_disable"]),
                       u32(1 if cb["occ1"] else 0), u32(1 if cb["rld1"] else 0),
                       u32(1 if cb["occ2"] else 0), u32(1 if cb["rld2"] else 0),
                       u32(1 if cb["sc_in"] else 0)]
        for v in cb["c1"]:
            ctrl_lines.append(u32(v))
        for v in cb["c2"]:
            ctrl_lines.append(u32(v))
        for v in il:
            in_lines.append(u32(v))
        for v in ir:
            in_lines.append(u32(v))

        ol, orr, sc_out = bus.process_block(il, ir, cb["sc_in"])
        model_blocks.append({"out_l": ol, "out_r": orr, "sc": sc_out,
                             "cp": bus.checkpoint()})

    return {"name": name, "nblocks": len(ctrl_blocks),
            "panic_before": panic_before,
            "ctrl_lines": ctrl_lines, "in_lines": in_lines,
            "model_blocks": model_blocks}


def ctrl(fx_bypass=rm.FXB_ALL_FX, fx_disable=0, occ1=True, rld1=False,
         c1=COEFFS_1, occ2=True, rld2=False, c2=COEFFS_2, sc_in=True):
    return {"fx_bypass": fx_bypass, "fx_disable": fx_disable,
            "occ1": occ1, "rld1": rld1, "c1": c1,
            "occ2": occ2, "rld2": rld2, "c2": c2, "sc_in": sc_in}


def uniform_case(name, n, seed, amp=0.3, **kw):
    rs = random.Random(seed)
    return build_case(name, [ctrl(**kw) for _ in range(n)],
                      [rand_in(rs, amp) for _ in range(n)])


def declared_cases():
    """The declared case set. Each entry states what it exercises; the table
    is reproduced in reports/SXT-028h/EVIDENCE.md."""
    N = 6
    cases = [
        uniform_case("both-slots-all-fx", N, 1),
        uniform_case("both-slots-no-sends", N, 2, fx_bypass=rm.FXB_NO_SENDS),
        # insert-specific: the scene stage RUNS in SCENE_FX_ONLY (unlike the
        # global bus, which the sibling rf-global2 leaf shows is skipped here)
        uniform_case("both-slots-scene-fx-only", N, 3,
                     fx_bypass=rm.FXB_SCENE_FX_ONLY),
        uniform_case("bypass-no-fx-skips-block", N, 4,
                     fx_bypass=rm.FXB_NO_FX),
        uniform_case("slot1-disabled-bit2", N, 5,
                     fx_disable=(1 << rm.FXSLOT_BINS1)),
        uniform_case("slot2-disabled-bit3", N, 6,
                     fx_disable=(1 << rm.FXSLOT_BINS2)),
        # carrier shapes: Shore.fxp / Acoordion Basses.fxp occupy bins1 only
        uniform_case("slot2-unoccupied-bins1-only", N, 7, occ2=False),
        uniform_case("slot1-unoccupied-bins2-only", N, 8, occ1=False),
        uniform_case("scene-not-live-passthrough", N, 9, sc_in=False),
    ]

    # scene ring flag drops mid-run (insert stage stops processing)
    rs = random.Random(10)
    live = [True, True, True, False, False, False]
    cases.append(build_case(
        "scene-live-goes-false-mid-run",
        [ctrl(sc_in=v) for v in live],
        [rand_in(rs) for _ in range(len(live))]))

    # multi-block arithmetic tail: TAIL_SIGNAL_BLOCKS of signal, then
    # TAIL_SPAN_BLOCKS of SILENT input while the scene stays live -- the
    # occupant's own ringing must continue to be rendered from its registers.
    nt = TAIL_SIGNAL_BLOCKS + TAIL_SPAN_BLOCKS
    rs = random.Random(11)
    cases.append(build_case(
        "tail-span-silent-input",
        [ctrl(c1=COEFFS_TAIL) for _ in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_in()
         for b in range(nt)]))

    # per-slot patch change (loadFx) mid-tail: bins1 is reloaded at block 3
    # while the tail rings -- ONLY bins1's history clears; bins2 keeps its own.
    rs = random.Random(12)
    cases.append(build_case(
        "slot1-reload-mid-tail",
        [ctrl(c1=COEFFS_TAIL, rld1=(b == 3)) for b in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_in()
         for b in range(nt)]))

    # slot goes off mid-tail (enqueueFXOff): bins2 released at block 3 --
    # its history is gone and the stage no-ops from then on.
    rs = random.Random(13)
    cases.append(build_case(
        "slot2-off-mid-tail",
        [ctrl(c1=COEFFS_TAIL, occ2=(b < 3)) for b in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_in()
         for b in range(nt)]))

    # panic / all-notes-off mid-tail: BOTH instances' histories drop.
    rs = random.Random(14)
    cases.append(build_case(
        "panic-reset-mid-tail",
        [ctrl(c1=COEFFS_TAIL) for _ in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_in()
         for b in range(nt)],
        panic_before=4))

    # near-full-scale input through a high-gain occupant: exercises the
    # 32-bit audio-output saturation path (sat32) in both model and RTL.
    rs = random.Random(15)
    cases.append(build_case(
        "saturating-full-scale",
        [ctrl(c1=COEFFS_HOT, c2=COEFFS_HOT) for _ in range(4)],
        [rand_in(rs, 120.0) for _ in range(4)]))

    # randomized control stream: bypass mode, disable mask, occupancy, reload
    # pulses and the scene-live flag all move per block.
    rs = random.Random(16)
    nrand = 12
    rctrl = []
    for _ in range(nrand):
        rctrl.append(ctrl(
            fx_bypass=rs.choice([rm.FXB_ALL_FX, rm.FXB_NO_SENDS,
                                 rm.FXB_SCENE_FX_ONLY, rm.FXB_NO_FX]),
            fx_disable=rs.choice([0, 1 << rm.FXSLOT_BINS1,
                                  1 << rm.FXSLOT_BINS2,
                                  (1 << rm.FXSLOT_BINS1) | (1 << rm.FXSLOT_BINS2),
                                  0xFFFF & ~((1 << rm.FXSLOT_BINS1) |
                                             (1 << rm.FXSLOT_BINS2))]),
            occ1=rs.random() > 0.2, rld1=rs.random() > 0.8,
            occ2=rs.random() > 0.2, rld2=rs.random() > 0.8,
            sc_in=rs.random() > 0.25))
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
            sc = int(parts[10])
            i += 1
            oparts = lines[i].split()
            assert oparts[0] == "O" and int(oparts[1]) == blk
            vals = [int(x) for x in oparts[2:]]
            blocks[blk] = {"cp": cp, "sc": sc, "out_l": vals[:BLOCK],
                           "out_r": vals[BLOCK:2 * BLOCK]}
            i += 1
        else:
            i += 1
    return blocks


def compile_tb(vvp_path, core=CORE, defines=()):
    """Compile the harness against `core` (the production core by default;
    rf_bins12_mutants.sv with a -D defect for the negative-control benches)."""
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
        if int(m["sc"]) != r["sc"]:
            fails.append(f"block {b} sc_out: model={int(m['sc'])} "
                         f"rtl={r['sc']}")
    return checked, fails


def revision_pin_ok(pinned_revision):
    """Frozen-revision pin check (issue #60 NC-E, "stale stub"). A harness
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default=os.path.join(REPO, "reports", "SXT-028h",
                                         "rtl-exactness.json"))
    ap.add_argument("--workdir", default="/tmp/sxt028h_rtl")
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
            "leaf": "SXT-028h",
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
    vvp_path = os.path.join(args.workdir, "rf_bins12_tb.vvp")
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
        cases_out.append(entry)

    summary = {
        "schema_version": 1,
        "leaf": "SXT-028h",
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
