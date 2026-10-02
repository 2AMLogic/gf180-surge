#!/usr/bin/env python3
"""SXT-041 cycle/state cost report for the scene-LFO (ms_slfo1..6) slice.

Measures, on the EXACT RTL schedule that `tools/compare_slfo_rtl_model.py`
proves equal to the frozen model:

  * `qmul` invocations per render — counted by `tb_slfo.sv` itself
    (`DONE slfo-qmuls=<n> advances=<m>`), i.e. the multiplies the frozen
    schedule actually issues, not an estimate;
  * per-instance and per-scene STATE bits, from
    `slfo_model.SceneLfoBank.state_bits()` (the model is the state of
    record);
  * the scene-scope event/routing op counts (attacks, releases, route
    applications) taken from the model trace.

Then it RECORDS the divergence against SXT-016 / SXT-015 rather than
reconciling it away: at this pin SXT-016 has NO scene-LFO probe row (its
nearest basis is `probe_scheduler__event_queue_and_control`, whose per-event
assumption names "8 envelope/LFO trigger writes, 12 routing ops"), so these
are the first concrete per-kernel numbers for this kernel and are offered as
an SXT-016 refinement input.

NO technology claim of any kind is made: `qmul`-per-render and state bits are
schedule properties of a behavioral iverilog simulation. No gf180mcu/FPGA
synthesis, timing, area or power result follows from them.

Usage:
  python3 tools/slfo_cost_report.py --run-dir DIR --out-json F --out-txt F
"""

import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import slfo_model as sm  # noqa: E402

TB = os.path.join(REPO, "rtl", "voice", "tb_slfo.sv")
SR = 48000
BLOCK = 32
PROBE_BASIS = ("reports/sxt-016/probes/"
               "probe_scheduler__event_queue_and_control__a24__m32__"
               "onchip.json")


def run_tb(run_dir, tb):
    vvp = os.path.abspath(os.path.join(run_dir, "tb_slfo_cost.vvp"))
    subprocess.run(["iverilog", "-g2012", "-o", vvp, tb], check=True,
                   cwd=run_dir, capture_output=True, text=True)
    r = subprocess.run(["vvp", vvp], check=True, cwd=run_dir,
                       capture_output=True, text=True)
    m = re.search(r"DONE slfo-qmuls=(\d+) advances=(\d+)", r.stdout)
    if not m:
        raise SystemExit(f"testbench did not report its counters:\n{r.stdout}")
    return int(m.group(1)), int(m.group(2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out-json")
    ap.add_argument("--out-txt")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        tr = json.load(f)

    qmuls, advances = run_tb(args.run_dir, args.tb)
    blocks = len(tr["blocks"])
    settle = tr["settle"]["settle_blocks"]
    frames = blocks * BLOCK
    attacks = sum(1 for e in tr["bank_events"] if e["attack"])
    releases = sum(1 for e in tr["bank_events"] if e["release"])
    with open(os.path.join(args.run_dir, "rtl", "slfo_routes.hex")) as f:
        n_routes = int(f.readline().strip(), 16)
    dest_classes = len(tr["slfo_route_sums_word_order"])

    bits = sm.state_bits()
    per_instance_bits = sum(bits.values())

    probe_path = os.path.join(REPO, PROBE_BASIS)
    probe = None
    if os.path.exists(probe_path):
        with open(probe_path) as f:
            p = json.load(f)
        probe = {
            "path": PROBE_BASIS,
            "id": p.get("probe_id") or p.get("id"),
            "control_cycles_per_frame": (
                p.get("closure_at_clocks", {}).get("48000000", {})
                .get("control_cycles_per_frame")),
            "has_scene_lfo_row": False,
        }

    out = {
        "issue": "SXT-041",
        "claim_scope": "Schedule properties of a behavioral iverilog "
                       "simulation proven integer-equal to the frozen model. "
                       "NOT a synthesis, timing, area or power result; no "
                       "gf180mcu or FPGA claim follows.",
        "sequence": tr["sequence"],
        "render": {"blocks": blocks, "settle_blocks": settle,
                   "frames": frames, "sample_rate": SR},
        "measured": {
            "slfo_qmuls_per_render": qmuls,
            "bank_advances": advances,
            "qmuls_per_advance": round(qmuls / advances, 4) if advances else 0,
            "mac_per_output_sample": round(qmuls / frames, 6),
            "scene_attacks": attacks,
            "scene_releases": releases,
            "scene_routes": n_routes,
            "destination_classes": dest_classes,
            "route_applications_per_block": n_routes,
            "note": "bank_advances == settle_blocks + blocks: the six "
                    "instances advance unconditionally every block, which is "
                    "the S5 scene-scope schedule",
        },
        "state": {
            "per_instance_bits": bits,
            "per_instance_total_bits": per_instance_bits,
            "instances_per_scene": sm.N_SCENE_LFOS,
            "per_scene_total_bits": per_instance_bits * sm.N_SCENE_LFOS,
            "comparison_to_voice_lfo": "SXT-032 reported ~146 bits/instance "
                                       "x 6 instances PER VOICE. The scene "
                                       "LFOs are six instances PER SCENE, so "
                                       "the same per-instance state is paid "
                                       "once for the whole scene instead of "
                                       "once per concurrent voice - recorded, "
                                       "not offered as a budget claim.",
        },
        "sxt016_sxt015_divergence": {
            "scene_lfo_probe_row_exists": False,
            "nearest_basis": probe,
            "divergence": "SXT-016 has no scene-LFO probe row at this pin "
                          "(the leaf's own cost note anticipated "
                          "'[ESTIMATE] pending SXT-016 refinement'). The "
                          "scheduler probe's per-event assumption names '8 "
                          "envelope/LFO trigger writes, 12 routing ops'; the "
                          "measured scene-LFO schedule issues "
                          f"{6 * 4} state writes per scene attack (six "
                          "instances x phase/eg_state/env_val/env_phase) and "
                          f"{n_routes} route applications per block. Recorded "
                          "as the first concrete numbers for this kernel, "
                          "NOT reconciled against the probe.",
        },
    }

    txt = [
        "SXT-041 scene-LFO cycle/state cost report",
        "=" * 56,
        f"sequence              {tr['sequence']}",
        f"blocks (+settle)      {blocks} (+{settle})",
        f"output frames         {frames} @ {SR} Hz",
        "",
        f"slfo qmuls / render   {qmuls}",
        f"bank advances         {advances}",
        f"qmuls / advance       {out['measured']['qmuls_per_advance']}",
        f"MAC / output sample   {out['measured']['mac_per_output_sample']}",
        f"scene attacks         {attacks}",
        f"scene releases        {releases}",
        f"scene routes          {n_routes} into {dest_classes} destination "
        f"classes, applied once per block (shared by every voice)",
        "",
        f"state / instance      {per_instance_bits} bits "
        f"({', '.join(f'{k} {v}' for k, v in sorted(bits.items()))})",
        f"state / scene         {per_instance_bits * sm.N_SCENE_LFOS} bits "
        f"({sm.N_SCENE_LFOS} instances)",
        "",
        "SXT-016 / SXT-015: no scene-LFO probe row exists at this pin;",
        "divergence RECORDED, not reconciled (see the JSON sibling).",
        "",
        "NO synthesis, timing, area, power or hardware-playback claim.",
    ]

    print("\n".join(txt))
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(out, f, indent=2, sort_keys=True)
            f.write("\n")
    if args.out_txt:
        with open(args.out_txt, "w") as f:
            f.write("\n".join(txt) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
