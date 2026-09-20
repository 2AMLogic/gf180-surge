#!/usr/bin/env python3
"""Render the committed SXT-021 control fixtures (deterministic).

For every fixtures/control/sequences/ctl-*.json this script:
  1. renders the model (trace + stereo output recording + summary),
  2. builds and runs the RTL control plane + stub slot under iverilog,
  3. checks EXACT schedule equality and byte-identity of the recordings
     (tools/compare_control_rtl.py),
  4. writes fixtures/control/<id>/ artifacts + record.json,
  5. rewrites fixtures/control/manifest.json (sha256 of every artifact).

Re-running with the same inputs must be byte-identical (no clocks, no
randomness; the only environment-dependent step is the iverilog/vvp
invocation, whose outputs are text traces fully checked by the comparator).

No underruns are tolerated in the committed fixtures; the overload fixtures
are EXPECTED to carry explicit detected overload statuses (they are the
bounded-overload evidence, not corruption).
"""

import glob
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tools.compare_control_rtl import run_comparison  # noqa: E402
from model.control import render_sequence  # noqa: E402
from model.control.engine_stub_counter import CounterStubEngine  # noqa: E402
from model.control.accounting import account_schedule  # noqa: E402

SEQ_DIR = os.path.join(REPO, "fixtures", "control", "sequences")
OUT_DIR = os.path.join(REPO, "fixtures", "control")
DUT = os.path.join(REPO, "rtl", "control", "control_top.sv")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def render_one(seq_path):
    with open(seq_path) as f:
        seq = json.load(f)
    ident = seq["id"]
    run_dir = os.path.join(OUT_DIR, ident)
    os.makedirs(run_dir, exist_ok=True)

    trace, out, summary = render_sequence(seq, CounterStubEngine())
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(trace, f, sort_keys=True, indent=1)
        f.write("\n")
    with open(os.path.join(run_dir, "model_out.bin"), "wb") as f:
        f.write(out)

    verdict = run_comparison(seq, run_dir, DUT)
    # tb.vvp / sim.log are regenerable and not deterministic bytes
    # (compiler output / machine paths); they are never committed
    for junk in ("tb.vvp", "sim.log"):
        try:
            os.remove(os.path.join(run_dir, junk))
        except FileNotFoundError:
            pass

    # Re-assemble the RTL-side recording from the verified RTL trace so the
    # committed artifact is genuinely the RTL output (byte-identical to the
    # model recording by the verdict).
    from tools.compare_control_rtl import parse_tb
    rtl = parse_tb(os.path.join(run_dir, "rtl_trace.txt"))
    with open(os.path.join(run_dir, "rtl_out.bin"), "wb") as f:
        for rec in trace["blocks"]:
            b = rec["b"]
            for i in range(32):
                l, r = rtl["m"][(b, i)]
                f.write(l.to_bytes(2, "little") + r.to_bytes(2, "little"))

    # cmp the two committed recordings (independent of the verdict logic)
    model_bytes = open(os.path.join(run_dir, "model_out.bin"), "rb").read()
    rtl_bytes = open(os.path.join(run_dir, "rtl_out.bin"), "rb").read()
    byte_cmp = (model_bytes == rtl_bytes)

    overload = {
        "reserve_exceeded_blocks": summary["reserve_exceeded_blocks"],
        "queue_overflow_blocks": summary["queue_overflow_blocks"],
        "drops_total": summary["drops_total"],
        "flushed_total": summary["flushed_total"],
        "max_latency_samples": summary["max_latency_samples"],
        "underruns": summary["underruns"],
        "declared_reserve_per_block": 8,
        "closes_declared_schedule": summary["reserve_exceeded_blocks"] == 0,
        "detection": (
            "explicit event_reserve_exceeded/queue_overflow statuses in "
            "model_trace.json; explicit X drop records in rtl_trace.txt"
            if summary["queue_overflow_blocks"] or
            summary["reserve_exceeded_blocks"] else "no overload"),
    }
    declared = account_schedule(8, 192000000)
    record = {
        "id": ident,
        "sequence_sha256": sha256(seq_path),
        "model_engine": CounterStubEngine.name,
        "dut": "rtl/control/control_top.sv",
        "verdict": verdict["verdict"],
        "byte_identical_model_vs_rtl": byte_cmp,
        "checked": verdict["checked"],
        "mismatches": verdict["mismatches"],
        "summary": summary,
        "overload": overload,
        "declared_schedule_closure_192mhz": {
            "closure": declared["closure"],
            "used_cycles_per_frame": declared["used_cycles_per_frame"]["total"],
            "budget_cycles_per_frame": declared["budget_cycles_per_frame"],
        },
        "claim_scope": "control plane + stub slot only; no DSP, fidelity, or "
                       "hardware claim",
    }
    with open(os.path.join(run_dir, "record.json"), "w") as f:
        json.dump(record, f, sort_keys=True, indent=1)
        f.write("\n")
    return record


def main():
    records = []
    for seq_path in sorted(glob.glob(os.path.join(SEQ_DIR, "ctl-*.json"))):
        rec = render_one(seq_path)
        records.append(rec)
        print("%-28s %s byte-identical=%s underruns=%d drops=%d "
              "reserve_exceeded=%d" %
              (rec["id"], rec["verdict"], rec["byte_identical_model_vs_rtl"],
               rec["overload"]["underruns"], rec["overload"]["drops_total"],
               rec["overload"]["reserve_exceeded_blocks"]))

    ok = all(r["verdict"] == "PASS" and r["byte_identical_model_vs_rtl"]
             and r["overload"]["underruns"] == 0 for r in records)
    exp_overload = {"ctl-burst-overload-v1", "ctl-queue-overflow-v1"}
    for r in records:
        if r["id"] in exp_overload:
            ok = ok and (r["overload"]["queue_overflow_blocks"] > 0
                         or r["overload"]["reserve_exceeded_blocks"] > 0)
        else:
            ok = ok and r["overload"]["queue_overflow_blocks"] == 0 \
                and r["overload"]["reserve_exceeded_blocks"] == 0

    files = {}
    for base, _, names in os.walk(OUT_DIR):
        for n in sorted(names):
            p = os.path.join(base, n)
            rel = os.path.relpath(p, REPO)
            if rel.endswith("manifest.json"):
                continue
            files[rel] = sha256(p)
    manifest = {
        "manifest_version": 1,
        "issue": "SXT-021 (#14)",
        "claim_scope": "control-plane continuous output through a named "
                       "stub engine; model-vs-RTL schedule equality and "
                       "byte-identical stereo recordings; no DSP, fidelity, "
                       "or hardware claim",
        "dut": "rtl/control/control_top.sv",
        "comparator": "tools/compare_control_rtl.py",
        "records": records,
        "files": dict(sorted(files.items())),
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, sort_keys=True, indent=1)
        f.write("\n")
    print("manifest: %d files; overall %s" %
          (len(files), "PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
