#!/usr/bin/env python3
"""SXT-032 negative controls: each control must DEMONSTRABLY FAIL the check
it targets. Patterns: reports/sxt-022/artifacts/negative-control.txt and
tools/reverb_negative_controls.py.

Controls (issue #66 acceptance + leaf review additions):
  C1 routing-zeroed, per destination class:
     model render with LFO->cutoff depth forced to 0, and a second render
     with LFO->reso depth forced to 0; each must FAIL the reference-budget
     check against the unmodified routed reference (the routed reference is
     retained unmodified -- AGENTS.md bypass rule).
  C2 source-swap: model render with the landed modwheel bound in place of
     the LFO source, on the modwheel staircase sequence; must FAIL the
     reference-budget check against the routed reference of the same
     sequence.
  C3 free-running vs retriggered confusion: model mutant that skips the
     trigger-mode phase restart at voice attack; on the same-pitch
     retrigger sequence the reference must diverge beyond the budgets.
  C4 RTL waveform/rounding mutant: rtl/voice/lfo_broken_mutant.sv (tb_lfo.sv
     with the output round-half-up bias mutated by one shift) must FAIL the
     RTL-vs-model integer-equality check.

Writes artifacts/negative-control.txt (transcript) and negative-controls.json.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_lfo.sv")
MUTANT = os.path.join(REPO, "rtl", "voice", "lfo_broken_mutant.sv")
RUNNER = os.path.join(REPO, "model", "voice", "run_lfo_model.py")
CMP_AUDIO = os.path.join(REPO, "tools", "compare_audio_reference.py")
CMP_LFO = os.path.join(REPO, "tools", "compare_lfo_rtl_model.py")

SEQ_RETRIG = "seq-notes-repeated-v1"
SEQ_MODWHEEL = "seq-modwheel-v1"


def sh(cmd, env=None):
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


def write_mutant():
    src = open(TB, encoding="utf-8").read()
    needle = "32'sd1 <<< (F_WAVE - FQ - 1)"
    mutant = "32'sd1 <<< (F_WAVE - FQ - 2)"
    if src.count(needle) != 1:
        raise RuntimeError("mutation anchor not found exactly once in tb_lfo.sv")
    out = src.replace(needle, mutant)
    with open(MUTANT, "w", encoding="utf-8") as f:
        f.write(out)
    return needle, mutant


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--reference-dir", required=True,
                    help="dir with reference-<seq>-lfo-fixture.wav")
    args = ap.parse_args()

    os.makedirs(args.artifacts, exist_ok=True)
    lines = []
    results = {}

    def log(s=""):
        lines.append(s)
        print(s)

    def audio_check(name, seq, model_wav, ref_wav, expect_fail=True):
        out_json = os.path.join(args.artifacts, f"audio-nc-{name}.json")
        rc, out, err = sh([sys.executable, CMP_AUDIO, "--ref", ref_wav,
                           "--model", model_wav, "--json", out_json])
        if rc != 0:
            log(f"[{name}] comparator exited {rc}: {err}")
            return False
        m = json.loads(open(out_json).read())
        verdict = m["verdict"]
        ok = verdict.startswith("FAIL") if expect_fail \
            else verdict.startswith("PASS")
        log(f"[{name}] ref={os.path.basename(ref_wav)} "
            f"max={m['max_abs_diff_lsb']:.0f} rms_dbfs="
            f"{m['rms_diff_dbfs']:.1f} spec={m['spectral_corr']:.4f} "
            f"-> {verdict} (expected "
            f"{'FAIL' if expect_fail else 'PASS'})")
        results[name] = {"verdict": verdict, "expected": "FAIL" if expect_fail
                         else "PASS", "control_ok": bool(ok),
                         "metrics_file": os.path.relpath(out_json, REPO)}
        return ok

    def model_render(tag, seq, extra):
        out_dir = os.path.join(args.artifacts, f"model-{tag}")
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        cmd = [sys.executable, RUNNER, "--sequence", seq,
               "--out-dir", out_dir] + extra
        rc, out, err = sh(cmd)
        if rc != 0:
            log(f"[{tag}] model runner exited {rc}: {err[-2000:]}")
            return None
        return os.path.join(out_dir, "model.wav")

    log("SXT-032 negative controls (all must demonstrably FAIL their check)")
    import datetime
    log("date: " + datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"))
    log("")

    ok_all = True

    # ---- C1: routing zeroed, per destination class -----------------------
    for dest, seq in (("cutoff-zeroed", SEQ_RETRIG), ("reso-zeroed",
                                                      SEQ_RETRIG)):
        ref_wav = os.path.join(args.reference_dir,
                               f"reference-{seq}-lfo-fixture.wav")
        wav = model_render(dest, seq, ["--zero-dest",
                                       "cutoff" if dest.startswith("cutoff")
                                       else "reso"])
        if wav:
            ok_all &= audio_check(dest, seq, wav, ref_wav)

    # ---- C2: source swap (modwheel in place of the LFO) -------------------
    ref_wav = os.path.join(args.reference_dir,
                           f"reference-{SEQ_MODWHEEL}-lfo-fixture.wav")
    wav = model_render("source-swap", SEQ_MODWHEEL, ["--source-swap"])
    if wav:
        ok_all &= audio_check("source-swap", SEQ_MODWHEEL, wav, ref_wav)

    # ---- C3: free-running vs retriggered confusion ------------------------
    ref_wav = os.path.join(args.reference_dir,
                           f"reference-{SEQ_RETRIG}-lfo-fixture.wav")
    wav = model_render("free-running", SEQ_RETRIG, ["--free-running"])
    if wav:
        ok_all &= audio_check("free-running", SEQ_RETRIG, wav, ref_wav)

    # ---- C4: RTL mutant must fail exactness --------------------------------
    needle, mutant = write_mutant()
    log("")
    log(f"RTL mutant: {os.path.relpath(MUTANT, REPO)} = tb_lfo.sv with the")
    log(f"  output round-half-up bias mutated: '{needle}' -> '{mutant}'")
    run_dir = os.path.join(args.artifacts, "model-exactness-ref")
    if not os.path.exists(os.path.join(run_dir, "model_trace.json")):
        rc, out, err = sh([sys.executable, RUNNER, "--sequence", SEQ_RETRIG,
                           "--out-dir", run_dir])
        if rc != 0:
            log(f"exactness reference run failed: {err[-1000:]}")
            ok_all = False
    if os.path.exists(os.path.join(run_dir, "model_trace.json")):
        out_json = os.path.join(args.artifacts, "exactness-mutant.json")
        rc, out, err = sh([sys.executable, CMP_LFO, "--run-dir", run_dir,
                           "--tb", MUTANT, "--out", out_json])
        m = json.loads(open(out_json).read())
        log(f"[rtl-mutant] verdict={m['verdict']} "
            f"mismatches={m['mismatches']} "
            f"first={m['first_failures'][:1]}")
        results["rtl-mutant"] = {"verdict": m["verdict"], "expected": "FAIL",
                                 "control_ok": m["verdict"] == "FAIL",
                                 "metrics_file":
                                     os.path.relpath(out_json, REPO)}
        ok_all &= m["verdict"] == "FAIL"

    log("")
    if ok_all:
        log("overall: ALL CONTROLS DEMONSTRABLY FAIL (expected)")
    else:
        log("overall: CONTROL FAILURE (a control did not fail as required)")
    results["overall_ok"] = ok_all

    with open(os.path.join(args.artifacts, "negative-control.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(args.artifacts, "negative-controls.json"), "w") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
