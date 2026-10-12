#!/usr/bin/env python3
"""Issue #456 one-shot negative controls for the decay-sweep coverage gate.
Original to this repository (Apache-2.0).

Each control must DEMONSTRABLY fail the behaviour the gate exists to close;
a control that does not fire is itself a finding and is reported as such.
Writes NEGATIVE-CONTROLS.txt next to itself. Never touches
reports/sxt-024/comparison/.

  NC-456-A  empty trace directory            -> REFUSED, exit 2, no evidence
  NC-456-B  one required case missing        -> REFUSED, exit 2, evidence
                                               file untouched
  NC-456-C  fully ungraded sweep (wet := dry, every check None), full
            declared set: the NEW tool must exit nonzero (NO_VERDICT) while
            the pre-#456 tool's aggregate -- all(...) over only non-None
            values -- is vacuously True on the same results (exit 0), i.e.
            the control fires on exactly the masquerade the gate closes.
  NC-456-D  graded false check (reverb +6 dB vs the prediction) -> FAIL,
            exit 1. Runs on the two-case subset with the declared required
            set scoped to it (disclosed: REQUIRED_SWEEP_CASES patched in the
            driver process); the full-set pin lives in the pytest suite.

Usage: python3 reports/sxt-024/artifacts/issue-456/negative_controls.py <repo_root>
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

REPO = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                       os.path.dirname(os.path.dirname(os.path.dirname(
                           os.path.dirname(os.path.abspath(__file__))))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))
import compare_reverb_model as crm  # noqa: E402

SYNTH_FRAMES = 48000
SUBSET = ("sweepmdecaym0", "sweepmdecaymm2")
SUBSET_DECAY = {"sweepmdecaym0": 0.0, "sweepmdecaymm2": -2.0}
LINES = []


def log(line=""):
    LINES.append(line)
    print(line)


def run_cli(traces_dir, out_dir):
    """Run the current tool's sweep command through main()'s argv path."""
    argv = sys.argv
    sys.argv = ["compare_reverb_model.py", "sweep",
                "--traces-dir", traces_dir, "--out-dir", out_dir]
    try:
        return crm.main()
    finally:
        sys.argv = argv


def write_wav(path, wet):
    d = np.clip(np.round(np.asarray(wet) * 32768.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(d.T.tobytes())


def synth_sidecar(dst_dir, name, decay_v, wav_path, frames):
    src = json.load(open(os.path.join(crm.TRACES, "sweepmdecaym0.json")))
    side = copy.deepcopy(src)
    side["trace"] = name
    side["sweep"] = {"param": "fx4_p3 decaytime", "requested": decay_v}
    side["render"]["overrides_applied"] = {"3": decay_v}
    side["render"]["frames"] = frames
    side["render"]["blocks"] = frames
    with open(wav_path, "rb") as f:
        side["wav"] = {"bytes": os.fstat(f.fileno()).st_size, "channels": 2,
                       "frames": frames, "sample_rate": 48000,
                       "sha256": hashlib.sha256(f.read()).hexdigest()}
    side["engine_patch_state"]["params"]["decaytime"] = decay_v
    side["synthetic_negative_control"] = (
        "issue #456 negative-control construction; not an oracle render")
    with open(os.path.join(dst_dir, name + ".json"), "w") as f:
        json.dump(side, f, indent=2, sort_keys=True)
        f.write("\n")


def load_old_module():
    blob = subprocess.run(
        ["git", "-C", REPO, "show", "HEAD:tools/compare_reverb_model.py"],
        check=True, capture_output=True).stdout
    path = os.path.join(tempfile.mkdtemp(prefix="issue456-nc-old-"),
                        "compare_reverb_model_old.py")
    with open(path, "wb") as f:
        f.write(blob)
    spec = importlib.util.spec_from_file_location("crm_old_nc456", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.REPO = tempfile.mkdtemp(prefix="issue456-nc-oldout-")
    mod.TRACES = crm.TRACES
    os.makedirs(os.path.join(mod.REPO, "reports", "sxt-024", "comparison"))
    return mod


def control_a(root):
    log("NC-456-A  empty trace directory")
    traces = os.path.join(root, "nc-a", "traces")
    out = os.path.join(root, "nc-a", "out")
    os.makedirs(traces)
    rc = run_cli(traces, out)
    left = sorted(os.listdir(out)) if os.path.isdir(out) else []
    fired = rc == 2 and not left
    log("  command : sweep --traces-dir <empty> --out-dir <out>")
    log("  exit: %d   files written: %s" % (rc, left or "none"))
    log("  FIRES (refused, no evidence written): %s" % fired)
    log()
    return fired


def control_b(root):
    log("NC-456-B  one required case missing (committed set minus "
        "sweepmdecaym3)")
    base = os.path.join(root, "nc-b")
    traces, out = os.path.join(base, "traces"), os.path.join(base, "out")
    os.makedirs(traces)
    os.makedirs(out)
    for name in crm.REQUIRED_SWEEP_CASES:
        if name == "sweepmdecaym3":
            continue
        for suffix in (".json", ".wav"):
            shutil.copy(os.path.join(crm.TRACES, name + suffix),
                        os.path.join(traces, name + suffix))
    sentinel = os.path.join(out, "sweep-t60.json")
    with open(sentinel, "w") as f:
        f.write("committed evidence sentinel\n")
    rc = run_cli(traces, out)
    intact = open(sentinel).read() == "committed evidence sentinel\n"
    no_cov = not os.path.exists(os.path.join(out, "sweep-t60-coverage.json"))
    fired = rc == 2 and intact and no_cov
    log("  command : sweep --traces-dir <6 of 7> --out-dir <out with sentinel>")
    log("  exit: %d   sentinel intact: %s   coverage file written: %s"
        % (rc, intact, not no_cov))
    log("  FIRES (refused before overwriting evidence): %s" % fired)
    log()
    return fired


def control_c(root):
    log("NC-456-C  fully ungraded sweep (wet := dry; every check None), "
        "full declared set")
    base = os.path.join(root, "nc-c")
    traces, out = os.path.join(base, "traces"), os.path.join(base, "out")
    os.makedirs(traces)
    os.makedirs(out)
    dry = np.load(os.path.join(crm.TRACES, "click-dry.npy"))
    n = len(dry[0])
    # both tools drive the model with the fixture's own click-dry bus
    shutil.copy(os.path.join(crm.TRACES, "click-dry.npy"),
                os.path.join(traces, "click-dry.npy"))
    for name in crm.REQUIRED_SWEEP_CASES:
        side = json.load(open(os.path.join(crm.TRACES, name + ".json")))
        wet0 = np.array([dry[0], dry[1]])  # wet := dry: reverb component 0
        wav = os.path.join(traces, name + ".wav")
        write_wav(wav, wet0)
        keep = copy.deepcopy(side)
        keep["render"]["frames"] = n
        keep["render"]["blocks"] = n
        with open(wav, "rb") as f:
            keep["wav"] = {"bytes": os.fstat(f.fileno()).st_size,
                           "channels": 2, "frames": n, "sample_rate": 48000,
                           "sha256": hashlib.sha256(f.read()).hexdigest()}
        keep["synthetic_negative_control"] = (
            "issue #456 NC-456-C: wet bus replaced by the dry bus (reverb "
            "component exactly zero); not an oracle render")
        with open(os.path.join(traces, name + ".json"), "w") as f:
            json.dump(keep, f, indent=2, sort_keys=True)
            f.write("\n")
    rc_new = run_cli(traces, out)
    cov = json.load(open(os.path.join(out, "sweep-t60-coverage.json")))
    results = json.load(open(os.path.join(out, "sweep-t60.json")))
    old = load_old_module()
    # the pre-#456 tool reads its fixed TRACES global: point it at the SAME
    # ungraded fixture so the comparison is apples-to-apples
    old.TRACES = traces
    rc_old = old.cmd_sweep(None)
    old_results = json.load(open(os.path.join(
        old.REPO, "reports", "sxt-024", "comparison", "sweep-t60.json")))
    old_all = all(v for r in old_results for v in r["checks"].values()
                  if v is not None)
    log("  fixture : all %d committed sweep traces with wet := dry (the "
        "reverb-only component is exactly zero, so no agreement check is "
        "measurable anywhere)" % len(crm.REQUIRED_SWEEP_CASES))
    log("  new tool: exit %d  verdict %r  coverage %r  cases_not_run %d"
        % (rc_new, cov["verdict"], cov["coverage"], cov["cases_not_run"]))
    log("  old tool: exit %d  aggregate all(...) over non-None values: %r"
        % (rc_old, old_all))
    fired = (rc_new == 1 and cov["verdict"] == "NO_VERDICT"
             and cov["coverage"] == "none"
             and all(all(v is None for v in r["checks"].values())
                     for r in results)
             and rc_old == 0 and old_all is True)
    log("  FIRES (old tool returned success on exactly this result set; "
        "the gate does not): %s" % fired)
    log()
    return fired


def control_d(root):
    log("NC-456-D  graded false check (reverb component +6 dB vs the "
        "prediction) -> FAIL")
    base = os.path.join(root, "nc-d")
    traces, out = os.path.join(base, "traces"), os.path.join(base, "out")
    os.makedirs(traces)
    os.makedirs(out)
    dry = np.load(os.path.join(crm.TRACES, "click-dry.npy")).astype(
        np.float64)[:, :SYNTH_FRAMES]
    for name, decay_v in SUBSET_DECAY.items():
        side = copy.deepcopy(
            json.load(open(os.path.join(crm.TRACES, name + ".json"))))
        side["engine_patch_state"]["params"]["decaytime"] = decay_v
        model, _c, st = crm.build_model(side)
        send, ret = crm.send_return_gains(st)
        (pl, pr), _ = crm.run_model_on_dry(model, dry[0], dry[1], send, ret)
        wet = (2.0 * pl - dry[0], 2.0 * pr - dry[1])
        wav = os.path.join(traces, name + ".wav")
        write_wav(wav, wet)
        synth_sidecar(traces, name, decay_v, wav, SYNTH_FRAMES)
    required_backup = crm.REQUIRED_SWEEP_CASES
    crm.REQUIRED_SWEEP_CASES = SUBSET  # disclosed subset scope for this control
    try:
        rc = run_cli(traces, out)
    finally:
        crm.REQUIRED_SWEEP_CASES = required_backup
    cov = json.load(open(os.path.join(out, "sweep-t60-coverage.json")))
    results = json.load(open(os.path.join(out, "sweep-t60.json")))
    log("  fixture : two-case subset (%s); wet := dry + 2 x (model reverb), "
        "i.e. the reverb-only component is +6 dB against the prediction"
        % ", ".join(SUBSET))
    log("  scope   : REQUIRED_SWEEP_CASES scoped to the subset in this "
        "driver process (full-set pin: tests/test_sxt024_sweep_coverage.py)")
    log("  exit: %d  verdict %r  checks_graded_false %d  per-case %s"
        % (rc, cov["verdict"], cov["checks_graded_false"],
           {r["trace"]: r["status"] for r in results}))
    fired = rc == 1 and cov["verdict"] == "FAIL" \
        and cov["checks_graded_false"] >= 1
    log("  FIRES (a graded false check is a FAIL, never a pass): %s" % fired)
    log()
    return fired


def main():
    root = tempfile.mkdtemp(prefix="issue456-nc-")
    log("issue #456 -- negative controls for the decay-sweep coverage gate")
    log("")
    log("environment: %s / numpy %s" % (sys.version.split()[0],
                                        np.__version__))
    log("tool under control: worktree tools/compare_reverb_model.py; the "
        "pre-#456 tool is loaded from git HEAD:tools/compare_reverb_model.py")
    log("all fixtures are synthetic temp constructions; no committed report "
        "or trace is modified")
    log("")
    ok = all([control_a(root), control_b(root), control_c(root),
              control_d(root)])
    log("CONTROL SUITE: %s (exit %d)" % ("all controls FIRED" if ok
                                         else "A CONTROL DID NOT FIRE",
                                         0 if ok else 1))
    with open(os.path.join(HERE, "NEGATIVE-CONTROLS.txt"), "w") as f:
        f.write("\n".join(LINES) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
