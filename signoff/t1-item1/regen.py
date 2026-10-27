#!/usr/bin/env python3
"""Regenerate the T1 item-1 synthesis evidence (#537), one group at a time.

Writes signoff/t1-item1/<group>/request.json from rtl/lint_manifest.json,
runs `klt synthesize` (sequential, single-threaded), and keeps only the
commit-safe artifacts: request, report.json, netlist, synth_<top>.ys.
Synthesizability evidence only: no P&R, timing, signoff or equivalence claim.
"""
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "signoff" / "t1-item1"
PDK = "gf180mcuD"
CELL_LIBRARY = "gf180mcu_fd_sc_mcu9t5v0"


def main(only):
    manifest = json.loads((ROOT / "rtl" / "lint_manifest.json").read_text())
    for g in manifest["groups"]:
        if only and g["id"] not in only:
            continue
        d = BASE / g["id"]
        d.mkdir(parents=True, exist_ok=True)
        out = d / "out"
        shutil.rmtree(out, ignore_errors=True)
        rel = "../../../" + g["source"]
        req = {
            "schema": "klt.synthesize.request/1",
            "engine": "yosys",
            "sources": [rel],
            "hdl_toplevel": g["top"],
            "pdk": {"cell_library": CELL_LIBRARY},
            "constraints": {"clock_period_ns": None},
            "outputs": {"dir": "out"},
        }
        (d / "request.json").write_text(json.dumps(req, indent=2) + "\n")
        p = subprocess.run(
            ["klt", "synthesize", str(d / "request.json"), "--pdk", PDK,
             "--format", "json"],
            check=False, capture_output=True, text=True, cwd=ROOT)
        (d / "exit_status.txt").write_text(f"{p.returncode}\n")
        if p.returncode == 0:
            (d / "report.json").write_text(p.stdout)
            top = g["top"]
            shutil.copy(out / f"{top}_synth.v", d / f"{top}_synth.v")
            shutil.copy(out / f"synth_{top}.ys", d / f"synth_{top}.ys")
        else:
            (d / "failure.txt").write_text(p.stdout + "\n" + p.stderr)
        shutil.rmtree(out, ignore_errors=True)
        print(g["id"], p.returncode, flush=True)


if __name__ == "__main__":
    main(set(sys.argv[1:]))
