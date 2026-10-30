#!/usr/bin/env python3
"""Regenerate the T1 physical-flow negative controls (#544).

Each control is a deliberately violated input that must make the targeted
`klt` check FAIL with a named finding, so the DRC/LVS evidence in
signoff/t1-physical/ is shown to be able to fail:

- DRC: `drc-sliver.gds`, one Metal2 rectangle 0.1 x 5 um (gf180mcu Metal2
  minimum width is 0.28 um) -> `klt drc` must report `metal2.width.1`.
- LVS: the committed clean `wavetable_core` routed stream checked against its
  own as-built netlist with ONE instance mutated (`mutation.json`: a `tieh`
  turned into a `tiel`) -> `klt lvs` must report a mismatch. The mutated
  netlist is not stored; the test re-derives it from the committed netlist.

Pinned `klayout-tools` (signoff/requirements.txt) through `uvx`; sequential.
Per-input negative controls only: they show the checks can fail, not that the
flow output is correct.
"""
import gzip
import json
import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = ROOT / "signoff" / "t1-physical"
NC = BASE / "negative-control"
PIN = (ROOT / "signoff" / "requirements.txt").read_text().strip()
PDK = "gf180mcuD"
CELL_LIBRARY = "gf180mcu_fd_sc_mcu9t5v0"
LVS_POWER = {"VDD": "VDD", "VNW": "VDD", "VPW": "VSS", "VSS": "VSS"}
MUTATION = {
    "base_netlist": "signoff/t1-physical/wavetable_core/wavetable_core.v",
    "line": 624,
    "from": " gf180mcu_fd_sc_mcu9t5v0__tieh _0513_ (.Z(_0000_));",
    "to": " gf180mcu_fd_sc_mcu9t5v0__tiel _0513_ (.ZN(_0000_));",
}

BUILD_GDS = '''
import klayout.db as db
ly = db.Layout()
ly.dbu = 0.001
top = ly.create_cell("drc_sliver")
top.shapes(ly.layer(36, 0)).insert(db.Box(0, 0, 100, 5000))  # Metal2, 0.1 x 5 um
o = db.SaveLayoutOptions()
o.format = "GDS2"
o.gds2_write_timestamps = False
ly.write("signoff/t1-physical/negative-control/drc-sliver.gds", o)
'''


def uvx(*args, py=False):
    cmd = ["uvx", "--from", PIN, *args]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PDK": PDK})


def pack(path):
    path.with_name(path.name + ".gz").write_bytes(
        gzip.compress(path.read_bytes(), 9, mtime=0))
    path.unlink()


def mutated_netlist():
    lines = (ROOT / MUTATION["base_netlist"]).read_text().split("\n")
    assert lines[MUTATION["line"] - 1] == MUTATION["from"], "base netlist drifted"
    lines[MUTATION["line"] - 1] = MUTATION["to"]
    return "\n".join(lines)


def main():
    NC.mkdir(exist_ok=True)
    (NC / "mutation.json").write_text(json.dumps(MUTATION, indent=2) + "\n")
    status = {}

    p = uvx("python", "-c", BUILD_GDS)
    assert p.returncode == 0, p.stderr
    gds = (NC / "drc-sliver.gds").relative_to(ROOT)
    p = uvx("klt", "drc", gds, "--deck", "gf180mcu", "--pdk", PDK, "--format", "json")
    status["drc"] = p.returncode
    (NC / "drc.report.json").write_text(p.stdout)

    work = NC / ".work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    wc = BASE / "wavetable_core"
    (work / "wavetable_core.gds").write_bytes(
        gzip.decompress((wc / "wavetable_core.gds.gz").read_bytes()))
    (work / "wavetable_core.v").write_text(mutated_netlist())
    (NC / "lvs.request.json").write_text(json.dumps({
        "schema": "klt.lvs.request/1",
        "engine": "klayout",
        "layout": {"file": ".work/wavetable_core.gds", "deck": "gf180mcu",
                   "top": "wavetable_core",
                   "abstract_cells": [f"{CELL_LIBRARY}__*"]},
        "reference": {"netlist": ".work/wavetable_core.v",
                      "form": "gate-level-verilog", "library": CELL_LIBRARY,
                      "top": "wavetable_core"},
        "options": {"power_connectivity": {"expected_nets": LVS_POWER}},
        "portable_paths": True,
    }, indent=2) + "\n")
    p = uvx("klt", "lvs", (NC / "lvs.request.json").relative_to(ROOT),
            "--format", "json")
    status["lvs"] = p.returncode
    (NC / "lvs.report.json").write_text(p.stdout)
    shutil.rmtree(work, ignore_errors=True)

    (NC / "exit_status.json").write_text(json.dumps(status, indent=2) + "\n")
    pack(NC / "lvs.report.json")
    print(status, flush=True)


if __name__ == "__main__":
    main()
