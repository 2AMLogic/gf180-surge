#!/usr/bin/env python3
"""SXT-035 negative controls: each control must DEMONSTRABLY FAIL the check
it targets. Patterns: reports/sxt-022/artifacts/negative-control.txt,
tools/reverb_negative_controls.py, tools/lfo_negative_controls.py.

Controls (issue #69 acceptance + leaf review additions):
  C1 routing-zeroed, per destination class: model render with the modwheel->
     Filter-1-Cutoff depth forced to 0, a second with Resonance forced to 0,
     a third with VCA-Gain forced to 0; each must FAIL the reference-budget
     check against the unmodified routed reference AND degrade a metric with
     headroom (rms or spectral correlation) relative to the unmutated
     model's own error on the same sequence (the routed reference is
     retained unmodified -- AGENTS.md bypass rule; max-abs saturates at the
     int16 span on this intentionally-clipped fixture and cannot
     discriminate -- recorded per control).
  C2 smoothing-bypass: model render with the landed FAST_LINE smoothing
     bypassed (value jumps to target); must FAIL the reference-budget check
     and exceed the model's own error.
  C3 source-swap: model render with the landed SXT-032 LFO1 bound in place
     of the modwheel source (per-voice instances, keytrigger); must FAIL
     the reference-budget check and exceed the model's own error.
  C4 out-of-class refusal: a route to 'A Highpass' (dest 303) must be
     REFUSED by the runner (exit 2, destination named); plus the leaf's
     named carrier presets must be REFUSED by the fail-closed v2 extractor.
  C5 RTL mutant: rtl/voice/tb_mw_broken_mutant.sv (tb_mw.sv with the
     FAST_LINE da rounding mutated by one shift) must FAIL the
     RTL-vs-model integer-equality check.

Writes artifacts/negative-control.txt (transcript) and negative-controls.json.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_mw.sv")
MUTANT = os.path.join(REPO, "rtl", "voice", "tb_mw_broken_mutant.sv")
RUNNER = os.path.join(REPO, "model", "voice", "run_mw_model.py")
EXTRACTOR = os.path.join(REPO, "model", "voice", "extract_inputs_v2.py")
CMP_AUDIO = os.path.join(REPO, "tools", "compare_audio_reference.py")
CMP_MW = os.path.join(REPO, "tools", "compare_mw_rtl_model.py")

SEQ_MW = "seq-modwheel-v1"
CARRIERS = [
    "resources/data/patches_3rdparty/Bluelight/Pads/Rainy Day Dreamaway.fxp",
    "resources/data/patches_3rdparty/Emu/Plucks/Pluck 2 Pad Demon Sad.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Alone.fxp",
]


def sh(cmd, env=None):
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


def write_mutant():
    src = open(TB, encoding="utf-8").read()
    needle = "da    = qmul_sh(tp_sp, INV, FQ);"
    mutant = "da    = qmul_sh(tp_sp, INV, FQ-1);"
    if src.count(needle) != 1:
        raise RuntimeError("mutation anchor not found exactly once in tb_mw.sv")
    with open(MUTANT, "w", encoding="utf-8") as f:
        f.write(src.replace(needle, mutant))
    return needle, mutant


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--reference-dir", required=True,
                    help="dir with reference-<seq>-mw-fixture.wav")
    args = ap.parse_args()

    os.makedirs(args.artifacts, exist_ok=True)
    lines = []
    results = {}

    def log(s=""):
        lines.append(s)
        print(s)

    ref_wav = os.path.join(args.reference_dir,
                           f"reference-{SEQ_MW}-mw-fixture.wav")

    def audio_metrics(name, model_wav):
        out_json = os.path.join(args.artifacts, f"audio-nc-{name}.json")
        rc, out, err = sh([sys.executable, CMP_AUDIO, "--ref", ref_wav,
                           "--model", model_wav, "--json", out_json])
        if rc != 0:
            log(f"[{name}] comparator exited {rc}: {err[-500:]}")
            return None
        return json.loads(open(out_json).read())

    def model_render(tag, seq, extra):
        out_dir = os.path.join(args.artifacts, f"model-{tag}")
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        rc, out, err = sh([sys.executable, RUNNER, "--sequence", seq,
                           "--out-dir", out_dir] + extra)
        if rc != 0:
            log(f"[{tag}] model runner exited {rc}: {err[-800:]}")
            return None
        return os.path.join(out_dir, "model.wav")

    log("SXT-035 negative controls (all must demonstrably FAIL their check)")
    import datetime
    log("date: " + datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"))
    log(f"reference (unmodified routed fixture): {ref_wav}")
    log("")

    ok_all = True

    # ---- baseline: unmutated model vs reference ---------------------------
    base_wav = model_render("baseline", SEQ_MW, [])
    base = audio_metrics("baseline", base_wav) if base_wav else None
    if base:
        log(f"[baseline] unmutated model-vs-reference: max={base['max_abs_diff_lsb']:.0f} "
            f"rms={base['rms_diff_dbfs']:.1f}dBFS spec={base['spectral_corr']:.4f} "
            f"-> {base['verdict']}")
        results["baseline"] = {
            "verdict": base["verdict"], "expected": "informational",
            "max_abs_diff_lsb": base["max_abs_diff_lsb"],
            "rms_diff_dbfs": base["rms_diff_dbfs"],
            "spectral_corr": base["spectral_corr"],
        }
    else:
        ok_all = False
    log("")

    def budget_control(name, tag, extra):
        nonlocal ok_all
        wav = model_render(tag, SEQ_MW, extra)
        if not wav:
            ok_all = False
            results[name] = {"control_ok": False, "why": "render failed"}
            return
        m = audio_metrics(name, wav)
        if m is None:
            ok_all = False
            results[name] = {"control_ok": False, "why": "comparator failed"}
            return
        # On this fixture the model-vs-reference max-abs error saturates at
        # the int16 span (the routed reference is intentionally driven into
        # hard clipping), so max-abs cannot discriminate. A control is
        # "demonstrably beyond the model's own error" when it fails the
        # budget check AND degrades ANY metric with headroom (rms increase
        # or spectral-correlation drop) relative to the unmutated model.
        fails_budget = m["verdict"].startswith("FAIL")
        worse_max = bool(base and m["max_abs_diff_lsb"] > base["max_abs_diff_lsb"])
        worse_rms = bool(base and m["rms_diff_lsb"] > base["rms_diff_lsb"])
        worse_spec = bool(base and m["spectral_corr"] < base["spectral_corr"])
        discrim = [w for w, n in ((worse_max, "max"), (worse_rms, "rms"),
                                  (worse_spec, "spectral")) if w]
        ok = bool(fails_budget and discrim)
        log(f"[{name}] max={m['max_abs_diff_lsb']:.0f} "
            f"rms={m['rms_diff_dbfs']:.1f}dBFS spec={m['spectral_corr']:.4f} "
            f"-> {m['verdict']}; beyond-model-error via={discrim or 'NONE'} "
            f"(expected FAIL and worse)")
        results[name] = {
            "verdict": m["verdict"], "expected": "FAIL",
            "control_ok": ok,
            "max_abs_diff_lsb": m["max_abs_diff_lsb"],
            "rms_diff_lsb": m["rms_diff_lsb"],
            "rms_diff_dbfs": m["rms_diff_dbfs"],
            "spectral_corr": m["spectral_corr"],
            "beyond_model_error_via": discrim,
            "metrics_file": os.path.relpath(
                os.path.join(args.artifacts, f"audio-nc-{name}.json"), REPO),
        }
        ok_all &= ok

    # ---- C1: routing zeroed, per destination class ------------------------
    budget_control("cutoff-zeroed", "cutoff-zeroed", ["--zero-dest", "cutoff"])
    budget_control("reso-zeroed", "reso-zeroed", ["--zero-dest", "reso"])
    budget_control("vca-zeroed", "vca-zeroed", ["--zero-dest", "vca"])

    # ---- C2: smoothing bypass ---------------------------------------------
    budget_control("smoothing-bypass", "smoothing-bypass", ["--no-smoothing"])

    # ---- C3: source swap (landed LFO1 in place of the modwheel) -----------
    budget_control("source-swap-lfo", "source-swap-lfo",
                   ["--source-swap-lfo"])

    # ---- C4: out-of-class refusal (route gate + carrier extraction) -------
    log("")
    rc, out, err = sh([sys.executable, RUNNER, "--sequence", SEQ_MW,
                       "--out-dir", os.path.join(args.artifacts,
                                                 "refused-out-of-class"),
                       "--out-of-class-route"])
    refused = (rc == 2) and "outside the declared SXT-035 destination class" in err
    log(f"[out-of-class-route] exit={rc} refused={refused} msg={err.strip()[:160]}")
    results["out-of-class-route"] = {"expected": "REFUSE (exit 2)",
                                     "control_ok": refused}
    ok_all &= refused

    for rel in CARRIERS:
        tag = "carrier-" + os.path.basename(rel).replace(" ", "_")
        with tempfile.TemporaryDirectory() as td:
            rc, out, err = sh([sys.executable, EXTRACTOR, "--preset-rel", rel,
                               "--out", os.path.join(td, "x.json")])
        refused = rc == 2
        log(f"[{tag}] extractor exit={rc} refused={refused} msg={err.strip()[:160]}")
        results[tag] = {"expected": "REFUSE (exit 2)", "control_ok": refused,
                        "refusal": err.strip()[:300]}
        ok_all &= refused

    # ---- C5: RTL mutant must fail exactness --------------------------------
    needle, mutant = write_mutant()
    log("")
    log(f"RTL mutant: {os.path.relpath(MUTANT, REPO)} = tb_mw.sv with the")
    log(f"  FAST_LINE da rounding mutated: '{needle}' -> '{mutant}'")
    run_dir = os.path.join(args.artifacts, "model-exactness-ref")
    if not os.path.exists(os.path.join(run_dir, "model_trace.json")):
        rc, out, err = sh([sys.executable, RUNNER, "--sequence", SEQ_MW,
                           "--out-dir", run_dir])
        if rc != 0:
            log(f"exactness reference run failed: {err[-800:]}")
            ok_all = False
    if os.path.exists(os.path.join(run_dir, "model_trace.json")):
        out_json = os.path.join(args.artifacts, "exactness-mutant.json")
        sh([sys.executable, CMP_MW, "--run-dir", run_dir,
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
