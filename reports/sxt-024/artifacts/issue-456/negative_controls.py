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
  NC-456-E  graded EXTRA case beside a wholly ungraded required set (the
            NC-456-C fixture plus one extra identity whose wet is the
            model's own prediction): the extra is graded True, yet the
            verdict stays NO_VERDICT, exit 1 -- an extra never enables PASS.
  NC-456-F  supplied dry bus: (i) the NC-456-D subset with its click-dry
            removed -> REFUSED, exit 2, nothing written; (ii) the same
            subset with a -6 dB click-dry -> per-case tracking values differ
            from the true-dry run, i.e. the selected directory's dry bus is
            the one used (the committed one is never borrowed).
  NC-456-G  renamed duplicate identities (issue #458 review): the committed
            m0 sidecar and wav copied under every required filename -> the
            tool must refuse (exit 2) before overwriting prior evidence,
            while the pre-#456 tool accepts exactly this masquerade (exit 0)
            -- one decay case renamed seven times must never count as the
            declared grid.
  NC-456-H  relabelled identity with the applied/engine decay left behind
            (issue #458 review): every required name gets a sidecar whose
            declared trace and requested grid value are consistent with the
            filename but whose applied decay override and normalized engine
            readback are still m0's -> refuse (exit 2), prior evidence
            untouched; labels alone cannot vouch for an identity.

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


# The pre-#456 tool is pinned to a FIXED commit, never HEAD: on the committed
# branch HEAD is the gated tool, so HEAD would compare the new code with
# itself. e4c25bf is the last origin/main commit touching
# tools/compare_reverb_model.py before #456 (the merge base's blob).
OLD_TOOL_COMMIT = "e4c25bfc5aec129c0113ce74236aa00cf32aa521"
OLD_TOOL_BLOB_SHA256 = None  # filled from the blob and logged for audit


def load_old_module():
    global OLD_TOOL_BLOB_SHA256
    blob = subprocess.run(
        ["git", "-C", REPO, "show",
         OLD_TOOL_COMMIT + ":tools/compare_reverb_model.py"],
        check=True, capture_output=True).stdout
    OLD_TOOL_BLOB_SHA256 = hashlib.sha256(blob).hexdigest()
    if b"REQUIRED_SWEEP_CASES" in blob:
        raise SystemExit("NC-456-C: pinned old tool already carries the #456 "
                         "gate; the control would compare new with new")
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
    log("  old tool: %s blob sha256 %s"
        % (OLD_TOOL_COMMIT[:12], OLD_TOOL_BLOB_SHA256))
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


def build_subset(traces, gain):
    """Two-case subset: wet := dry + gain x (model reverb), with the subset's
    own click-dry.npy written into the selected directory."""
    dry = np.load(os.path.join(crm.TRACES, "click-dry.npy")).astype(
        np.float64)[:, :SYNTH_FRAMES]
    np.save(os.path.join(traces, "click-dry.npy"), dry.astype(np.float32))
    for name, decay_v in SUBSET_DECAY.items():
        side = copy.deepcopy(
            json.load(open(os.path.join(crm.TRACES, name + ".json"))))
        side["engine_patch_state"]["params"]["decaytime"] = decay_v
        model, _c, st = crm.build_model(side)
        send, ret = crm.send_return_gains(st)
        (pl, pr), _ = crm.run_model_on_dry(model, dry[0], dry[1], send, ret)
        wet = (dry[0] + gain * (pl - dry[0]), dry[1] + gain * (pr - dry[1]))
        wav = os.path.join(traces, name + ".wav")
        write_wav(wav, wet)
        synth_sidecar(traces, name, decay_v, wav, SYNTH_FRAMES)
    return dry


def run_subset(traces, out):
    required_backup = crm.REQUIRED_SWEEP_CASES
    crm.REQUIRED_SWEEP_CASES = SUBSET  # disclosed subset scope for this control
    try:
        return run_cli(traces, out)
    finally:
        crm.REQUIRED_SWEEP_CASES = required_backup


def control_d(root):
    log("NC-456-D  graded false check (reverb component +6 dB vs the "
        "prediction) -> FAIL")
    base = os.path.join(root, "nc-d")
    traces, out = os.path.join(base, "traces"), os.path.join(base, "out")
    os.makedirs(traces)
    os.makedirs(out)
    build_subset(traces, gain=2.0)
    rc = run_subset(traces, out)
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


def control_e(root):
    log("NC-456-E  graded EXTRA case beside a wholly ungraded required set")
    base = os.path.join(root, "nc-e")
    traces, out = os.path.join(base, "traces"), os.path.join(base, "out")
    shutil.copytree(os.path.join(root, "nc-c", "traces"), traces)
    os.makedirs(out)
    # one extra identity whose wet is the model's own prediction -> gradable
    ptraces = os.path.join(base, "pred")
    os.makedirs(ptraces)
    build_subset(ptraces, gain=1.0)
    extra = "sweepmdecaym9"
    shutil.copy(os.path.join(ptraces, "sweepmdecaym0.wav"),
                os.path.join(traces, extra + ".wav"))
    side = json.load(open(os.path.join(ptraces, "sweepmdecaym0.json")))
    side["trace"] = extra
    with open(os.path.join(traces, extra + ".json"), "w") as f:
        json.dump(side, f, indent=2, sort_keys=True)
        f.write("\n")
    rc = run_cli(traces, out)
    cov = json.load(open(os.path.join(out, "sweep-t60-coverage.json")))
    status = {c["trace"]: c["status"] for c in cov["cases"]}
    log("  fixture : NC-456-C traces (all %d required cases ungraded) + extra "
        "%s (wet := model prediction)" % (len(crm.REQUIRED_SWEEP_CASES),
                                         extra))
    log("  exit: %d  verdict %r  coverage %r  extra status %r  "
        "required_checks_graded %d  checks_graded_true %d"
        % (rc, cov["verdict"], cov["coverage"], status.get(extra),
           cov["required_checks_graded"], cov["checks_graded_true"]))
    fired = (rc == 1 and cov["verdict"] == "NO_VERDICT"
             and status.get(extra) == "PASS"
             and cov["required_checks_graded"] == 0
             and cov["checks_graded_true"] >= 1)
    log("  FIRES (a graded extra cannot supply the agreement a PASS needs): "
        "%s" % fired)
    log()
    return fired


def control_f(root):
    log("NC-456-F  dry input comes from the SELECTED trace directory")
    base = os.path.join(root, "nc-f")
    true_t, true_o = os.path.join(base, "true"), os.path.join(base, "true-out")
    gone_t, gone_o = os.path.join(base, "gone"), os.path.join(base, "gone-out")
    half_t, half_o = os.path.join(base, "half"), os.path.join(base, "half-out")
    for d in (true_t, true_o, gone_o, half_o):
        os.makedirs(d)
    dry = build_subset(true_t, gain=1.0)
    shutil.copytree(true_t, gone_t)
    os.remove(os.path.join(gone_t, "click-dry.npy"))
    shutil.copytree(true_t, half_t)
    np.save(os.path.join(half_t, "click-dry.npy"),
            (0.5 * dry).astype(np.float32))
    rc_true = run_subset(true_t, true_o)
    rc_gone = run_subset(gone_t, gone_o)
    gone_left = sorted(os.listdir(gone_o))
    rc_half = run_subset(half_t, half_o)

    def track(out):
        return {r["trace"]: r["tail_level_tracking_mean_dev_db"]
                for r in json.load(open(os.path.join(out, "sweep-t60.json")))}
    t_true, t_half = track(true_o), track(half_o)
    log("  (i)  click-dry removed from the subset: exit %d  files written: %s"
        % (rc_gone, gone_left or "none"))
    log("  (ii) true dry: exit %d  tracking mean dev %s"
        % (rc_true, {k: round(v, 4) for k, v in t_true.items()}))
    log("       -6 dB dry: exit %d  tracking mean dev %s"
        % (rc_half, {k: (None if v is None else round(v, 4))
                     for k, v in t_half.items()}))
    fired = (rc_gone == 2 and not gone_left and rc_true == 0
             and all(t_half[k] != t_true[k] for k in SUBSET))
    log("  FIRES (missing dry refused; a different supplied dry changes the "
        "graded result): %s" % fired)
    log()
    return fired


def control_g(root):
    log("NC-456-G  renamed duplicate identities: the m0 case under every "
        "required filename")
    base = os.path.join(root, "nc-g")
    traces, out = os.path.join(base, "traces"), os.path.join(base, "out")
    os.makedirs(traces)
    os.makedirs(out)
    shutil.copy(os.path.join(crm.TRACES, "click-dry.npy"),
                os.path.join(traces, "click-dry.npy"))
    for name in crm.REQUIRED_SWEEP_CASES:
        for suffix in (".json", ".wav"):
            shutil.copy(os.path.join(crm.TRACES, "sweepmdecaym0" + suffix),
                        os.path.join(traces, name + suffix))
    sentinel = os.path.join(out, "sweep-t60.json")
    with open(sentinel, "w") as f:
        f.write("committed evidence sentinel\n")
    rc_new = run_cli(traces, out)
    intact = open(sentinel).read() == "committed evidence sentinel\n"
    no_cov = not os.path.exists(os.path.join(out, "sweep-t60-coverage.json"))
    # the masquerade the identity check closes: the pre-#456 tool counts
    # filenames, so one decay case renamed seven times grades as the whole
    # declared grid and exits 0 (the issue #458 review's live demonstration)
    old = load_old_module()
    old.TRACES = traces
    rc_old = old.cmd_sweep(None)
    log("  fixture : the committed m0 sidecar+wav copied under all %d "
        "required filenames (+ the committed click-dry)"
        % len(crm.REQUIRED_SWEEP_CASES))
    log("  new tool: exit %d  prior evidence intact: %s  coverage file "
        "written: %s" % (rc_new, intact, not no_cov))
    log("  old tool: exit %d (renamed duplicates accepted as full coverage)"
        % rc_old)
    fired = rc_new == 2 and intact and no_cov and rc_old == 0
    log("  FIRES (duplicate identities refuse before overwriting evidence; "
        "the old tool passed exactly this fixture): %s" % fired)
    log()
    return fired


def control_h(root):
    log("NC-456-H  relabelled trace/requested with the applied/engine decay "
        "left behind")
    base = os.path.join(root, "nc-h")
    traces, out = os.path.join(base, "traces"), os.path.join(base, "out")
    os.makedirs(traces)
    os.makedirs(out)
    shutil.copy(os.path.join(crm.TRACES, "click-dry.npy"),
                os.path.join(traces, "click-dry.npy"))
    src = json.load(open(os.path.join(crm.TRACES, "sweepmdecaym0.json")))
    grid = {crm.sweep_case_name(v): float(v)
            for v in crm.SWEEP_GRID_DEFAULT}
    for name, requested in grid.items():
        shutil.copy(os.path.join(crm.TRACES, "sweepmdecaym0.wav"),
                    os.path.join(traces, name + ".wav"))
        side = copy.deepcopy(src)
        side["trace"] = name                       # label edited
        side["sweep"] = {"param": "fx4_p3 decaytime",
                         "requested": requested}   # label edited
        # render.overrides_applied["3"] and engine_patch_state decaytime are
        # deliberately UNCHANGED (m0's applied decay): labels cannot vouch
        side["wav"] = src["wav"]  # honest: the artifact IS m0's wav
        side["synthetic_negative_control"] = (
            "issue #456 NC-456-H: trace/requested relabelled, applied and "
            "engine decay left at m0's; not an oracle render")
        with open(os.path.join(traces, name + ".json"), "w") as f:
            json.dump(side, f, indent=2, sort_keys=True)
            f.write("\n")
    sentinel = os.path.join(out, "sweep-t60.json")
    with open(sentinel, "w") as f:
        f.write("committed evidence sentinel\n")
    rc = run_cli(traces, out)
    intact = open(sentinel).read() == "committed evidence sentinel\n"
    no_cov = not os.path.exists(os.path.join(out, "sweep-t60-coverage.json"))
    log("  fixture : every required name declares its own grid value as "
        "requested, but the applied override and engine readback stay at "
        "m0's (5.96e-08)")
    log("  command : sweep --traces-dir <relabelled set> --out-dir <out with "
        "sentinel>")
    log("  exit: %d   sentinel intact: %s   coverage file written: %s"
        % (rc, intact, not no_cov))
    fired = rc == 2 and intact and no_cov
    log("  FIRES (labels alone cannot supply an identity; refuse before "
        "overwriting evidence): %s" % fired)
    log()
    return fired


def main():
    root = tempfile.mkdtemp(prefix="issue456-nc-")
    log("issue #456 -- negative controls for the decay-sweep coverage gate")
    log("")
    log("environment: %s / numpy %s" % (sys.version.split()[0],
                                        np.__version__))
    log("tool under control: worktree tools/compare_reverb_model.py; the "
        "pre-#456 tool is loaded from git %s:tools/compare_reverb_model.py "
        "(fixed commit, not HEAD)" % OLD_TOOL_COMMIT)
    log("all fixtures are synthetic temp constructions; no committed report "
        "or trace is modified")
    log("")
    ok = all([control_a(root), control_b(root), control_c(root),
              control_d(root), control_e(root), control_f(root),
              control_g(root), control_h(root)])
    log("CONTROL SUITE: %s (exit %d)" % ("all controls FIRED" if ok
                                         else "A CONTROL DID NOT FIRE",
                                         0 if ok else 1))
    with open(os.path.join(HERE, "NEGATIVE-CONTROLS.txt"), "w") as f:
        f.write("\n".join(LINES) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
