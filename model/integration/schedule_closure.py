#!/usr/bin/env python3
"""SXT-025: effects-active schedule closure + memory-stall accounting.

Replaces the SXT-021 stub-slot placeholder with the real landed-kernel row
and closes the per-sample-period schedule under worst-case assumptions with
effects active:

    gross  [cyc / 48 kHz sample period] = F / Fs
    budget = gross * (1 - 0.2 declared reserve)
    used   = control (72, SXT-016 probe row)
           + events (88 * worst coincident events per block, SXT-016)
           + Reverb1 composite_ext_E2 kernel (835 cyc, INCLUDES the
             external-memory stall terms under A-EXT-2: 16-bit SRAM burst,
             4 cycles/32-bit word sustained + 10-cycle re-seek, full access
             latency charged per access; probe
             reports/sxt-016/probes/probe_fx_reverb1__reverb1_composite_ext_E2__a24__m32__e2.json)
           + transfer (8, A-CTL-1) + contention (990, A-CTL-2)

Memory-stall accounting reconciles the RENDERED run's measured external
traffic (from the trace ledger) against the SXT-024 traffic model and the
SXT-016 probe byte rate, per instance, and states the external-writable
buffer requirement (never flash).

OVERFLOW is an explicit rejection object, never silent. All cycle numbers
are candidate-clock arithmetic under named assumptions (A-CLK class) --
NOT a gf180mcu synthesis, timing, or hardware claim.

Original to this repository (Apache-2.0).
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

SAMPLE_RATE_HZ = 48000
RESERVE_FRACTION = 0.2
CTRL_CYCLES_PER_FRAME = 72
CYCLES_PER_EVENT = 88
TRANSFER_CYCLES_PER_FRAME = 8
CONTENTION_CYCLES_PER_FRAME = 990
KERNEL_CYCLES_PER_FRAME = {
    "reverb1_composite_ext_E2": 835,   # includes ext-memory stall terms
}
CLOCK_CANDIDATES_HZ = [48000000, 96000000, 192000000, 480000000]
PROBE = ("reports/sxt-016/probes/"
         "probe_fx_reverb1__reverb1_composite_ext_E2__a24__m32__e2.json")
CTRL_PROBE = ("reports/sxt-016/probes/"
              "probe_scheduler__event_queue_and_control__a24__m32__onchip.json")


def account(kernel_row, worst_events_per_block, clock_hz, instances=1):
    gross = clock_hz / SAMPLE_RATE_HZ
    budget = gross * (1 - RESERVE_FRACTION)
    parts = {
        "control": CTRL_CYCLES_PER_FRAME,
        "events": worst_events_per_block * CYCLES_PER_EVENT,
        "fx_kernels": instances * KERNEL_CYCLES_PER_FRAME[kernel_row],
        "transfer": TRANSFER_CYCLES_PER_FRAME,
        "contention": CONTENTION_CYCLES_PER_FRAME,
    }
    used = sum(parts.values())
    row = {
        "clock_hz": clock_hz,
        "kernel": kernel_row,
        "reverb1_instances": instances,
        "worst_events_per_block": worst_events_per_block,
        "gross_cycles_per_frame": gross,
        "budget_cycles_per_frame": budget,
        "used_cycles_per_frame": parts,
        "used_total": used,
        "utilization_fraction": round(used / gross, 6),
        "closure": "OVERFLOW" if used > budget else "within_budget",
    }
    if used > budget:
        row["rejection"] = {
            "code": "schedule_budget_overflow",
            "detail": {"used": used, "budget": budget,
                       "clock_hz": clock_hz},
            "note": "explicit rejection, never silent (plan section 5)",
        }
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True,
                    help="trace__<seq>.json from the integration run")
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "sxt-025", "schedule-closure.json"))
    args = ap.parse_args()
    trace = json.load(open(args.trace))
    worst_events = max(1, trace["event_timing"]["worst_events_per_block"])
    instances = sum(1 for i in trace["traffic_ledger"]
                    if i.get("traffic"))
    # every rendered block must have had its FX turn: the ledger totals are
    # exact multiples of the per-frame traffic
    rows = {str(f): account("reverb1_composite_ext_E2", worst_events, f,
                            instances)
            for f in CLOCK_CANDIDATES_HZ}

    # memory-stall reconciliation per instance
    mem = []
    for inst in trace["traffic_ledger"]:
        t = inst.get("traffic")
        if not t:
            continue
        mem.append({
            "slot": inst["slot"],
            "kind": inst["kind"],
            "words_per_output_frame_measured": t["words_per_output_frame"],
            "bytes_per_output_frame_measured": t["bytes_per_output_frame"],
            "reconciles_sxt024_model": t["words_per_output_frame"] == 34
                                       and t["bytes_per_output_frame"] == 136,
            "bytes_per_s_at_48k": t["bytes_per_output_frame"] * SAMPLE_RATE_HZ,
            "sxt016_probe_bytes_per_s": 6528000,
            "external_writable_buffer_bytes": t["buffer_bytes"],
            "flash_is_not_writable_storage": True,
        })

    out = {
        "issue": "SXT-025 (#18)",
        "claim_scope": "candidate-clock arithmetic under named assumptions "
                       "(A-CLK, A-EXT-2, A-CTL-1/2); no gf180mcu synthesis, "
                       "place-and-route, signoff, or hardware claim. The "
                       "kernel row REPLACES the SXT-021 stub placeholder "
                       "(2 cyc) with the landed Reverb1 E2 row including "
                       "external-memory stalls.",
        "inputs": {
            "trace": os.path.relpath(args.trace, REPO),
            "kernel_probe": PROBE,
            "control_probe": CTRL_PROBE,
            "kernel_cycles_per_frame": KERNEL_CYCLES_PER_FRAME,
            "kernel_row_note": "835 cyc/sample-period INCLUDES ext-memory "
                               "stall terms (latency-bound 612 of 835) per "
                               "A-EXT-2 with full access latency charged",
        },
        "worst_events_per_block_measured": worst_events,
        "event_reserve_per_block": 8,
        "event_reserve_respected": worst_events <= 8,
        "closure_at_clocks": rows,
        "memory_stall_accounting": mem,
        "render_span": {
            "blocks_total": trace["blocks_total"],
            "frames": trace["frames"],
            "tail_frames": trace["tail"]["tail_frames"],
        },
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({
        "worst_events_per_block": worst_events,
        "closures": {k: v["closure"] for k, v in rows.items()},
        "used_at_192mhz": rows["192000000"]["used_total"],
        "budget_at_192mhz": rows["192000000"]["budget_cycles_per_frame"],
        "stall_reconciliation_ok": all(m["reconciles_sxt024_model"]
                                       for m in mem),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
