#!/usr/bin/env python3
"""One bounded P&R trial for a group, kept out of the committed dirs (#804).

    python3 signoff/t1-physical/trial.py <group> <slug> --set key=value [...]

Builds the group's request exactly as regen.py writes it (regen.build_request),
applies the --set overlays (dotted path, one request setting per trial by
contract), and runs, inside signoff/t1-physical/trials/<group>/<slug>/:
place-and-route, DRC, LVS (reference = the trial's own as-built netlist),
the connectivity probe and the geometry probe. Nothing in the committed
group directories is read except the baseline request/netlist, and nothing
there is written.

Router diagnostics (klt's openroad-logs scratch) are archived as
openroad-logs.tar.gz before the scratch is removed. Every command, exit
code and wall time lands in run.json together with the baseline-relative
request diff and the outcome summary. Sequential, single run at a time;
place-and-route alone is ~40 minutes for ext_mem_instr.
"""
import gzip
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import open_pin_probe  # noqa: E402
import regen  # noqa: E402

BASE = ROOT / "signoff" / "t1-physical"
PIN = regen.PIN
PDK = regen.PDK


def klt(*args, cwd=ROOT):
    cmd = ["uvx", "--from", PIN, "klt", *map(str, args)]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, "PDK": PDK})


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


def set_path(obj, dotted, value):
    keys = dotted.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    last = keys[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def deep_diff(a, b, path=""):
    """(path, baseline_value, trial_value) for every leaf that differs,
    added or removed between the baseline request and the trial request.
    Lists diff element by element ([i] path segments, len changes as
    additions/removals) so a one-leaf overlay stays a one-leaf diff."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in a:
                out.append((p, None, b[k]))
            elif k not in b:
                out.append((p, a[k], None))
            else:
                out += deep_diff(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            p = f"{path}[{i}]"
            if i >= len(a):
                out.append((p, None, b[i]))
            elif i >= len(b):
                out.append((p, a[i], None))
            else:
                out += deep_diff(a[i], b[i], p)
    elif a != b:
        out.append((path or "<root>", a, b))
    return out


def main():
    args = sys.argv[1:]
    sets = []
    group = slug = None
    it = iter(args)
    for a in it:
        if a == "--set":
            sets.append(next(it))
        elif group is None:
            group = a
        elif slug is None:
            slug = a
    if group is None or slug is None or not sets:
        raise SystemExit(__doc__)
    if group not in regen.DIE_UM:
        raise SystemExit(f"unknown group {group}")
    if not os.environ.get("PDK_ROOT"):
        raise SystemExit("PDK_ROOT must be set (the probes resolve the "
                         "pinned liberty/LEF under it; it is never recorded)")

    tdir = BASE / "trials" / group / slug
    tdir.mkdir(parents=True, exist_ok=True)
    run = {"schema": "gf180-surge.pnr-trial/1", "group": group, "slug": slug,
           "sets": sets, "commands": [], "steps": {}}

    request = regen.build_request(group)
    # The trial request lives two levels deeper than the group request, so
    # the netlist path must be recomputed; recorded separately so the
    # request_diff stays exactly the one setting the trial changes.
    synth = ROOT / "signoff" / "t1-item1" / group / f"{group}_synth.v"
    request["netlist"] = os.path.relpath(synth, tdir)
    netlist_rewrite = {
        "group_request": regen.build_request(group)["netlist"],
        "trial_request": request["netlist"],
        "reason": "trial requests live at trials/<group>/<slug>/; the "
                  "referenced bytes are the same committed netlist",
    }
    for s in sets:
        key, _, raw = s.partition("=")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        set_path(request, key, value)
    write_json(tdir / "request.json", request)
    baseline = json.loads((BASE / group / "request.json").read_text())
    diff = [d for d in deep_diff(baseline, request)
            if d[0] != "netlist"]
    run["request_diff"] = [
        {"path": p, "baseline": a, "trial": b} for p, a, b in diff]
    run["netlist_path_rewrite"] = netlist_rewrite
    print(f"[trial] request diff: {run['request_diff']}", flush=True)

    def step(name, fn):
        t0 = time.monotonic()
        p = fn()
        dt = round(time.monotonic() - t0, 1)
        run["commands"].append({"step": name, "exit": p.returncode,
                                "seconds": dt})
        print(f"[trial] {name}: exit {p.returncode} in {dt}s", flush=True)
        return p

    req_rel = (tdir / "request.json").relative_to(ROOT)
    p = step("place-and-route",
             lambda: klt("place-and-route", req_rel, "--pdk", PDK,
                         "--format", "json"))
    (tdir / "pnr.report.json").write_text(p.stdout)
    run["steps"]["place-and-route"] = {"exit": p.returncode}
    if p.returncode != 0:
        (tdir / "pnr.failure.txt").write_text(
            regen.neutral_paths(p.stdout + "\n" + p.stderr))
        write_json(tdir / "run.json", run)
        print("[trial] place-and-route FAILED; downstream steps NOT_RUN",
              flush=True)
        return

    scratch = tdir / ".klt"
    out = scratch / "place-and-route"
    shutil.copy(out / f"{group}.gds", tdir / f"{group}.gds")
    shutil.copy(out / f"{group}.v", tdir / f"{group}.v")
    logs = tdir / ".klt" / "place-and-route" / "openroad-logs"
    if logs.is_dir():
        with tarfile.open(tdir / "openroad-logs.tar.gz", "w:gz") as tf:
            tf.add(logs, arcname="openroad-logs")
    shutil.rmtree(scratch, ignore_errors=True)

    gds = (tdir / f"{group}.gds").relative_to(ROOT)
    p = step("drc", lambda: klt("drc", gds, "--deck", "gf180mcu", "--pdk",
                                PDK, "--format", "json"))
    (tdir / "drc.report.json").write_text(p.stdout)
    drc = json.loads(p.stdout)
    run["steps"]["drc"] = {"exit": p.returncode,
                           "status": drc.get("status"),
                           "violations": drc.get("violation_count")}

    write_json(tdir / "lvs.request.json", {
        "schema": "klt.lvs.request/1",
        "engine": "klayout",
        "layout": {"file": f"{group}.gds", "deck": "gf180mcu", "top": group,
                   "abstract_cells": [f"{regen.CELL_LIBRARY}__*"]},
        "reference": {"netlist": f"{group}.v", "form": "gate-level-verilog",
                      "library": regen.CELL_LIBRARY, "top": group},
        "options": {"power_connectivity": {"expected_nets": regen.LVS_POWER}},
        "portable_paths": True,
    })
    p = step("lvs", lambda: klt("lvs",
                                (tdir / "lvs.request.json")
                                .relative_to(ROOT), "--format", "json"))
    (tdir / "lvs.report.json").write_text(p.stdout)
    lvs = json.loads(p.stdout)
    run["steps"]["lvs"] = {"exit": p.returncode, "status": lvs.get("status"),
                           "errors": lvs.get("error_count")}

    # pack the big artifacts exactly like regen.pack, then run the probes
    # against the packed stream so the trial records bind the same bytes.
    (tdir / f"{group}.gds.gz").write_bytes(gzip.compress(
        (tdir / f"{group}.gds").read_bytes(), 9, mtime=0))
    (tdir / "pnr.report.json.gz").write_bytes(gzip.compress(
        (tdir / "pnr.report.json").read_bytes(), 9, mtime=0))
    (tdir / "drc.report.json.gz").write_bytes(gzip.compress(
        (tdir / "drc.report.json").read_bytes(), 9, mtime=0))
    (tdir / "lvs.report.json.gz").write_bytes(gzip.compress(
        (tdir / "lvs.report.json").read_bytes(), 9, mtime=0))
    for f in ("pnr.report.json", "drc.report.json", "lvs.report.json"):
        (tdir / f).unlink()

    t0 = time.monotonic()
    try:
        open_pin_probe.probe(group, d=tdir, stream_gz=f"{group}.gds.gz")
        conn_rc = 0
    except SystemExit as e:
        print(f"[trial] connectivity probe failed: {e}", flush=True)
        conn_rc = 1
    run["commands"].append({"step": "open-pin-probe", "exit": conn_rc,
                            "seconds": round(time.monotonic() - t0, 1)})
    conn = json.loads((tdir / "open_pin_probe.json").read_text())
    inputs = [f for f in conn["findings"] if f["direction"] == "input"]
    run["steps"]["open-pin-probe"] = {
        "exit": conn_rc,
        "single_pin_nets": conn["summary"]["single_pin_nets"],
        "open_input_pins": [f["instance"] for f in inputs],
        "input_pins_examined": conn["pins_examined"].get("input", 0),
    }

    t0 = time.monotonic()
    gp = subprocess.run(
        [sys.executable, str(HERE / "pin_geometry_probe.py"), group,
         "--stream", str(tdir / f"{group}.gds"), "--out",
         str(tdir / "pin_geometry_probe.json"), "--conn",
         str(tdir / "open_pin_probe.json")],
        cwd=ROOT, capture_output=True, text=True, env=os.environ)
    run["commands"].append({"step": "pin-geometry-probe", "exit":
                            gp.returncode,
                            "seconds": round(time.monotonic() - t0, 1)})
    print(f"[trial] pin-geometry-probe: exit {gp.returncode}", flush=True)
    if gp.returncode != 0:
        print(gp.stdout[-2000:], gp.stderr[-2000:], flush=True)
    else:
        geo = json.loads((tdir / "pin_geometry_probe.json").read_text())
        run["steps"]["pin-geometry-probe"] = {
            "exit": gp.returncode,
            "isolated_input_masters":
                geo["summary"]["masters_with_isolated_inputs"],
        }

    run["erc"] = {"status": "NOT_RUN",
                  "reason": "erc is not_changed by a routing trial and "
                            "stays not_checked (missing antenna PDK) for "
                            "the committed groups; not part of this "
                            "trial's acceptance"}
    write_json(tdir / "run.json", run)
    ok = (run["steps"]["open-pin-probe"]["open_input_pins"] == []
          and run["steps"]["lvs"]["status"] == "match"
          and run["steps"]["drc"]["status"] == "clean")
    print(f"[trial] {group}/{slug}: "
          f"inputs={run['steps']['open-pin-probe']['open_input_pins']} "
          f"lvs={run['steps']['lvs']['status']} "
          f"drc={run['steps']['drc']['status']} "
          f"qualifying={ok}", flush=True)


if __name__ == "__main__":
    main()
