#!/usr/bin/env python3
"""Regenerate the T1 physical-flow evidence (#544), one group at a time.

For each synthesized product group (netlist from signoff/t1-item1/): runs
`klt place-and-route`, then `klt drc`, `klt lvs` and `klt erc` on the routed
stream, with the pinned `klayout-tools` (signoff/requirements.txt) through
`uvx`. Sequential and single-threaded. Keeps only the commit-safe artifacts
(requests, reports, the routed stream and as-built netlist) and removes the
`.klt/` scratch directory.

Per-block physical-flow evidence only: no timing closure, no corners, no
"gf180mcu implementation" claim. DRC/LVS/ERC outcomes are recorded as the
tools report them, never waived.
"""
import gzip
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "signoff" / "t1-physical"
CELL_LIBRARY = "gf180mcu_fd_sc_mcu9t5v0"
SITE = "GF018hv5v_green_sc9"
PDK = "gf180mcuD"
PIN = (ROOT / "signoff" / "requirements.txt").read_text().strip()
# Square die edge (um): sized for the top-level pin count (PPL-0024) and a
# routable utilization. Block-level, pin-limited; not a floorplan proposal.
DIE_UM = {"wavetable_core": 500, "control_top": 1000, "ext_mem_instr": 1100}
LVS_POWER = {"VDD": "VDD", "VNW": "VDD", "VPW": "VSS", "VSS": "VSS"}
# Power delivery: the ORFS `gf180mcu_9t_6M` strap geometry, written out so two
# flow settings can differ from the preset (#544 triage; measured on
# wavetable_core, DRC 19850 -> 0 with both changes, 19096 with the tapcell
# change alone, 19096 with `split_cuts` alone):
#  - `tapcell.distance_um` 30 (preset: 100). The curated deck's
#    comp.tap_distance.{nwell,psub}.mv.1 rules cap tap distance at 15 um;
#    a 100 um pitch cannot meet them.
#  - no `split_cuts` on the Metal1-Metal4 connect (preset: Metal3 0.128).
#    pdngen's 0.128 um cuts are what produce every metal2/3/4.ongrid.1,
#    via2/3.ongrid.1 and via2/3.width.1 hit (VIA_via2_3_* cells). `ongrid`
#    is kept as in the preset.
POWER = {
    "straps": [
        {"layer": "Metal1", "width_um": 0.9, "pitch_um": 5.04,
         "offset_um": 0.0, "followpins": True},
        {"layer": "Metal4", "width_um": 4.48, "pitch_um": 44.8,
         "offset_um": 22.4, "spacing_um": 0.56},
        {"layer": "Metal5", "width_um": 4.48, "pitch_um": 89.6,
         "offset_um": 44.8},
    ],
    "connects": [
        {"layers": ["Metal1", "Metal4"], "max_columns": 5,
         "ongrid": ["Metal2", "Metal3", "Metal4"]},
        {"layers": ["Metal4", "Metal5"]},
    ],
    "tapcell": {"distance_um": 30},
}


def klt(*args):
    cmd = ["uvx", "--from", PIN, "klt", *map(str, args)]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       env={**__import__("os").environ, "PDK": PDK})
    return p


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


PACKED = ("*.gds", "drc.report.json", "erc.report.json", "lvs.report.json",
          "pnr.report.json")


def pack(d):
    """gzip the large artifacts deterministically (mtime 0) to keep the repo
    small. Hashes inside the reports bind the *uncompressed* stream; `gunzip`
    before any `klt ... --check`."""
    for pat in PACKED:
        for f in d.glob(pat):
            f.with_name(f.name + ".gz").write_bytes(
                gzip.compress(f.read_bytes(), 9, mtime=0))
            f.unlink()


def run_group(top):
    d = BASE / top
    d.mkdir(parents=True, exist_ok=True)
    edge = DIE_UM[top]
    pnr_req = {
        "schema": "klt.place-and-route.request/1",
        "engine": "openroad",
        "netlist": f"../../t1-item1/{top}/{top}_synth.v",
        "hdl_toplevel": top,
        "pdk": {"cell_library": CELL_LIBRARY, "corner": "tt_025C_1v80"},
        "floorplan": {"method": "explicit", "die_area_um": [0, 0, edge, edge],
                      "core_area_um": [10, 10, edge - 10, edge - 10],
                      "site": SITE},
        "io": {"layer_h": "Metal3", "layer_v": "Metal2"},
        "power": POWER,
        "constraints": {"clock_port": "clk", "clock_period_ns": 20.0},
        "seed": 1,
        "target_stage": "route",
        "portable_paths": True,
    }
    write_json(d / "request.json", pnr_req)
    scratch = d / ".klt"
    shutil.rmtree(scratch, ignore_errors=True)
    status = {}
    p = klt("place-and-route", (d / "request.json").relative_to(ROOT),
            "--pdk", PDK, "--format", "json")
    status["place-and-route"] = p.returncode
    (d / "pnr.report.json").write_text(p.stdout)
    if p.returncode != 0:
        (d / "pnr.failure.txt").write_text(p.stdout + "\n" + p.stderr)
        write_json(d / "exit_status.json", status)
        shutil.rmtree(scratch, ignore_errors=True)
        print(top, "place-and-route FAILED", flush=True)
        return
    out = scratch / "place-and-route"
    shutil.copy(out / f"{top}.gds", d / f"{top}.gds")
    shutil.copy(out / f"{top}.v", d / f"{top}.v")
    shutil.rmtree(scratch, ignore_errors=True)
    check_group(top, status)


def check_group(top, status):
    """DRC, LVS and ERC on the routed stream already in the group directory."""
    d = BASE / top
    gds = (d / f"{top}.gds").relative_to(ROOT)
    p = klt("drc", gds, "--deck", "gf180mcu", "--pdk", PDK, "--format", "json")
    status["drc"] = p.returncode
    (d / "drc.report.json").write_text(p.stdout)

    write_json(d / "lvs.request.json", {
        "schema": "klt.lvs.request/1",
        "engine": "klayout",
        "layout": {"file": f"{top}.gds", "deck": "gf180mcu", "top": top,
                   "abstract_cells": [f"{CELL_LIBRARY}__*"]},
        "reference": {"netlist": f"{top}.v", "form": "gate-level-verilog",
                      "library": CELL_LIBRARY, "top": top},
        "options": {"power_connectivity": {"expected_nets": LVS_POWER}},
        "portable_paths": True,
    })
    p = klt("lvs", (d / "lvs.request.json").relative_to(ROOT), "--format", "json")
    status["lvs"] = p.returncode
    (d / "lvs.report.json").write_text(p.stdout)

    spec = (BASE / "erc-supply-spec.json").relative_to(ROOT)
    p = klt("erc", gds, spec, "--top", top, "--format", "json")
    status["erc"] = p.returncode
    (d / "erc.report.json").write_text(p.stdout)

    write_json(d / "exit_status.json", status)
    pack(d)
    print(top, status, flush=True)


if __name__ == "__main__":
    # `--checks-only` resumes after place-and-route: reuses the unpacked
    # `<g>.gds` and `pnr.report.json` left by an interrupted run.
    args = sys.argv[1:]
    checks_only = "--checks-only" in args
    only = {a for a in args if not a.startswith("--")}
    for top in DIE_UM:
        if only and top not in only:
            continue
        if checks_only:
            check_group(top, {"place-and-route": 0})
        else:
            run_group(top)
