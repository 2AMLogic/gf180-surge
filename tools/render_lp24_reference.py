#!/usr/bin/env python3
"""SXT-038 reference renderer: run the PINNED LP 24 dB filter code per case.

The reference for this leaf is the manifest-pinned filter submodule
`libs/sst/sst-filters@e92d93a9` (the code the pinned engine executes for a
fut_lp24 unit), driven through the pinned per-block voice-path sequence by
the external harness `oracle/sxt038/lp24_ref_harness.cpp`
(decision-records/0010).  The harness binary is a GPL combined work built
into an external directory; only its numeric output is committed.

What this is, precisely (claim hygiene):
  * it IS the pinned coefficient maker + the pinned per-subtype kernel at
    the pinned commit, at the engine's (dsamplerate_os, BLOCK_SIZE_OS)
    configuration, with the engine's tuning-table semantics reproduced by
    construction (`provider surge-lut`);
  * it is NOT a full-engine preset render: the surrounding voice graph
    (oscillators, mixer, waveshaper, routing, the preset's own filter EG)
    is not executed here.  A full-engine leg needs the pinned surgepy build,
    which is not available in this environment (EVIDENCE §0, F-038-1).

Usage:
  python3 tools/render_lp24_reference.py --cases all --out-dir reports/SXT-038/artifacts
  python3 tools/render_lp24_reference.py --cases edges,brass --provider exact
"""

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lp24"))

import case_plan as cp  # noqa: E402

CASES_DIR = os.path.join(REPO, "reports", "SXT-038", "artifacts", "cases")
BUILD = os.path.join(REPO, "oracle", "sxt038", "build_lp24_ref.sh")


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_harness():
    try:
        out = subprocess.run([BUILD], check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise Refuse("oracle/sxt038/build_lp24_ref.sh not found")
    except subprocess.CalledProcessError as e:
        raise Refuse(f"harness build failed: {e.stderr.strip()[:500]}")
    binary = out.stdout.strip().splitlines()[-1]
    if not os.path.exists(binary):
        raise Refuse(f"harness build reported {binary}, which does not exist")
    prov = {}
    pfile = os.path.join(os.path.dirname(binary), "build-provenance.txt")
    if os.path.exists(pfile):
        for line in open(pfile, encoding="utf-8"):
            k, _, v = line.strip().partition(" ")
            prov[k] = v
    return binary, prov


def write_job(plan, stim, work, provider):
    ctl = os.path.join(work, "control.txt")
    with open(ctl, "w", encoding="utf-8") as f:
        f.write(f"provider {provider}\n")
        f.write("type 2\n")
        f.write("samplerate 96000\n")
        f.write(f"blocksize {cp.BLOCK_OS}\n")
        f.write(f"blocks {len(plan)}\n")
        for b in plan:
            f.write(f"B {b['sub']} {1 if b['reset'] else 0} "
                    f"{float(b['cut']).hex()} {float(b['res']).hex()}\n")
    inp = os.path.join(work, "input.i32")
    with open(inp, "wb") as f:
        f.write(struct.pack(f"<{len(stim)}i", *stim))
    return ctl, inp


def render_case(case_path, out_dir, binary, prov, provider):
    case = cp.load_case(case_path)
    plan = cp.build_plan(case)
    stim = cp.load_stimulus(case)
    if len(stim) != len(plan) * cp.BLOCK_OS:
        raise Refuse(f"{case['case']}: stimulus/plan length mismatch")

    suffix = "" if provider == "surge-lut" else f"-{provider}"
    bundle = os.path.join(out_dir, f"bundle-{case['case']}{suffix}")
    os.makedirs(bundle, exist_ok=True)
    work = os.path.join(out_dir, ".work")
    os.makedirs(work, exist_ok=True)

    ctl, inp = write_job(plan, stim, work, provider)
    run = subprocess.run([binary, ctl, inp, bundle], capture_output=True, text=True)
    if run.returncode != 0:
        raise Refuse(f"{case['case']}: harness exit {run.returncode}: "
                     f"{(run.stderr or run.stdout).strip()[:400]}")
    report = json.loads(run.stdout.strip().splitlines()[-1])

    peaks = {"out": 0.0, "in": 0.0}
    size = struct.calcsize("<IIIff")
    raw = open(os.path.join(bundle, "units.bin"), "rb").read()
    for i in range(len(raw) // size):
        _t, _l, _s, fin, fout = struct.unpack_from("<IIIff", raw, i * size)
        peaks["in"] = max(peaks["in"], abs(fin))
        peaks["out"] = max(peaks["out"], abs(fout))

    meta = {
        "schema_version": 1,
        "issue": "SXT-038",
        "case": case["case"],
        "carrier": case["carrier"],
        "filter": case["filter"],
        "overrides": case.get("overrides", {}),
        "sequence": case["sequence"],
        "stimulus": case["stimulus"],
        "reference": {
            "kind": "pinned-filter-submodule",
            "provider": provider,
            "engine_commit": case["carrier"]["engine_pin"],
            "sst_filters_commit": prov.get("sst_filters_commit"),
            "sst_basic_blocks_commit": prov.get("sst_basic_blocks_commit"),
            "harness_source_sha256": prov.get("harness_source_sha256"),
            "compiler": prov.get("compiler"),
            "sample_rate_os": 96000,
            "block_size_os": cp.BLOCK_OS,
            "note": "pinned filter code only; NOT a full-engine preset render",
        },
        "run": {
            "blocks": report["blocks"],
            "samples": report["samples"],
            "segments": 1 + max(b["seg"] for b in plan),
            "resets": sum(1 for b in plan if b["reset"]),
            "subtypes": sorted({b["sub"] for b in plan}),
            "cut_min": min(b["cut"] for b in plan),
            "cut_max": max(b["cut"] for b in plan),
            "peak_abs_in": peaks["in"],
            "peak_abs_out": peaks["out"],
        },
        "sha256": {
            "coeffs.jsonl": sha256_file(os.path.join(bundle, "coeffs.jsonl")),
            "units.bin": sha256_file(os.path.join(bundle, "units.bin")),
            "regs.bin": sha256_file(os.path.join(bundle, "regs.bin")),
        },
    }
    with open(os.path.join(bundle, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
        f.write("\n")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="all")
    ap.add_argument("--out-dir", default=os.path.join(REPO, "reports", "SXT-038", "artifacts"))
    ap.add_argument("--provider", default="surge-lut", choices=("surge-lut", "exact"))
    args = ap.parse_args()

    names = ([os.path.splitext(f)[0] for f in sorted(os.listdir(CASES_DIR))
              if f.endswith(".json")] if args.cases == "all"
             else args.cases.split(","))
    binary, prov = build_harness()
    os.makedirs(args.out_dir, exist_ok=True)
    out = []
    for name in names:
        path = os.path.join(CASES_DIR, f"{name}.json")
        if not os.path.exists(path):
            raise Refuse(f"no case file for {name}")
        meta = render_case(path, args.out_dir, binary, prov, args.provider)
        out.append({"case": name, "blocks": meta["run"]["blocks"],
                    "samples": meta["run"]["samples"],
                    "peak_out": meta["run"]["peak_abs_out"]})
        print(json.dumps(out[-1]))
    print(json.dumps({"rendered": len(out), "provider": args.provider,
                      "sst_filters_commit": prov.get("sst_filters_commit")}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
