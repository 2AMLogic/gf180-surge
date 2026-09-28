#!/usr/bin/env python3
"""lp24 `--expect fail` hazard, measured pre- vs post-migration (#209).

A missing `rtl/init.hex` makes cfg[0] read as x -> n_blocks == 0 -> the
testbench writes an EMPTY but perfectly parseable trace and still exits 0.
Pre-migration the harness then reports verdict FAIL (missing T line), which
`--expect fail` accepts as the negative control PASSING -- a stimulus-load
failure masquerading as a caught mutant.
"""
import json, os, shutil, subprocess, sys

WT = "/home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-209"
D = "/tmp/sxt209-expect/lp24"
C = [100000, 200000, 300000, 400000, 500000, 600000, 700000, 800000]
DC = [1, 2, 3, 4, 5, 6, 7, 8]


def hexw(path, words):
    with open(path, "w") as f:
        for x in words:
            f.write("%08x\n" % (x & 0xffffffff))


shutil.rmtree("/tmp/sxt209-expect", ignore_errors=True)
os.makedirs(os.path.join(D, "rtl"))
hexw(os.path.join(D, "rtl", "init.hex"), [1])
hexw(os.path.join(D, "rtl", "ctrl.hex"), [3, 0] + C + DC)
hexw(os.path.join(D, "rtl", "in.hex"), [i * 1000 for i in range(64)])
TB = os.path.join(WT, "rtl", "voice", "tb_lp24.sv")
subprocess.run(["iverilog", "-g2012", "-o", os.path.join(D, "p.vvp"), TB],
               check=True)
subprocess.run(["vvp", "p.vvp"], cwd=D, check=True, capture_output=True)
y, t = {}, {}
for line in open(os.path.join(D, "tb_trace.txt")):
    p = line.split()
    if p and p[0] == "Y":
        y[(int(p[1]), int(p[2]))] = int(p[3])
    elif p and p[0] == "T":
        v = [int(x) for x in p[1:]]
        t[v[0]] = v[1:]
blk = {"b": 0, "subtype": t[0][0], "out_model": [y[(0, k)] for k in range(64)],
       "after": {"r": t[0][1:6], "C_end": t[0][6:14]}}
json.dump({"case": "synthetic", "leg": "synthetic", "trace_blocks": [blk]},
          open(os.path.join(D, "model_trace.json"), "w"))

# remove exactly one stimulus file: rtl/init.hex
os.rename(os.path.join(D, "rtl", "init.hex"), os.path.join(D, "init.away"))
rc = subprocess.run(["vvp", "p.vvp"], cwd=D, capture_output=True, text=True)
print("live sim with rtl/init.hex missing: vvp rc=%d" % rc.returncode)
for l in rc.stdout.splitlines():
    print("    " + l)
print("    trace lines written: %d"
      % len(open(os.path.join(D, "tb_trace.txt")).read().splitlines()))

for label, tools in (("PRE-migration (origin/main)",
                      "/tmp/sxt209-baseline/tools"),
                     ("POST-migration (this branch)",
                      os.path.join(WT, "tools"))):
    out = os.path.join(D, "verdict.json")
    if os.path.exists(out):
        os.remove(out)
    p = subprocess.run(
        [sys.executable, os.path.join(tools, "compare_rtl_model_lp24.py"),
         "--run-dir", D, "--tb", TB, "--out", out, "--expect", "fail"],
        capture_output=True, text=True)
    s = json.load(open(out)) if os.path.exists(out) else None
    print("%-30s rc=%d verdict=%s comparison=%s sim_fails=%s"
          % (label, p.returncode, s and s.get("verdict"),
             s and s.get("comparison"),
             (s or {}).get("sim_fails")))
    if p.returncode == 0:
        print("     ^^ rc=0 under --expect fail: the stimulus-load failure "
              "was ACCEPTED as a passing negative control")
