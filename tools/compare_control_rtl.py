#!/usr/bin/env python3
"""SXT-021 exactness harness: RTL control-plane trace vs SXT-021 model.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * the block-start snapshots T (queue count, patch id, active count, the
    8-entry voice table) against the model's snapshot_after,
  * every applied decision E (order and all fields, per block),
  * every explicit queue-overflow drop X,
  * every stereo output sample M against the model's outputs, and the
    re-assembled rtl_out.bin byte-for-byte against the model recording.

Underrun lines (U) anywhere are a FAIL. The rendered event stream is
re-derived from the committed sequence JSON through the model harness; the
committed model trace is never trusted (independent re-render).

Also used for the committed negative control: with
--dut rtl/control/control_broken_mutant.sv (one changed queue-depth
constant) the comparison must FAIL.

Usage:
  python3 tools/compare_control_rtl.py --seq fixtures/control/sequences/ID.json \
      --run-dir DIR [--dut rtl/control/control_top.sv] [--out verdict.json]
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _rtl_compile_common import compile_and_run  # noqa: E402
from model.control import render_sequence  # noqa: E402
from model.control.engine_stub_counter import CounterStubEngine  # noqa: E402

TB = os.path.join(REPO, "rtl", "control", "tb_control.sv")
DUT_DEFAULT = os.path.join(REPO, "rtl", "control", "control_top.sv")


def write_events_hex(seq, path):
    """events.hex for tb_control: count, sample count, then 80-bit events."""
    from model.control import NAME_TO_TYPE, Event

    raw = seq["events"]
    events = []
    for k, e in enumerate(raw):
        events.append(Event(seq=k, t=e["t"], type=NAME_TO_TYPE[e["type"]],
                            p1=int(e.get("p1", 0)), p2=int(e.get("p2", 0))))
    with open(path, "w") as f:
        f.write("%020x\n" % len(events))
        f.write("%020x\n" % (seq["blocks"] * 32))
        for ev in events:
            f.write("%020x\n" % ev.to_word())
    return len(events)


def parse_tb(path):
    t = {}   # b -> [28 ints]
    e = {}   # b -> [(seq, type, p1, p2, slot, steal, status, flush)]
    x = {}   # b -> [(t, type, p1, p2)]
    m = {}   # (b, s) -> (l, r)
    u = []   # [(b, s)]
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            tag = parts[0]
            if tag == "Z":
                continue
            vals = [int(v) for v in parts[1:]]
            if tag == "T":
                t[vals[0]] = vals[1:]
            elif tag == "E":
                b, seq, typ, p1, p2, slot, steal, status, flush = vals
                e.setdefault(b, []).append((seq, typ, p1, p2, slot, steal,
                                            status, flush))
            elif tag == "X":
                b, tt, typ, p1, p2 = vals
                x.setdefault(b, []).append((tt, typ, p1, p2))
            elif tag == "M":
                b, s, l, r = vals
                m[(b, s)] = (l, r)
            elif tag == "U":
                u.append((vals[0], vals[1]))
    return {"t": t, "e": e, "x": x, "m": m, "u": u}


def compare(model_trace, model_out, rtl):
    fails = []
    checked = {"snapshots": 0, "snapshot_fields": 0, "decisions": 0,
               "drops": 0, "samples": 0}
    if rtl["u"]:
        fails.append("underrun lines present: %r" % rtl["u"][:4])
    blocks = {rec["b"] for rec in model_trace["blocks"]}
    if set(rtl["t"]) != blocks:
        fails.append("block set mismatch: model=%r rtl=%r"
                     % (sorted(blocks)[:8], sorted(rtl["t"])[:8]))
        return checked, fails
    for rec in model_trace["blocks"]:
        b = rec["b"]
        snap = rec["snapshot_after"]
        want_t = [snap["qcount"], snap["patch_id"], snap["active_count"]]
        for v in snap["voices"]:
            want_t += [1 if v["active"] else 0, v["note"], v["seq"]]
        got_t = rtl["t"].get(b)
        checked["snapshots"] += 1
        if got_t is None or len(got_t) != len(want_t):
            fails.append("block %d: missing/short T line" % b)
            continue
        for k, (w, g) in enumerate(zip(want_t, got_t)):
            checked["snapshot_fields"] += 1
            if w != g:
                fails.append("block %d T[%d]: model=%d rtl=%d" % (b, k, w, g))
        want_e = [(d["seq"], d["type"], d["p1"], d["p2"], d["slot"],
                   d["steal"], d["status"], d["flushes"])
                  for d in rec["decisions"]]
        got_e = rtl["e"].get(b, [])
        checked["decisions"] += len(want_e)
        if want_e != got_e:
            fails.append("block %d decisions: model=%r rtl=%r"
                         % (b, want_e[:4], got_e[:4]))
        want_x = [(d["t"], d["type"], d["p1"], d["p2"]) for d in rec["drops"]]
        got_x = rtl["x"].get(b, [])
        checked["drops"] += len(want_x)
        if want_x != got_x:
            fails.append("block %d drops: model=%r rtl=%r"
                         % (b, want_x[:4], got_x[:4]))
        for i in range(32):
            w = tuple(model_out[(b * 32 + i) * 4:(b * 32 + i) * 4 + 4])
            want = (int.from_bytes(w[0:2], "little"),
                    int.from_bytes(w[2:4], "little"))
            got = rtl["m"].get((b, i))
            checked["samples"] += 1
            if got != want:
                fails.append("block %d sample %d: model=%r rtl=%r"
                             % (b, i, want, got))
        if len(fails) > 40:
            break
    return checked, fails


def run_comparison(seq, run_dir, dut=DUT_DEFAULT):
    """Full model-vs-RTL comparison for one sequence dict.

    Re-renders the model independently (the committed model trace is never
    trusted), builds and runs the RTL in `run_dir`, writes events.hex /
    rtl_trace.txt / sim.log / verdict.json there, and returns the verdict.
    """
    os.makedirs(run_dir, exist_ok=True)
    trace, out, summary = render_sequence(seq, CounterStubEngine())
    write_events_hex(seq, os.path.join(run_dir, "events.hex"))
    # TB first, then the DUT, exactly as the hand-rolled step did; the
    # simulation is launched by name from inside run_dir with its stdout
    # captured to sim.log, and writes rtl_trace.txt there itself.
    compile_and_run(TB, run_dir, out_name="tb.vvp",
                    extra_sources=(os.path.abspath(dut),),
                    compile_in_workdir=True, run_by_name=True,
                    stdout_path=os.path.join(run_dir, "sim.log"),
                    trace_name=None)
    rtl = parse_tb(os.path.join(run_dir, "rtl_trace.txt"))
    checked, fails = compare(trace, out, rtl)

    # byte-identity of the assembled RTL recording vs the model recording
    rtl_bytes = bytearray()
    for rec in trace["blocks"]:
        b = rec["b"]
        for i in range(32):
            l, r = rtl["m"][(b, i)]
            rtl_bytes += l.to_bytes(2, "little") + r.to_bytes(2, "little")
    byte_identical = bytes(rtl_bytes) == out

    verdict = {
        "sequence": seq.get("id"),
        "dut": os.path.relpath(os.path.abspath(dut), REPO),
        "verdict": "PASS" if (not fails and byte_identical) else "FAIL",
        "byte_identical_outputs": byte_identical,
        "model_summary": summary,
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
    }
    with open(os.path.join(run_dir, "verdict.json"), "w") as f:
        json.dump(verdict, f, indent=2)
        f.write("\n")
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--dut", default=DUT_DEFAULT)
    args = ap.parse_args()

    with open(args.seq) as f:
        seq = json.load(f)
    verdict = run_comparison(seq, args.run_dir, args.dut)
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
