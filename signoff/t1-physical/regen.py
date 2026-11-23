#!/usr/bin/env python3
"""Regenerate the T1 physical-flow evidence (#544), one group at a time.

For each synthesized product group (netlist from signoff/t1-item1/): runs
`klt place-and-route`, then `klt drc`, `klt lvs` and `klt erc` on the routed
stream, with the pinned `klayout-tools` (signoff/requirements.txt) through
`uvx`, except ERC which runs under the per-check `ERC_KLT` override (0.9.2,
the first release with the gf180mcu antenna table; #803). Sequential and
single-threaded. Keeps only the commit-safe artifacts
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
# ERC alone runs under the newer klt that has the gf180mcu antenna table
# (#803; 2AMLogic/klayout-tools#4003, in v0.9.2, absent from v0.8.0). A
# per-check override only: the flow pin stays 0.8.0 for P&R/DRC/LVS, and
# regenerating those under a moved pin is deliberately out of scope.
ERC_KLT = "klayout-tools==0.9.2"
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


def klt(*args, version=None):
    cmd = ["uvx", "--from", version or PIN, "klt", *map(str, args)]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       env={**__import__("os").environ, "PDK": PDK})
    return p


def run_erc(gds, spec, top):
    """The one ERC invocation (#803): `ERC_KLT` with `--pdk gf180mcu`, shared
    by the full flow, `--checks-only`, `--erc-only` and the control, so no
    path can fall back to the flow pin and lose the antenna table. Returns
    (returncode, stdout) only for a usable tool report -- a parseable JSON
    report written by `ERC_KLT` -- and exits nonzero on an infrastructure
    failure (no report, wrong version) so a caller never replaces committed
    evidence with it. Valid nonzero ERC findings (exit 4) are returned."""
    p = klt("erc", gds, spec, "--top", top, "--pdk", "gf180mcu",
            "--format", "json", version=ERC_KLT)
    try:
        rep = json.loads(p.stdout)
        ok = (rep["provenance"]["klt_version"] == ERC_KLT.split("==")[1]
              and "coverage" in rep)
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        sys.exit(f"{top}: ERC under {ERC_KLT} produced no usable report "
                 f"(exit {p.returncode}); nothing written.\n{p.stderr[-2000:]}")
    return p.returncode, p.stdout


class unpacked_stream:
    """Context manager: `<top>.gds` for the duration of a refresh, restoring
    whatever was there before (bytes, or absence) on exit, success or not."""

    def __init__(self, top):
        self.d = BASE / top
        self.path = self.d / f"{top}.gds"
        self.packed = self.d / f"{top}.gds.gz"

    def __enter__(self):
        self.prior = self.path.read_bytes() if self.path.exists() else None
        self.path.write_bytes(gzip.decompress(self.packed.read_bytes()))
        return self.path

    def __exit__(self, *exc):
        if self.prior is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.write_bytes(self.prior)
        return False


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


def neutral_paths(text):
    """Machine-neutral form of a payload: ROOT -> <repo>, then home -> <home>.

    ROOT is substituted first: it sits under home, so the home replacement
    only fires on a path elsewhere under home. Same tokens and ordering as
    signoff/t1-item1/regen.py's neutral_paths (#714), so a pnr.failure.txt
    record committed from any worktree or host carries no machine-local
    path and later re-runs reproduce it byte for byte.
    """
    return text.replace(str(ROOT), "<repo>").replace(str(pathlib.Path.home()), "<home>")


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
        (d / "pnr.failure.txt").write_text(
            neutral_paths(p.stdout + "\n" + p.stderr))
        write_json(d / "exit_status.json", status)
        shutil.rmtree(scratch, ignore_errors=True)
        print(top, "place-and-route FAILED", flush=True)
        return
    out = scratch / "place-and-route"
    shutil.copy(out / f"{top}.gds", d / f"{top}.gds")
    shutil.copy(out / f"{top}.v", d / f"{top}.v")
    shutil.rmtree(scratch, ignore_errors=True)
    check_group(top, status)


def check_group(top, status, reuse_drc=False):
    """DRC, LVS and ERC on the routed stream already in the group directory."""
    d = BASE / top
    gds = (d / f"{top}.gds").relative_to(ROOT)
    if reuse_drc:
        # Resume after an interrupted run: the DRC report is already on disk;
        # its exit code is 0 when clean, 3 (klt's "findings") otherwise.
        rep = json.loads((d / "drc.report.json").read_text())
        status["drc"] = 0 if rep["status"] == "clean" else 3
    else:
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
    status["erc"], out = run_erc(gds, spec, top)
    (d / "erc.report.json").write_text(out)

    write_json(d / "exit_status.json", status)
    pack(d)
    print(top, status, flush=True)


def erc_only(top):
    """ERC refresh under `ERC_KLT` on the *committed* stream (#803).

    Unpacks `<top>.gds.gz` (the reports bind the uncompressed stream) to
    `<top>.gds`, runs `run_erc` against `erc-supply-spec.json`, and only after
    a usable report rewrites `erc.report.json.gz` and the `erc` field of
    `exit_status.json`. Every other committed artifact stays byte-identical,
    and a pre-existing unpacked stream is restored, not removed.
    """
    d = BASE / top
    spec = (BASE / "erc-supply-spec.json").relative_to(ROOT)
    with unpacked_stream(top) as gds:
        rc, out = run_erc(gds.relative_to(ROOT), spec, top)
    status = json.loads((d / "exit_status.json").read_text())
    status["erc"] = rc
    (d / "erc.report.json").write_text(out)
    write_json(d / "exit_status.json", status)
    pack_erc(d)
    print(top, "erc", rc, flush=True)


def pack_erc(d):
    (d / "erc.report.json.gz").write_bytes(
        gzip.compress((d / "erc.report.json").read_bytes(), 9, mtime=0))
    (d / "erc.report.json").unlink()


def erc_control():
    """The lowercase supply-spec control (#803): same wavetable_core stream,
    same klt version as `erc_only`, but the retained pre-mapping spec whose
    role names miss the gf180mcu table keys. The committed report must show
    every intended metal level skipped with `missing_antenna_limit` -- the
    coverage check in tests/test_t1_physical_flow.py rejects it. Only the
    `erc` field of the control's exit record is touched."""
    top = "wavetable_core"
    nc = BASE / "negative-control"
    spec = (nc / "erc-supply-spec-lowercase.json").relative_to(ROOT)
    with unpacked_stream(top) as gds:
        rc, out = run_erc(gds.relative_to(ROOT), spec, top)
    (nc / "erc.report.json").write_text(out)
    pack_erc(nc)
    status = json.loads((nc / "exit_status.json").read_text())
    status["erc"] = rc
    write_json(nc / "exit_status.json", status)
    print("negative-control erc", rc, flush=True)


if __name__ == "__main__":
    # `--checks-only` resumes after place-and-route: reuses the unpacked
    # `<g>.gds` and `pnr.report.json` left by an interrupted run;
    # `--reuse-drc` also keeps the unpacked `drc.report.json`. `--erc-only`
    # (#803) refreshes only the ERC reports under `ERC_KLT` on the committed
    # streams; `--erc-control` regenerates the lowercase negative control.
    args = sys.argv[1:]
    if "--erc-control" in args:
        erc_control()
        sys.exit(0)
    checks_only = "--checks-only" in args
    erc_only_mode = "--erc-only" in args
    only = {a for a in args if not a.startswith("--")}
    for top in DIE_UM:
        if only and top not in only:
            continue
        if erc_only_mode:
            erc_only(top)
        elif checks_only:
            check_group(top, {"place-and-route": 0},
                        reuse_drc="--reuse-drc" in args)
        else:
            run_group(top)
