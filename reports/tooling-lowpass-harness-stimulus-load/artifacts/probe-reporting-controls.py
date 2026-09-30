#!/usr/bin/env python3
"""Real-toolchain reporting controls for the lowpass-family harnesses (#209).

For each leaf: build a run dir with VALID (non-x) stimulus, run the real
testbench through real iverilog/vvp, synthesize a model_trace.json that
agrees with the trace it produced, then exercise:
  A  complete stimulus, agreeing model      -> comparison PASS / sim_fails []
  B  complete stimulus, mutated model       -> comparison FAIL / sim_fails []
  C  rtl/in.hex removed                     -> comparison NOT_RUN, file named
"""
import json, os, shutil, subprocess, sys

WT = "/home/ubuntu/GitHub/gf180-surge/.loom/worktrees/issue-209"
SCRATCH = "/tmp/sxt209-runs"
C = [100000, 200000, 300000, 400000, 500000, 600000, 700000, 800000]
DC = [1, 2, 3, 4, 5, 6, 7, 8]


def hexw(path, words):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for x in words:
            f.write("%08x\n" % (x & 0xffffffff))


def build_run_dir(leaf, subtype):
    d = os.path.join(SCRATCH, leaf)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "rtl"))
    hexw(os.path.join(d, "rtl", "init.hex"), [1])
    hexw(os.path.join(d, "rtl", "ctrl.hex"), [3, subtype] + C + DC)
    hexw(os.path.join(d, "rtl", "in.hex"), [i * 1000 for i in range(64)])
    return d


def run_tb(leaf, d):
    tb = os.path.join(WT, "rtl", "voice", "tb_%s.sv" % leaf)
    vvp = os.path.join(d, "tb_probe.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", vvp, tb], check=True)
    p = subprocess.run(["vvp", vvp], cwd=d, capture_output=True, text=True)
    return p.returncode, p.stdout


def read_trace(d):
    y, t = {}, {}
    with open(os.path.join(d, "tb_trace.txt")) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "Y":
                y[(int(parts[1]), int(parts[2]))] = int(parts[3])
            elif parts[0] == "T":
                vals = [int(v) for v in parts[1:]]
                t[vals[0]] = vals[1:]
    return y, t


def model_trace_for(leaf, y, t, mutate=False):
    out = [y[(0, k)] for k in range(64)]
    if mutate:
        out[7] += 1
    fields = t[0]
    if leaf == "lp12":                      # subtype, r0, r1, r_clip, c0..c7
        blk = {"b": 0, "subtype": fields[0], "in": [], "out_model": out,
               "after": {"r0": fields[1], "r1": fields[2],
                         "r_clip": fields[3], "C_end": fields[4:12]}}
        return {"leg": "synthetic-reporting-control",
                "instances": [{"trace_blocks": [blk]}]}
    # lp24 / lpmoog: subtype, r[0..4], C[0..7]
    blk = {"b": 0, "subtype": fields[0], "out_model": out,
           "after": {"r": fields[1:6], "C_end": fields[6:14]}}
    mt = {"case": "synthetic-reporting-control",
          "leg": "synthetic-reporting-control", "trace_blocks": [blk]}
    if leaf == "lpmoog":
        mt["meta"] = {"case": "synthetic-reporting-control"}
        mt["subtypes"] = [fields[0]]
    return mt


HARNESS = {"lp12": "compare_rtl_model_lp12.py",
           "lp24": "compare_rtl_model_lp24.py",
           "lpmoog": "compare_rtl_model_lpmoog.py"}


def harness(leaf, d, tools_dir, extra=()):
    out = os.path.join(d, "verdict.json")
    # Remove --out BEFORE invoking, so a run that dies without writing a
    # summary reads back as "no verdict" instead of silently inheriting the
    # previous run's file from this same run dir (issue #216; the sibling
    # probe-expect-fail-hazard.py already unlinks for the same reason).
    if os.path.exists(out):
        os.remove(out)
    cmd = [sys.executable, os.path.join(tools_dir, HARNESS[leaf]),
           "--run-dir", d, "--tb",
           os.path.join(WT, "rtl", "voice", "tb_%s.sv" % leaf),
           "--out", out] + list(extra)
    p = subprocess.run(cmd, capture_output=True, text=True)
    try:
        with open(out) as f:
            return p.returncode, json.load(f), p.stderr
    except OSError:
        return p.returncode, None, p.stderr


def main():
    tools_new = os.path.join(WT, "tools")
    tools_old = "/tmp/sxt209-baseline/tools"
    rc_all = 0
    for leaf, subtype in (("lp12", 1), ("lp24", 0), ("lpmoog", 0)):
        print("=" * 72)
        print("LEAF", leaf)
        d = build_run_dir(leaf, subtype)
        rc, stdout = run_tb(leaf, d)
        healthy_hit = [l for l in stdout.splitlines()
                       if "$readmem" in l and "Unable to open" in l]
        print("  healthy vvp rc=%d  matcher-hits=%d  (false-positive control)"
              % (rc, len(healthy_hit)))
        print("  healthy stdout:")
        for l in stdout.splitlines():
            print("      " + l)
        assert rc == 0 and not healthy_hit, "STOP/ESCALATE: %r" % healthy_hit
        y, t = read_trace(d)

        agree = model_trace_for(leaf, y, t)
        mutated = model_trace_for(leaf, y, t, mutate=True)

        def write_model(mt):
            with open(os.path.join(d, "model_trace.json"), "w") as f:
                json.dump(mt, f)

        # ---- known-good control: PRE-migration harness on this same run dir
        write_model(agree)
        old_rc, old_sum, old_err = harness(leaf, d, tools_old)
        print("  [pre-migration] rc=%s verdict=%s mismatches=%s checked=%s"
              % (old_rc, old_sum and old_sum.get("verdict"),
                 old_sum and old_sum.get("mismatches"),
                 old_sum and old_sum.get("checked")))

        # ---- A: complete stimulus, agreeing model
        rc_a, sum_a, _ = harness(leaf, d, tools_new)
        print("  [A complete+agree] rc=%d verdict=%s comparison=%s sim_fails=%s"
              % (rc_a, sum_a["verdict"], sum_a["comparison"], sum_a["sim_fails"]))
        assert rc_a == 0 and sum_a["verdict"] == "PASS"
        assert sum_a["comparison"] == "PASS" and sum_a["sim_fails"] == []
        assert sum_a["sim_stdout_tail"] == ""
        # identical to pre-migration on every pre-existing key
        for k in ("verdict", "checked", "mismatches", "first_failures"):
            assert old_sum[k] == sum_a[k], (k, old_sum[k], sum_a[k])
        print("      known-good control: pre/post summaries identical on "
              "verdict/checked/mismatches/first_failures")

        # ---- B: complete stimulus, genuine disagreement
        write_model(mutated)
        rc_b, sum_b, _ = harness(leaf, d, tools_new)
        print("  [B complete+mutated] rc=%d verdict=%s comparison=%s "
              "mismatches=%d sim_fails=%s first=%r"
              % (rc_b, sum_b["verdict"], sum_b["comparison"],
                 sum_b["mismatches"], sum_b["sim_fails"],
                 sum_b["first_failures"][:1]))
        assert rc_b != 0 and sum_b["verdict"] == "FAIL"
        assert sum_b["comparison"] == "FAIL" and sum_b["sim_fails"] == []
        assert sum_b["checked"]["samples"] > 0

        # ---- C: failure control -- remove exactly one stimulus file
        write_model(agree)
        removed = os.path.join(d, "rtl", "in.hex")
        os.rename(removed, removed + ".away")
        rc_c, sum_c, _ = harness(leaf, d, tools_new)
        print("  [C missing rtl/in.hex] rc=%d verdict=%s comparison=%s "
              "checked=%s" % (rc_c, sum_c["verdict"], sum_c["comparison"],
                              sum_c["checked"]))
        print("      sim_fails[0]: %s" % sum_c["sim_fails"][0])
        assert rc_c != 0 and sum_c["verdict"] == "FAIL"
        assert sum_c["comparison"] == "NOT_RUN"
        assert len(sum_c["sim_fails"]) == 1
        assert "rtl/in.hex" in sum_c["sim_fails"][0]
        assert sum_c["checked"] == {"samples": 0, "checkpoints": 0,
                                    "fields": 0}
        assert not any("sample" in s for s in sum_c["first_failures"]), \
            sum_c["first_failures"]

        # ---- C': the SAME missing file, run through the real simulator
        #      (rc=0 + ERROR on stdout) -- the #188 mechanism, live.
        rc2, stdout2 = run_tb(leaf, d)
        hits = [l for l in stdout2.splitlines()
                if "$readmem" in l and "Unable to open" in l]
        print("      live simulator with the file removed: vvp rc=%d, "
              "matcher-hits=%d" % (rc2, len(hits)))
        for h in hits:
            print("        " + h)
        assert rc2 == 0 and len(hits) == 1
        os.rename(removed + ".away", removed)

        # ---- lp24 only: --expect fail must NOT be satisfied by a sim failure
        if leaf == "lp24":
            os.rename(removed, removed + ".away")
            rc_d, sum_d, _ = harness(leaf, d, tools_new,
                                     extra=("--expect", "fail"))
            print("  [D lp24 --expect fail + missing stimulus] rc=%d "
                  "verdict=%s comparison=%s" % (rc_d, sum_d["verdict"],
                                                sum_d["comparison"]))
            assert rc_d != 0, "a sim failure must never satisfy --expect fail"
            old_rc_d, old_sum_d, old_err_d = harness(leaf, d, tools_old,
                                                     extra=("--expect", "fail"))
            # With rtl/init.hex still PRESENT, n_blocks reads as 1 and the
            # testbench writes Y lines valued x, which the pre-migration
            # harness dies parsing -- it produces NO verdict at all here, so
            # this case does NOT demonstrate the --expect fail hazard (PART 2
            # does, with rtl/init.hex removed).  See issue #216.
            if old_sum_d is None:
                verdict_d = "NO_VERDICT (%s)" % (
                    old_err_d.strip().splitlines() or ["no stderr"])[-1]
            else:
                verdict_d = old_sum_d.get("verdict")
            print("      pre-migration, same case: rc=%s verdict=%s"
                  % (old_rc_d, verdict_d))
            os.rename(removed + ".away", removed)
    print("=" * 72)
    print("ALL REAL-TOOLCHAIN REPORTING CONTROLS OK")
    return rc_all


if __name__ == "__main__":
    sys.exit(main())
