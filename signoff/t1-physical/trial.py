#!/usr/bin/env python3
"""One bounded P&R trial for a group, kept out of the committed dirs (#804).

    python3 signoff/t1-physical/trial.py <group> <slug> --set key=value [...]

--resume-pnr adopts a place-and-route whose driver was started by an
earlier step and completed after that step exited (refuses unless the
request on disk is byte-identical to the --set rebuild and all driver
outputs are present; no pnr report is written in that mode).

Builds the group's request exactly as regen.py writes it (regen.build_request),
applies the --set overlays (dotted path, one request setting per trial by
contract), and runs, inside signoff/t1-physical/trials/<group>/<slug>/:
place-and-route, DRC, LVS (reference = the trial's own as-built netlist),
the connectivity probe and the geometry probe. Nothing in the committed
group directories is read except the baseline request/netlist, and nothing
there is written.

Router diagnostics are retained under openroad-logs/<invocation-id>/
before klt scratch is removed. Every command, exit
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
    resume_pnr = False
    rerun_geometry = False
    it = iter(args)
    for a in it:
        if a == "--set":
            sets.append(next(it))
        elif a == "--resume-pnr":
            resume_pnr = True
        elif a == "--rerun-geometry":
            rerun_geometry = True
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
    scratch = tdir / ".klt"
    out = scratch / "place-and-route"
    adopted = None
    if rerun_geometry:
        # Repair path for the first m4-strap-offset-0p0 run: the
        # connectivity probe's scratch cleanup deleted the trial's
        # unpacked <group>.gds before the geometry probe opened it
        # (same filename, fixed in the same change: the geometry probe
        # now reads the packed .gds.gz). Re-executes only the geometry
        # step against the same stream and rewrites its run.json entry;
        # the failed attempt stays in commands.
        run_path = tdir / "run.json"
        if not run_path.is_file():
            raise SystemExit("--rerun-geometry: no run.json to repair")
        run = json.loads(run_path.read_text())
        for need in (f"{group}.gds.gz", "open_pin_probe.json"):
            if not (tdir / need).is_file():
                raise SystemExit(
                    f"--rerun-geometry: {need} missing; nothing to re-run "
                    "against")
        t0 = time.monotonic()
        gp = subprocess.run(
            [sys.executable, str(HERE / "pin_geometry_probe.py"), group,
             "--stream", str(tdir / f"{group}.gds.gz"), "--out",
             str(tdir / "pin_geometry_probe.json"), "--conn",
             str(tdir / "open_pin_probe.json")],
            cwd=ROOT, capture_output=True, text=True, env=os.environ)
        dt = round(time.monotonic() - t0, 1)
        print(f"[trial] pin-geometry-probe (rerun): exit {gp.returncode} "
              f"in {dt}s", flush=True)
        if gp.returncode != 0:
            print(gp.stdout[-2000:], gp.stderr[-2000:], flush=True)
            raise SystemExit("--rerun-geometry: probe still failing")
        run["commands"].append({
            "step": "pin-geometry-probe", "exit": gp.returncode,
            "seconds": dt,
            "note": "re-execution after the trial's original geometry step "
                    "failed on FileNotFoundError: open_pin_probe's scratch "
                    "cleanup had deleted the unpacked trial .gds (same "
                    "name); fixed by reading the packed .gds.gz, and this "
                    "rerun path, in the same change",
        })
        geo = json.loads((tdir / "pin_geometry_probe.json").read_text())
        run["steps"]["pin-geometry-probe"] = {
            "exit": gp.returncode,
            "isolated_input_masters":
                geo["summary"]["masters_with_isolated_inputs"],
            "first_attempt": "exit 1 (FileNotFoundError; see commands)",
        }
        write_json(run_path, run)
        print(f"[trial] pin-geometry-probe summary: "
              f"{run['steps']['pin-geometry-probe']}", flush=True)
        return
    if resume_pnr:
        # Adopt a place-and-route driven by an earlier builder step whose
        # driver survived that step's exit (the trial.py parent did not).
        # Legitimate only when the request on disk is byte-identical to the
        # one this invocation rebuilds from --set, and the driver's own
        # outputs are all present; the driver's JSON stdout went to the dead
        # parent's pipe, so no pnr.report.json is written for this trial and
        # nothing downstream is inferred from it.
        on_disk = (tdir / "request.json").read_text()
        rebuilt = json.dumps(request, indent=2) + "\n"
        if on_disk != rebuilt:
            raise SystemExit(
                "--resume-pnr: request.json on disk differs from the "
                "--set rebuild; refusing to adopt artifacts of a "
                "different trial")
        have = {n: (out / n).exists() for n in
                (f"{group}.gds", f"{group}.v", f"{group}_route_metrics.json")}
        if not all(have.values()):
            raise SystemExit(
                f"--resume-pnr: driver outputs incomplete {have}; the "
                "place-and-route did not finish")
        adopted = {
            "driver": "uvx --from klayout-tools==0.8.0 klt place-and-route "
                      f"{req_rel} --pdk {PDK} --format json",
            "driver_note": "started 2026-11-21T02:23:13Z by the predecessor "
                           "builder step (klt pid observed alive at adoption "
                           "time); the trial.py parent of that step exited, "
                           "orphaning the driver mid-route",
            "adoption_checks": {k: ("present" if v else "absent")
                                for k, v in have.items()},
            "pnr_report": "absent: the driver's stdout was captured by the "
                          "dead parent's pipe; route metrics, DEF, stage "
                          "ODBs and openroad logs are the driver's own "
                          "files, archived below",
        }
        run["steps"]["place-and-route"] = {
            "exit": None, "status": "adopted_completed_driver",
            "adoption": adopted,
        }
        run["commands"].append({
            "step": "place-and-route", "exit": None,
            "note": "not executed by this step: adopted completed driver "
                    "(see steps.place-and-route.adoption)",
        })
        print("[trial] resuming after adopted place-and-route", flush=True)
    else:
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
    shutil.copy(out / f"{group}.gds", tdir / f"{group}.gds")
    shutil.copy(out / f"{group}.v", tdir / f"{group}.v")
    # The generated stage scripts are the proof a request leaf reached the
    # flow (the placebo trial's density leaf never did); keep them out of
    # the scratch that is deleted below. m4-strap-offset-0p0's own scripts
    # were archived by hand mid-run the same way before this line existed.
    scripts = sorted(out.glob("pnr_*.tcl"))
    if scripts:
        (tdir / "pnr-scripts").mkdir(exist_ok=True)
        for s in scripts:
            shutil.copy(s, tdir / "pnr-scripts" / s.name)
    logs = out / "openroad-logs"
    if logs.is_dir():
        retained_logs = tdir / "openroad-logs"
        if retained_logs.exists():
            shutil.rmtree(retained_logs)
        logs.rename(retained_logs)
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
    pack_reports = [n for n in ("pnr.report.json", "drc.report.json",
                                "lvs.report.json")
                    if (tdir / n).exists()]
    for n in pack_reports:
        (tdir / (n + ".gz")).write_bytes(gzip.compress(
            (tdir / n).read_bytes(), 9, mtime=0))
    for n in pack_reports:
        (tdir / n).unlink()

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
         "--stream", str(tdir / f"{group}.gds.gz"), "--out",
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
