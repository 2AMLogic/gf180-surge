#!/usr/bin/env python3
"""SXT-028l exactness harness: RTL trace vs frozen model trace (integer
equality), routing-form leaf (Send buses 3-4 / rf-send34, the extended rack
half of the engine's four send buses).

Generates deterministic control-plane + audio stimulus for a set of declared
cases (the send stage's single active bypass mode and its three skipped ones,
per-slot disable bits 12/13 incl. the real-corpus both-disabled shape,
occupancy shapes, the scene-B-inactive Single-mode shape, the real-corpus
zero-return-level shape, `sendused` transitions, a multi-block arithmetic
tail after the scene buses go silent, a per-slot patch-change reload
mid-tail, a slot-off mid-tail, a panic/reset mid-tail, a same-class
dual-occupant case, a saturating full-scale case and a randomized control
stream), drives rtl/effects/rf-rf-send34/{rf_send34_core.sv, tb_rf_send34.sv}
with iverilog, and compares EVERY main-bus output sample, EVERY per-bus wet
sample and EVERY per-instance checkpoint (both buses' TDF2 registers and ring
flags) against model/effects/rf-rf-send34/rf_send34_model.py with INTEGER
EQUALITY (any mismatch = FAIL). Oracle-independent.

Frozen-revision pin (stale-harness control, issue #64 NC-E): every emitted
record carries the model's own `model_revision()`; `--assert-model-revision
<hex>` makes the harness REFUSE to report PASS when the pinned revision does
not match the live model (exit 2, status "REFUSED"). The negative-control
tool drives exactly that path.

Usage:
    python3 tools/compare_rtl_model_rf_send34.py [--out out.json]
    python3 tools/compare_rtl_model_rf_send34.py --assert-model-revision <hex>
"""

import argparse
import json
import os
import random
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-send34"))

import rf_send34_model as rm  # noqa: E402

RTL_DIR = os.path.join(REPO, "rtl", "effects", "rf-rf-send34")
CORE = os.path.join(RTL_DIR, "rf_send34_core.sv")
TB = os.path.join(RTL_DIR, "tb_rf_send34.sv")
IV = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")

BLOCK = rm.BLOCK
CTRL_WORDS = 25

# Two distinct occupant coefficient sets (arbitrary control-plane stimulus --
# NOT derived from any Surge FX class's parameters; see the frozen model's
# "FORM SCOPE ONLY" note).
COEFFS_3 = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_4 = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
            rm.to_q(-0.35, 29, 32), rm.to_q(0.18, 29, 32))
# A deliberately long-ringing occupant (poles at |z| ~ 0.97): its arithmetic
# tail stays nonzero for many blocks after the scene buses go silent, which is
# what the tail acceptance case and the dropped-tail controls need.
COEFFS_TAIL = (rm.to_q(0.06, 29, 32), 0, 0,
               rm.to_q(-1.90, 29, 32), rm.to_q(0.945, 29, 32))
# High-gain occupant used only to exercise the 32-bit saturation paths
# (bus formation and the return mix) on a near-full-scale input.
COEFFS_HOT = (rm.to_q(3.9, 29, 32), rm.to_q(2.5, 29, 32), rm.to_q(-1.5, 29, 32),
              rm.to_q(0.2, 29, 32), rm.to_q(-0.1, 29, 32))

# Gain planes (Q1.30), DISTINCT per bus on purpose: for a PARALLEL routing
# form the observable slot-permutation axis is slot-content-vs-bus-gain, so a
# wrong-order control has force only when the two buses' gains differ.
# `gain_from_level` applies the declared level**3 (amp_to_linear-cubed)
# mapping at CONTROL rate -- see the frozen model's docstring.
LEVELS_3 = (rm.gain_from_level(0.8), rm.gain_from_level(0.5),
            rm.gain_from_level(1.0))
LEVELS_4 = (rm.gain_from_level(0.3), rm.gain_from_level(0.9),
            rm.gain_from_level(0.7))
# Real-corpus shape: `Slowboat/FX/Random Bass FX.fxp` stores return_level 0.0
# on BOTH send3 and send4 -- the bus runs and its instance state advances, but
# it returns silence into the main bus.
LEVELS_ZERO_RETURN = (rm.gain_from_level(0.8), rm.gain_from_level(0.5),
                      rm.gain_from_level(0.0))

# Declared tail span (blocks of silent scene buses during which the occupant's
# arithmetic tail must still be rendered) -- used by the tail acceptance case
# and asserted by the dropped-tail negative control.
TAIL_SIGNAL_BLOCKS = 2
TAIL_SPAN_BLOCKS = 6

# Real-corpus fx_disable mask that disables BOTH of this leaf's slots at once
# (Kinsey Dulcet/Percussion/Closeout Sale @ Electro Percussion Warehouse.fxp
# carries fx_disable = 13107, whose bits 12 AND 13 are both set, with both
# send3 and send4 occupied -- see
# model/effects/fx_inputs/rf-rf-send34-closeout-sale.json).
BOTH_DISABLED_MASK = (1 << rm.FXSLOT_SEND3) | (1 << rm.FXSLOT_SEND4)
CORPUS_BOTH_DISABLED_MASK = 13107


def u32(v):
    return f"{v & 0xffffffff:08x}"


def rand_in(rs, amp=0.3):
    """One block of stimulus: (sa_l, sa_r, sb_l, sb_r, main_l, main_r)."""
    return tuple([rm.to_q(amp * rs.uniform(-1, 1), 21, 32)
                  for _ in range(BLOCK)] for _ in range(6))


def silent_scenes(rs, amp=0.3):
    """Scene buses silent, main bus still live -- the tail stimulus: the send
    buses stop being fed while the occupants ring out."""
    z = [0] * BLOCK
    return (list(z), list(z), list(z), list(z),
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)])


def build_case(name, ctrl_blocks, in_blocks, panic_before=None):
    """Runs the frozen model block-by-block over an explicit per-block control
    stream, emitting matching ctrl.hex / in.hex stimulus and the model's own
    per-block trace.

    ctrl_blocks entries: dicts with keys fx_bypass, fx_disable, scene_b,
    occ3, rld3, c3, lv3, occ4, rld4, c4, lv4, send_in3, send_in4.
    """
    rack = rm.ExtendedSendRack()
    ctrl_lines, in_lines = [], []
    model_blocks = []
    assert len(ctrl_blocks) == len(in_blocks)
    for b, (cb, ib) in enumerate(zip(ctrl_blocks, in_blocks)):
        if panic_before is not None and b == panic_before:
            rack.panic_reset()

        rack.apply_control(cb["fx_bypass"], cb["fx_disable"], cb["scene_b"],
                           cb["occ3"], cb["rld3"], cb["c3"], cb["lv3"],
                           cb["occ4"], cb["rld4"], cb["c4"], cb["lv4"])

        ctrl_lines += [u32(cb["fx_bypass"]), u32(cb["fx_disable"]),
                       u32(1 if cb["scene_b"] else 0),
                       u32(1 if cb["occ3"] else 0), u32(1 if cb["rld3"] else 0),
                       u32(1 if cb["occ4"] else 0), u32(1 if cb["rld4"] else 0),
                       u32(1 if cb["send_in3"] else 0),
                       u32(1 if cb["send_in4"] else 0)]
        for v in cb["c3"]:
            ctrl_lines.append(u32(v))
        for v in cb["c4"]:
            ctrl_lines.append(u32(v))
        for v in cb["lv3"]:
            ctrl_lines.append(u32(v))
        for v in cb["lv4"]:
            ctrl_lines.append(u32(v))
        for arr in ib:
            for v in arr:
                in_lines.append(u32(v))

        sa_l, sa_r, sb_l, sb_r, main_l, main_r = ib
        (ol, orr, w3l, w3r, w4l, w4r, ring3, ring4) = rack.process_block(
            sa_l, sa_r, sb_l, sb_r, main_l, main_r,
            cb["send_in3"], cb["send_in4"])
        model_blocks.append({"out_l": ol, "out_r": orr,
                             "wet": w3l + w3r + w4l + w4r,
                             "ring3": ring3, "ring4": ring4,
                             "cp": rack.checkpoint()})

    return {"name": name, "nblocks": len(ctrl_blocks),
            "panic_before": panic_before,
            "ctrl_lines": ctrl_lines, "in_lines": in_lines,
            "model_blocks": model_blocks}


def ctrl(fx_bypass=rm.FXB_ALL_FX, fx_disable=0, scene_b=True,
         occ3=True, rld3=False, c3=COEFFS_3, lv3=LEVELS_3,
         occ4=True, rld4=False, c4=COEFFS_4, lv4=LEVELS_4,
         send_in3=True, send_in4=True):
    return {"fx_bypass": fx_bypass, "fx_disable": fx_disable,
            "scene_b": scene_b,
            "occ3": occ3, "rld3": rld3, "c3": c3, "lv3": lv3,
            "occ4": occ4, "rld4": rld4, "c4": c4, "lv4": lv4,
            "send_in3": send_in3, "send_in4": send_in4}


def uniform_case(name, n, seed, amp=0.3, **kw):
    rs = random.Random(seed)
    return build_case(name, [ctrl(**kw) for _ in range(n)],
                      [rand_in(rs, amp) for _ in range(n)])


def declared_cases():
    """The declared case set. Each entry states what it exercises; the table
    is reproduced in reports/SXT-028l/EVIDENCE.md."""
    N = 6
    cases = [
        uniform_case("both-buses-all-fx", N, 1),
        # send-specific: the SEND stage is the only routing stage that is
        # skipped in NO_SENDS (the insert and global stages still run there).
        uniform_case("bypass-no-sends-skips-stage", N, 2,
                     fx_bypass=rm.FXB_NO_SENDS),
        uniform_case("bypass-scene-fx-only-skips-stage", N, 3,
                     fx_bypass=rm.FXB_SCENE_FX_ONLY),
        uniform_case("bypass-no-fx-skips-stage", N, 4,
                     fx_bypass=rm.FXB_NO_FX),
        uniform_case("bus3-disabled-bit12", N, 5,
                     fx_disable=(1 << rm.FXSLOT_SEND3)),
        uniform_case("bus4-disabled-bit13", N, 6,
                     fx_disable=(1 << rm.FXSLOT_SEND4)),
        # real-corpus shape: Closeout Sale @ Electro Percussion Warehouse.fxp
        # occupies BOTH send buses and disables BOTH of them (13107).
        uniform_case("both-buses-disabled-corpus-mask", N, 7,
                     fx_disable=CORPUS_BOTH_DISABLED_MASK),
        # carrier shape: Trance/Dystopia occupy send3 only
        uniform_case("bus4-unoccupied-send3-only", N, 8, occ4=False),
        uniform_case("bus3-unoccupied-send4-only", N, 9, occ3=False),
        # real-corpus shape: Strynth.fxp hosts the SAME FX class (Nimbus) in
        # both send3 and send4. Identical coefficients on DIFFERENT gain
        # planes must still give two INDEPENDENT histories.
        uniform_case("same-class-dual-occupants", N, 10, c4=COEFFS_3),
        # Single scene mode: scene B is never instantiated, so only scene A
        # feeds the send buses (all three issue-named carriers are Single).
        uniform_case("scene-b-inactive-single-mode", N, 11, scene_b=False),
        # real-corpus shape: Random Bass FX.fxp stores return_level 0.0 on
        # both send buses -- the buses run and their state advances, but they
        # return silence.
        uniform_case("zero-return-level-both-buses", N, 12,
                     lv3=LEVELS_ZERO_RETURN, lv4=LEVELS_ZERO_RETURN),
        uniform_case("sendused-false-passthrough", N, 13,
                     send_in3=False, send_in4=False),
    ]

    # `sendused` drops on one bus only, mid-run: send3 stops processing while
    # send4 keeps going (the buses are independent).
    rs = random.Random(14)
    live = [True, True, True, False, False, False]
    cases.append(build_case(
        "sendused3-goes-false-mid-run",
        [ctrl(send_in3=v) for v in live],
        [rand_in(rs) for _ in range(len(live))]))

    # multi-block arithmetic tail: TAIL_SIGNAL_BLOCKS of signal, then
    # TAIL_SPAN_BLOCKS with the SCENE BUSES SILENT while `sendused` stays true
    # -- the occupants' own ringing must continue to be rendered from their
    # registers and mixed back through the return gains.
    nt = TAIL_SIGNAL_BLOCKS + TAIL_SPAN_BLOCKS
    rs = random.Random(15)
    cases.append(build_case(
        "tail-span-silent-scenes",
        [ctrl(c3=COEFFS_TAIL, c4=COEFFS_TAIL) for _ in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_scenes(rs)
         for b in range(nt)]))

    # per-slot patch change (loadFx) mid-tail: send3 is reloaded at block 3
    # while the tail rings -- ONLY send3's history clears; send4 keeps its own
    # and the gain plane is untouched.
    rs = random.Random(16)
    cases.append(build_case(
        "bus3-reload-mid-tail",
        [ctrl(c3=COEFFS_TAIL, c4=COEFFS_TAIL, rld3=(b == 3)) for b in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_scenes(rs)
         for b in range(nt)]))

    # slot goes off mid-tail (enqueueFXOff): send4 released at block 3 -- its
    # history is gone and its bus stops contributing to the main bus entirely.
    rs = random.Random(17)
    cases.append(build_case(
        "bus4-off-mid-tail",
        [ctrl(c3=COEFFS_TAIL, c4=COEFFS_TAIL, occ4=(b < 3)) for b in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_scenes(rs)
         for b in range(nt)]))

    # panic / all-notes-off mid-tail: BOTH instances' histories drop.
    rs = random.Random(18)
    cases.append(build_case(
        "panic-reset-mid-tail",
        [ctrl(c3=COEFFS_TAIL, c4=COEFFS_TAIL) for _ in range(nt)],
        [rand_in(rs, 0.05) if b < TAIL_SIGNAL_BLOCKS else silent_scenes(rs)
         for b in range(nt)],
        panic_before=4))

    # near-full-scale input through a high-gain occupant and unity gains:
    # exercises the 32-bit saturation paths in bus formation and the return
    # mix, in both model and RTL.
    rs = random.Random(19)
    hot_levels = (rm.to_g(1.9), rm.to_g(1.9), rm.to_g(1.9))
    cases.append(build_case(
        "saturating-full-scale",
        [ctrl(c3=COEFFS_HOT, c4=COEFFS_HOT, lv3=hot_levels, lv4=hot_levels)
         for _ in range(4)],
        [rand_in(rs, 120.0) for _ in range(4)]))

    # randomized control stream: bypass mode, disable mask, scene-B activity,
    # occupancy, reload pulses, the gain plane and both `sendused` flags all
    # move per block.
    rs = random.Random(20)
    nrand = 12
    rctrl = []
    for _ in range(nrand):
        rctrl.append(ctrl(
            fx_bypass=rs.choice([rm.FXB_ALL_FX, rm.FXB_NO_SENDS,
                                 rm.FXB_SCENE_FX_ONLY, rm.FXB_NO_FX]),
            fx_disable=rs.choice([0, 1 << rm.FXSLOT_SEND3,
                                  1 << rm.FXSLOT_SEND4,
                                  CORPUS_BOTH_DISABLED_MASK,
                                  0xFFFF & ~BOTH_DISABLED_MASK]),
            scene_b=rs.random() > 0.3,
            occ3=rs.random() > 0.2, rld3=rs.random() > 0.8,
            occ4=rs.random() > 0.2, rld4=rs.random() > 0.8,
            lv3=(rm.gain_from_level(rs.random()),
                 rm.gain_from_level(rs.random()),
                 rm.gain_from_level(rs.random())),
            lv4=(rm.gain_from_level(rs.random()),
                 rm.gain_from_level(rs.random()),
                 rm.gain_from_level(rs.random())),
            send_in3=rs.random() > 0.25, send_in4=rs.random() > 0.25))
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
            ring3, ring4 = int(parts[10]), int(parts[11])
            i += 1
            oparts = lines[i].split()
            assert oparts[0] == "O" and int(oparts[1]) == blk
            ovals = [int(x) for x in oparts[2:]]
            i += 1
            wparts = lines[i].split()
            assert wparts[0] == "W" and int(wparts[1]) == blk
            wvals = [int(x) for x in wparts[2:]]
            blocks[blk] = {"cp": cp, "ring3": ring3, "ring4": ring4,
                           "out_l": ovals[:BLOCK],
                           "out_r": ovals[BLOCK:2 * BLOCK],
                           "wet": wvals}
            i += 1
        else:
            i += 1
    return blocks


def compile_tb(vvp_path, core=CORE, defines=()):
    """Compile the harness against `core` (the production core by default;
    rf_send34_mutants.sv with a -D defect for the negative-control benches)."""
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
    checked = {"outputs": 0, "wet": 0, "checkpoints": 0}
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
                fails.append(f"block {b} main[{k}]: model={a} rtl={v}")
        for k, (a, v) in enumerate(zip(m["wet"], r["wet"])):
            checked["wet"] += 1
            if a != v:
                fails.append(f"block {b} wet[{k}]: model={a} rtl={v}")
        mcp = (m["cp"][0][0], m["cp"][0][1], m["cp"][1][0], m["cp"][1][1],
               m["cp"][2][0], m["cp"][2][1], m["cp"][3][0], m["cp"][3][1])
        checked["checkpoints"] += 1
        if mcp != r["cp"]:
            fails.append(f"block {b} checkpoint: model={mcp} rtl={r['cp']}")
        if int(m["ring3"]) != r["ring3"] or int(m["ring4"]) != r["ring4"]:
            fails.append(f"block {b} ring: model="
                         f"{(int(m['ring3']), int(m['ring4']))} "
                         f"rtl={(r['ring3'], r['ring4'])}")
    return checked, fails


def revision_pin_ok(pinned_revision):
    """Frozen-revision pin check (issue #64 NC-E, "stale stub"). A harness
    whose pinned model revision does not match the LIVE model file must
    refuse to report PASS. `None` means "no pin asserted on this run" and is
    accepted (the record still carries the live revision)."""
    if pinned_revision is None:
        return True
    return pinned_revision == rm.model_revision()


def tail_nonzero_blocks(case):
    """Number of blocks in `case` whose per-bus WET output is not all-zero --
    used to assert that the declared tail span really carries audio out of the
    occupants' registers (the main bus alone would not prove it: the main-bus
    stimulus stays live through the tail on purpose)."""
    return sum(1 for m in case["model_blocks"] if any(v != 0 for v in m["wet"]))


def dual_instance_states_differ(case):
    """True when the case's final checkpoint shows the two buses holding
    DIFFERENT histories -- the observable form of per-instance state."""
    cp = case["model_blocks"][-1]["cp"]
    return (cp[0], cp[1]) != (cp[2], cp[3])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default=os.path.join(REPO, "reports", "SXT-028l",
                                         "rtl-exactness.json"))
    ap.add_argument("--workdir", default="/tmp/sxt028l_rtl")
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
            "leaf": "SXT-028l",
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
    vvp_path = os.path.join(args.workdir, "rf_send34_tb.vvp")
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
        if case["name"] == "tail-span-silent-scenes":
            entry["tail"] = {
                "signal_blocks": TAIL_SIGNAL_BLOCKS,
                "declared_tail_span_blocks": TAIL_SPAN_BLOCKS,
                "blocks_with_nonzero_wet_output": tail_nonzero_blocks(case),
            }
        if case["name"] == "same-class-dual-occupants":
            entry["dual_instance"] = {
                "identical_coefficients_in_both_buses": True,
                "distinct_gain_planes": LEVELS_3 != LEVELS_4,
                "final_histories_differ": dual_instance_states_differ(case),
            }
        cases_out.append(entry)

    summary = {
        "schema_version": 1,
        "leaf": "SXT-028l",
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
