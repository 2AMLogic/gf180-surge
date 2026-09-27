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
     and trip the control-plane smoothing discriminator (issue #163): the
     smoothed modwheel word's blocks-to-converge after each CC dispatch,
     read from model_trace.json. The whole-render audio legs do not
     discriminate for this mutant (its rms is BETTER than the unmutated
     model's, and its spectral margin is a few thousandths wide and
     definition-dependent), so C2 no longer rests on them.
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
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402

TB = os.path.join(REPO, "rtl", "voice", "tb_mw.sv")
MUTANT = os.path.join(REPO, "rtl", "voice", "tb_mw_broken_mutant.sv")
RUNNER = os.path.join(REPO, "model", "voice", "run_mw_model.py")
EXTRACTOR = os.path.join(REPO, "model", "voice", "extract_inputs_v2.py")
CMP_AUDIO = os.path.join(REPO, "tools", "compare_audio_reference.py")
CMP_MW = os.path.join(REPO, "tools", "compare_mw_rtl_model.py")

SEQ_MW = "seq-modwheel-v1"
SEQ_FILE = os.path.join(REPO, "fixtures", "sequences", SEQ_MW + ".json")

# ---- C2 control-plane discriminator (issue #163) --------------------------
# The declared FAST_LINE smoother (voice_model.Modwheel) steps the modwheel
# word once per control block by da = (target - startingpoint) * inv, with
# inv = qint(1 / (50 * 48000/44100)). da is constant for the whole dispatch,
# so ANY dispatch needs ~1/inv blocks to reach its target, independent of the
# step size. `--no-smoothing` (run_mw_model.NoSmoothingModwheel) reaches the
# target inside set_target, i.e. in 0 blocks. The trip threshold is half the
# declared ramp, far from BOTH measured values (54 blocks smoothed, 0
# bypassed), so this leg is not a thin margin -- and it reads only the
# control plane (model_trace.json), never the audio render, the reference,
# or the global spectral_corr metric.
DECLARED_RAMP_BLOCKS = (1 << vm.FQ) / vm.Modwheel().inv
MIN_RAMP_BLOCKS = int(DECLARED_RAMP_BLOCKS // 2)

CARRIERS = [
    "resources/data/patches_3rdparty/Bluelight/Pads/Rainy Day Dreamaway.fxp",
    "resources/data/patches_3rdparty/Emu/Plucks/Pluck 2 Pad Demon Sad.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Alone.fxp",
]


def sh(cmd, env=None):
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


def mw_cc_dispatches():
    """[(block, cc_value, target_q21)] -- one per CC1 event in the fixture.

    The dispatch block mirrors run_mw_model.py's event pump, which consumes
    every event with ceil(t / BLOCK_SIZE) <= b at block b.
    """
    with open(SEQ_FILE, encoding="utf-8") as f:
        seq = json.load(f)
    out = []
    for e in seq["events"]:
        if (e["type"] == "cc" and e.get("channel") == 0
                and e.get("controller") == 1):
            b = -(-e["t"] // vm.BLOCK_SIZE)
            out.append((b, e["value"], vm.qint(e["value"] / 127.0)))
    return out


def mw_ramp_profile(run_dir):
    """Blocks-to-converge of the smoothed modwheel word per CC dispatch.

    Reads the per-block `mw_pre`/`mw_value` records that run_mw_model.py
    writes into model_trace.json (model/voice/run_mw_model.py: the modsource
    step runs at the END of the control pass). Returns
    (per_dispatch, min_ramp_blocks), or (None, None) when the trace is
    absent or a dispatch never reaches its target inside the trace.
    """
    path = os.path.join(run_dir, "model_trace.json")
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8") as f:
        blocks = json.load(f).get("blocks") or []
    by_b = {blk["b"]: blk for blk in blocks if "mw_value" in blk}
    per = []
    for b0, cc, target in mw_cc_dispatches():
        n = 0
        while (b0 + n) in by_b and by_b[b0 + n]["mw_value"] != target:
            n += 1
        if (b0 + n) not in by_b:
            return None, None
        per.append({"block": b0, "cc": cc, "target_q21": target,
                    "ramp_blocks": n})
    if not per:
        return None, None
    return per, min(p["ramp_blocks"] for p in per)


def ramp_discriminator(run_dir):
    """(trips, detail) for the C2 control-plane smoothing discriminator.

    `trips` is True when the run's fastest CC dispatch converges in fewer
    than MIN_RAMP_BLOCKS blocks, i.e. the declared FAST_LINE ramp is not
    present. `detail` is None when the trace could not be read (reported as
    unavailable -- NOT as a trip).
    """
    per, mn = mw_ramp_profile(run_dir)
    if per is None:
        return False, None
    return bool(mn < MIN_RAMP_BLOCKS), {
        "metric": "blocks-to-converge of the smoothed modwheel word "
                  "after each CC dispatch (model_trace.json mw_value)",
        "declared_ramp_blocks": DECLARED_RAMP_BLOCKS,
        "threshold_blocks": MIN_RAMP_BLOCKS,
        "min_ramp_blocks": mn,
        "max_ramp_blocks": max(p["ramp_blocks"] for p in per),
        "margin_blocks": MIN_RAMP_BLOCKS - mn,
        "discriminator_trips": bool(mn < MIN_RAMP_BLOCKS),
        "per_dispatch": per,
    }


def read_i16(path):
    with wave.open(path) as w:
        return np.frombuffer(w.readframes(w.getnframes()),
                             dtype="<i2").astype(np.float64)


def transition_window_rms(ref_wav, model_wav):
    """RMS of (ref - model) over the CC-transition windows only.

    The windowed variant of SXT-042's note_windows()/windowed_rms() pattern
    (tools/kt_negative_controls.py), evaluated for C2 and RECORDED FOR THE
    RECORD ONLY -- it is not a discriminator here. On this intentionally
    clipped fixture the reference saturates at the int16 span through most
    of the ramps, so a smoothing mutant can land *closer* to the clipped
    reference inside the very windows where smoothing matters. The numbers
    are written out so that conclusion is checkable rather than asserted.
    """
    ref, mdl = read_i16(ref_wav), read_i16(model_wav)
    ramp = math.ceil(DECLARED_RAMP_BLOCKS)
    acc_s, acc_n, per = 0.0, 0, []
    for b0, cc, _target in mw_cc_dispatches():
        t0, t1 = b0 * vm.BLOCK_SIZE, (b0 + ramp) * vm.BLOCK_SIZE
        d = ref[t0:t1] - mdl[t0:t1]
        if not len(d):
            continue
        acc_s += float((d * d).sum())
        acc_n += len(d)
        per.append({"block": b0, "cc": cc,
                    "rms_lsb": float(np.sqrt((d * d).mean())),
                    "ref_saturated_frac":
                        float((np.abs(ref[t0:t1]) >= 32767).mean())})
    if not acc_n:
        return None
    return {"note": "recorded only -- NOT a discriminator (see docstring)",
            "window_blocks_after_each_cc": ramp,
            "rms_lsb": float(np.sqrt(acc_s / acc_n)),
            "per_window": per}


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

    def run_dir_of(wav):
        return os.path.dirname(wav)

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

    # ---- failure control for the C2 control-plane discriminator (#163) ----
    # The unmutated model MUST NOT trip the smoothing discriminator; if it
    # does, the discriminator is not measuring what it claims to and the
    # whole control record is void.
    if base_wav:
        base_trips, base_ramp = ramp_discriminator(run_dir_of(base_wav))
        if base_ramp is None:
            log("[baseline] mw-ramp failure control: trace unavailable "
                "-> NOT_RUN (control record void)")
            ok_all = False
        else:
            log(f"[baseline] mw-ramp failure control: min ramp="
                f"{base_ramp['min_ramp_blocks']} blocks over "
                f"{len(base_ramp['per_dispatch'])} CC dispatches "
                f"(declared FAST_LINE ramp "
                f"{base_ramp['declared_ramp_blocks']:.2f} blocks, trips below "
                f"{base_ramp['threshold_blocks']}) -> trips={base_trips} "
                f"(expected False on the unmutated model)")
            results["baseline"]["mw_ramp"] = base_ramp
            tw = transition_window_rms(ref_wav, base_wav)
            if tw:
                results["baseline"]["transition_window_rms"] = tw
                log(f"[baseline] transition-window rms (recorded, not a "
                    f"discriminator): {tw['rms_lsb']:.1f} LSB over "
                    f"{len(tw['per_window'])} windows")
            if base_trips:
                log("[baseline] FAILURE CONTROL VIOLATED: the unmutated model "
                    "trips the smoothing discriminator")
                ok_all = False
    log("")

    def budget_control(name, tag, extra, ramp_check=False):
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
        # or spectral-correlation drop) relative to the unmutated model, or
        # (C2 only, issue #163) trips the control-plane smoothing
        # discriminator, which reads no audio metric at all.
        fails_budget = m["verdict"].startswith("FAIL")
        worse_max = bool(base and m["max_abs_diff_lsb"] > base["max_abs_diff_lsb"])
        worse_rms = bool(base and m["rms_diff_lsb"] > base["rms_diff_lsb"])
        worse_spec = bool(base and m["spectral_corr"] < base["spectral_corr"])
        discrim = [n for w, n in ((worse_max, "max"), (worse_rms, "rms"),
                                  (worse_spec, "spectral")) if w]
        entry = {
            "verdict": m["verdict"], "expected": "FAIL",
            "max_abs_diff_lsb": m["max_abs_diff_lsb"],
            "rms_diff_lsb": m["rms_diff_lsb"],
            "rms_diff_dbfs": m["rms_diff_dbfs"],
            "spectral_corr": m["spectral_corr"],
            "metrics_file": os.path.relpath(
                os.path.join(args.artifacts, f"audio-nc-{name}.json"), REPO),
        }
        if ramp_check:
            trips, ramp = ramp_discriminator(run_dir_of(wav))
            entry["mw_ramp"] = ramp
            tw = transition_window_rms(ref_wav, wav)
            base_tw = (results.get("baseline") or {}).get(
                "transition_window_rms")
            if tw:
                tw["worse_than_baseline"] = bool(
                    base_tw and tw["rms_lsb"] > base_tw["rms_lsb"])
                entry["transition_window_rms"] = tw
                vs = (f" vs baseline {base_tw['rms_lsb']:.1f} LSB -> worse="
                      f"{tw['worse_than_baseline']}" if base_tw else "")
                log(f"[{name}] transition-window rms (recorded, not a "
                    f"discriminator): {tw['rms_lsb']:.1f} LSB{vs}")
            if trips:
                discrim.append("mw-ramp")
            if ramp is None:
                log(f"[{name}] mw-ramp: trace unavailable -> NOT_RUN")
            else:
                log(f"[{name}] mw-ramp: min ramp={ramp['min_ramp_blocks']} "
                    f"blocks over {len(ramp['per_dispatch'])} CC dispatches "
                    f"(declared {ramp['declared_ramp_blocks']:.2f}, trips "
                    f"below {ramp['threshold_blocks']}) -> trips={trips}, "
                    f"margin={ramp['margin_blocks']} blocks")
        ok = bool(fails_budget and discrim)
        entry["control_ok"] = ok
        entry["beyond_model_error_via"] = discrim
        # Recorded so a later change to the spectral_corr definition (#110)
        # cannot silently retire this control: True means the control still
        # holds with the whole-render spectral leg struck out entirely.
        entry["control_ok_without_spectral_leg"] = bool(
            fails_budget and [d for d in discrim if d != "spectral"])
        log(f"[{name}] max={m['max_abs_diff_lsb']:.0f} "
            f"rms={m['rms_diff_dbfs']:.1f}dBFS spec={m['spectral_corr']:.4f} "
            f"-> {m['verdict']}; beyond-model-error via={discrim or 'NONE'} "
            f"(expected FAIL and worse); without the spectral leg -> "
            f"{entry['control_ok_without_spectral_leg']}")
        results[name] = entry
        ok_all &= ok

    # ---- C1: routing zeroed, per destination class ------------------------
    budget_control("cutoff-zeroed", "cutoff-zeroed", ["--zero-dest", "cutoff"])
    budget_control("reso-zeroed", "reso-zeroed", ["--zero-dest", "reso"])
    budget_control("vca-zeroed", "vca-zeroed", ["--zero-dest", "vca"])

    # ---- C2: smoothing bypass ---------------------------------------------
    budget_control("smoothing-bypass", "smoothing-bypass", ["--no-smoothing"],
                   ramp_check=True)

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
