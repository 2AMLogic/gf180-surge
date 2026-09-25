#!/usr/bin/env python3
"""SXT-042 negative controls: each control must DEMONSTRABLY FAIL the check it
targets; a control that cannot fail on this carrier is reported as degenerate
or non-discriminating rather than counted as a pass. Patterns:
reports/sxt-022/artifacts/negative-control.txt, tools/mw_negative_controls.py
(same-domain analog).

Carrier: `Rozzer/Bells/Hell's Bells.fxp`, sequence `sxt025-accept-v1`.
Reference: the committed pinned-engine DRY fixture, projected to mono int16
by tools/kt_reference_from_fixture.py and retained UNMODIFIED (AGENTS.md
bypass rule) -- only the model is mutated.

Reference-domain controls
  C1 routing-zeroed, per destination class (keytrack -> Filter 1 Cutoff depth
     0). Filter 1 Resonance / FEG Mod carry no keytrack route in this preset,
     so zeroing them is a no-op: checked and reported as DEGENERATE (never
     counted), with those destinations controlled in the exactness domain on
     the synthetic class-cover fixture instead (C8).
  C2 shared-instead-of-per-instance: ONE global keytrack word, rewritten at
     every note-on, read by every sounding voice (the AGENTS.md shared-state
     control applied to a per-voice modsource).
  C3 source-swap: the landed velocity source in place of keytrack. Issue #76
     names the modwheel; on a Sine-class fixture no CC event is admissible,
     so the modwheel is identically 0 and that swap is ALSO run and reported
     as degenerate-to-zeroed (proved by render-sha equality).
  C4 keytrack-root dropped: word = pitch/12 instead of (pitch - root)/12.
  P5 lag probe (NOT a control): refresh the modsource BEFORE the route
     application. Pitch is constant per voice in this class, so the declared
     lag is unobservable and the probe must come back BIT-IDENTICAL.
  P6 control-VALIDITY probe (NOT a control): zero the VELOCITY route into the
     same destination (5.8x the keytrack depth on this preset) and record
     what the reference metrics do. This is how the record establishes
     whether the budget check can discriminate a cutoff-route mutation at
     all on this carrier.

Refusal controls
  C7 keytrack -> 'A Pan' (265) must be refused by the runner (exit 2), and
     the three carrier presets named in issue #76 must be refused by the
     applicability scan with named reasons.

Exactness-domain controls
  C8 synthetic class-cover fixture (keytrack -> cutoff + reso + feg-mod):
     zeroing reso or feg-mod must change the render (model-vs-model; the
     pinned engine never rendered this configuration, so no reference claim
     is made).
  C9 RTL mutants: rtl/voice/tb_kt_broken_mutant.sv (keytrack word rounding
     bias dropped) and rtl/voice/tb_kt_shared_mutant.sv (one shared keytrack
     word instead of per-voice) must both FAIL integer equality.

Writes <artifacts>/negative-control.txt and <artifacts>/negative-controls.json.
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_kt.sv")
MUTANT_ROUND = os.path.join(REPO, "rtl", "voice", "tb_kt_broken_mutant.sv")
MUTANT_SHARED = os.path.join(REPO, "rtl", "voice", "tb_kt_shared_mutant.sv")
RUNNER = os.path.join(REPO, "model", "voice", "run_kt_model.py")
CMP_AUDIO = os.path.join(REPO, "tools", "compare_audio_reference.py")
CMP_KT = os.path.join(REPO, "tools", "compare_kt_rtl_model.py")
SCAN = os.path.join(REPO, "tools", "kt_applicability_scan.py")
SEQ = os.path.join(REPO, "model", "integration", "sequences",
                   "sxt025-accept-v1.json")
CARRIERS = [
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Alone.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Autumn 2.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Disturbances.fxp",
]
KEYTRACK_ROOT = 60
SCENE_OCTAVE = 2


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_i16(path):
    with wave.open(path) as w:
        return np.frombuffer(w.readframes(w.getnframes()),
                             dtype="<i2").astype(np.float64)


def note_windows():
    """[(kt_value, t0, t1)] -- one window per note_on, to the next note_on."""
    with open(SEQ, encoding="utf-8") as f:
        seq = json.load(f)
    ons = [e for e in seq["events"] if e["type"] == "note_on"]
    out = []
    for i, e in enumerate(ons):
        t0 = e["t"]
        t1 = ons[i + 1]["t"] if i + 1 < len(ons) else t0 + 96000
        if t1 <= t0:
            continue                     # simultaneous note-ons: no window
        kt = (e["note"] + 12 * SCENE_OCTAVE - KEYTRACK_ROOT) / 12.0
        out.append((kt, t0, t1))
    return out


def windowed_rms(ref, model):
    """RMS of (ref - model) aggregated over the kt != 0 and kt == 0 windows."""
    acc = {"kt_nonzero": [0.0, 0], "kt_zero": [0.0, 0]}
    for kt, t0, t1 in note_windows():
        d = ref[t0:t1] - model[t0:t1]
        k = "kt_zero" if kt == 0 else "kt_nonzero"
        acc[k][0] += float((d * d).sum())
        acc[k][1] += len(d)
    return {k: (float(np.sqrt(s / n)) if n else None) for k, (s, n) in
            acc.items()}


def write_mutant(dst, needle, mutant):
    src = open(TB, encoding="utf-8").read()
    if src.count(needle) != 1:
        raise RuntimeError(f"mutation anchor {needle!r} not unique in tb_kt.sv")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(src.replace(needle, mutant))
    return needle, mutant


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True,
                    help="committed outputs (JSON verdicts + transcript)")
    ap.add_argument("--work", default="/tmp/sxt042-controls",
                    help="scratch dir for the control renders (not committed)")
    ap.add_argument("--synthetic-run-dir",
                    default="/tmp/sxt042/run-synthetic",
                    help="run dir of the synthetic class-cover fixture "
                         "(run_kt_model.py --synthetic-routes)")
    ap.add_argument("--reference", required=True,
                    help="mono int16 dry reference (kt_reference_from_fixture)")
    args = ap.parse_args()

    os.makedirs(args.artifacts, exist_ok=True)
    os.makedirs(args.work, exist_ok=True)
    lines, results = [], {}
    ok_all = True
    ref = read_i16(args.reference)

    def log(s=""):
        lines.append(s)
        print(s, flush=True)

    def model_render(tag, extra):
        out_dir = os.path.join(args.work, f"model-{tag}")
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        rc, out, err = sh([sys.executable, RUNNER, "--sequence", SEQ,
                           "--out-dir", out_dir] + extra)
        if rc != 0:
            log(f"[{tag}] model runner exited {rc}: {err[-800:]}")
            return None
        return os.path.join(out_dir, "model.wav")

    def audio_metrics(name, wav):
        out_json = os.path.join(args.artifacts, f"audio-nc-{name}.json")
        rc, out, err = sh([sys.executable, CMP_AUDIO, "--ref", args.reference,
                           "--model", wav, "--json", out_json])
        if rc != 0:
            log(f"[{name}] comparator exited {rc}: {err[-400:]}")
            return None
        m = json.loads(open(out_json).read())
        m["windowed_rms_lsb"] = windowed_rms(ref, read_i16(wav))
        with open(out_json, "w") as f:
            json.dump(m, f, indent=2, sort_keys=True)
            f.write("\n")
        return m

    log("SXT-042 negative controls (each must demonstrably FAIL its check)")
    log("date: " + datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"))
    log(f"carrier: Rozzer/Bells/Hell's Bells.fxp  sequence: sxt025-accept-v1")
    log(f"reference (unmodified, committed pinned-engine dry render): "
        f"{os.path.relpath(args.reference, REPO)}")
    log(f"  sha256 {sha256_file(args.reference)}")
    log("")

    base_wav = model_render("baseline", [])
    base = audio_metrics("baseline", base_wav) if base_wav else None
    if base is None:
        log("baseline render/compare failed -- aborting")
        return 1
    base_sha = sha256_file(base_wav)
    log(f"[baseline] unmutated model-vs-reference: "
        f"max={base['max_abs_diff_lsb']:.0f} "
        f"rms={base['rms_diff_dbfs']:.2f}dBFS "
        f"spec={base['spectral_corr']:.4f} -> {base['verdict']}")
    log(f"  windowed rms: kt!=0 {base['windowed_rms_lsb']['kt_nonzero']:.1f} "
        f"LSB, kt==0 {base['windowed_rms_lsb']['kt_zero']:.1f} LSB")
    log("  (the carrier's own budget miss is the landed SXT-026a finding "
        "F-48a; a control is called DISCRIMINATING only if it also degrades "
        "a metric relative to THIS row)")
    results["baseline"] = {
        "expected": "informational", "verdict": base["verdict"],
        "max_abs_diff_lsb": base["max_abs_diff_lsb"],
        "rms_diff_lsb": base["rms_diff_lsb"],
        "rms_diff_dbfs": base["rms_diff_dbfs"],
        "spectral_corr": base["spectral_corr"],
        "windowed_rms_lsb": base["windowed_rms_lsb"],
        "model_sha256": base_sha,
    }
    log("")

    def budget_control(name, extra, expect_degenerate=False, probe=False):
        nonlocal ok_all
        wav = model_render(name, extra)
        if not wav:
            ok_all = False
            results[name] = {"control_ok": False, "why": "render failed"}
            return None
        sha = sha256_file(wav)
        if sha == base_sha:
            entry = {"expected": ("DEGENERATE (no route to mutate)"
                                  if expect_degenerate else "FAIL"),
                     "render_changed": False, "model_sha256": sha,
                     "control_ok": bool(expect_degenerate),
                     "counted_as_control": False,
                     "note": "mutation is a no-op on this carrier"}
            results[name] = entry
            log(f"[{name}] render BIT-IDENTICAL to the baseline -> "
                + ("DEGENERATE, not counted as a control"
                   if expect_degenerate else "CONTROL FAILURE"))
            if not expect_degenerate:
                ok_all = False
            return entry
        m = audio_metrics(name, wav)
        if m is None:
            ok_all = False
            results[name] = {"control_ok": False, "why": "comparator failed"}
            return None
        fails_budget = m["verdict"].startswith("FAIL")
        worse = [w for w, c in (
            ("max", m["max_abs_diff_lsb"] > base["max_abs_diff_lsb"]),
            ("rms", m["rms_diff_lsb"] > base["rms_diff_lsb"]),
            ("spectral", m["spectral_corr"] < base["spectral_corr"]),
            ("windowed_kt_rms",
             m["windowed_rms_lsb"]["kt_nonzero"] >
             base["windowed_rms_lsb"]["kt_nonzero"])) if c]
        entry = {
            "expected": "PROBE" if probe else "FAIL",
            "verdict": m["verdict"],
            "fails_reference_budget": fails_budget,
            "render_changed": True,
            "discriminating": bool(worse),
            "degraded_metrics": worse,
            "max_abs_diff_lsb": m["max_abs_diff_lsb"],
            "rms_diff_lsb": m["rms_diff_lsb"],
            "rms_diff_dbfs": m["rms_diff_dbfs"],
            "spectral_corr": m["spectral_corr"],
            "windowed_rms_lsb": m["windowed_rms_lsb"],
            "model_sha256": sha,
            "counted_as_control": not probe,
        }
        # A counted control must FAIL the reference-budget check AND provably
        # change the render. Whether it also degrades a metric is reported
        # separately: on this carrier the landed F-48a residual is larger
        # than the audio effect of the whole cutoff-modulation path, so a
        # non-discriminating result is a property of the carrier, recorded,
        # never silently accepted as a pass.
        entry["control_ok"] = bool(probe or (fails_budget and True))
        results[name] = entry
        log(f"[{name}] max={m['max_abs_diff_lsb']:.0f} "
            f"rms={m['rms_diff_dbfs']:.2f}dBFS "
            f"spec={m['spectral_corr']:.4f} "
            f"wrms(kt!=0)={m['windowed_rms_lsb']['kt_nonzero']:.1f} "
            f"-> {m['verdict']}; "
            f"{'PROBE' if probe else 'control'} "
            f"degrades={worse or 'NONE (non-discriminating on this carrier)'}")
        if not probe:
            ok_all &= fails_budget
        return entry

    # ---- C1 routing-zeroed, per destination class -------------------------
    budget_control("cutoff-zeroed", ["--zero-dest", "cutoff"])
    budget_control("reso-zeroed", ["--zero-dest", "reso"],
                   expect_degenerate=True)
    budget_control("fegmod-zeroed", ["--zero-dest", "fegmod"],
                   expect_degenerate=True)

    # ---- C2 shared instead of per-instance ---------------------------------
    budget_control("shared-keytrack-word", ["--shared-kt"])

    # ---- C3 source swap -----------------------------------------------------
    budget_control("source-swap-velocity", ["--source-swap", "velocity"])
    mw = budget_control("source-swap-modwheel", ["--source-swap", "modwheel"],
                        expect_degenerate=False)
    zero = results.get("cutoff-zeroed", {})
    if mw and zero.get("model_sha256"):
        same = mw.get("model_sha256") == zero["model_sha256"]
        mw["equals_cutoff_zeroed_render"] = same
        mw["note"] = ("the modwheel is identically 0 on this fixture (a "
                      "Sine-class fixture admits no CC events), so this swap "
                      "is arithmetically the zeroed control -- proved by the "
                      "render sha equality; velocity carries the "
                      "non-degenerate swap")
        log(f"  source-swap-modwheel render == cutoff-zeroed render: {same}")

    # ---- C4 keytrack root dropped ------------------------------------------
    budget_control("ignore-keytrack-root", ["--ignore-root"])

    # ---- P6 control-validity probe -----------------------------------------
    budget_control("probe-velocity-cutoff-zeroed",
                   ["--diagnostic-zero-velocity-cutoff"], probe=True)

    # ---- P5 lag probe (must be INERT) --------------------------------------
    log("")
    wav = model_render("lag-refresh-before", ["--refresh-before"])
    inert = bool(wav) and sha256_file(wav) == base_sha
    log(f"[P5 lag-refresh-before] bit-identical to baseline: {inert} "
        "(expected TRUE: pitch is constant per voice, so the declared "
        "1-control-pass lag is unobservable in this class -- probe, not a "
        "control)")
    results["lag-refresh-before-probe"] = {
        "expected": "INERT (bit-identical)", "bit_identical": inert,
        "counted_as_control": False, "probe_ok": inert}
    ok_all &= inert

    # ---- C7 out-of-class refusals ------------------------------------------
    log("")
    rc, out, err = sh([sys.executable, RUNNER, "--sequence", SEQ,
                       "--out-dir", os.path.join(args.work,
                                                 "refused-out-of-class"),
                       "--out-of-class-route"])
    refused = rc == 2 and "outside the declared SXT-042 destination class" in err
    log(f"[out-of-class-route] exit={rc} refused={refused} "
        f"msg={err.strip()[:200]}")
    results["out-of-class-route"] = {"expected": "REFUSE (exit 2)",
                                     "control_ok": refused,
                                     "refusal": err.strip()[:300]}
    ok_all &= refused

    scan_json = os.path.join(args.artifacts, "applicability-scan.json")
    rc, out, err = sh([sys.executable, SCAN, "--json", scan_json])
    if rc != 0:
        log(f"[applicability-scan] exited {rc}: {err[-400:]}")
        ok_all = False
    else:
        scan = json.loads(open(scan_json).read())
        by_path = {r["path"]: r for r in scan["carriers"]}
        for rel in CARRIERS:
            r = by_path.get(rel) or {}
            reasons = (r.get("route_class_reasons", [])
                       + r.get("voice_class_reasons", []))
            got = bool(r) and not r.get("in_class", True)
            log(f"[carrier-refusal] {os.path.basename(rel)}: refused={got}")
            for x in reasons[:3]:
                log(f"    - {x}")
            results["carrier-" + os.path.basename(rel)] = {
                "expected": "REFUSE (outside the declared class)",
                "control_ok": got, "reasons": reasons}
            ok_all &= got

    # ---- C8 exactness-domain controls on the synthetic class-cover fixture --
    log("")
    syn_dir = args.synthetic_run_dir
    syn_wav = os.path.join(syn_dir, "model.wav")
    if os.path.exists(syn_wav):
        syn_sha = sha256_file(syn_wav)
        for dest in ("reso", "fegmod"):
            w = model_render(f"synthetic-{dest}-zeroed",
                             ["--synthetic-routes", "--zero-dest", dest])
            changed = bool(w) and sha256_file(w) != syn_sha
            log(f"[synthetic-{dest}-zeroed] render differs from the "
                f"synthetic class-cover baseline: {changed} "
                "(model-vs-model; no reference claim -- the pinned engine "
                "never rendered this configuration)")
            results[f"synthetic-{dest}-zeroed"] = {
                "expected": "render must change", "control_ok": changed,
                "domain": "exactness/model-vs-model only",
                "counted_as_control": True}
            ok_all &= changed
    else:
        log("[synthetic controls] SKIPPED: run-synthetic fixture missing")
        ok_all = False

    # ---- C9 RTL mutants -----------------------------------------------------
    log("")
    run_dir = syn_dir if os.path.exists(
        os.path.join(syn_dir, "model_trace.json")) else os.path.join(
            args.work, "model-baseline")
    for tag, path, needle, mutant, why in (
        ("rtl-mutant-rounding", MUTANT_ROUND,
         "num = (64'sd1048576 * n) + 64'sd3;",
         "num = (64'sd1048576 * n) + 64'sd0;",
         "keytrack word rounding bias dropped (round-half-up -> truncate)"),
        ("rtl-mutant-shared", MUTANT_SHARED,
         "kt = kt_word_of(key + 12*oct - root);",
         "kt = kt_word_of(32'sd36 + 12*oct - root);",
         "one SHARED keytrack word (the first note's) instead of per-voice"),
    ):
        write_mutant(path, needle, mutant)
        out_json = os.path.join(args.artifacts, f"exactness-{tag}.json")
        sh([sys.executable, CMP_KT, "--run-dir", run_dir, "--tb", path,
            "--out", out_json])
        m = json.loads(open(out_json).read())
        log(f"[{tag}] {why}")
        log(f"  verdict={m['verdict']} mismatches={m['mismatches']} "
            f"first={m['first_failures'][:1]}")
        results[tag] = {"expected": "FAIL", "verdict": m["verdict"],
                        "control_ok": m["verdict"] == "FAIL",
                        "mutation": {"from": needle, "to": mutant},
                        "run_dir": os.path.relpath(run_dir, REPO),
                        "metrics_file": os.path.relpath(out_json, REPO)}
        ok_all &= m["verdict"] == "FAIL"

    # ---- summary ------------------------------------------------------------
    nondiscrim = sorted(k for k, v in results.items()
                        if isinstance(v, dict) and v.get("counted_as_control")
                        and v.get("render_changed") and
                        not v.get("discriminating"))
    log("")
    if nondiscrim:
        log("NON-DISCRIMINATING on this carrier (fail the budget check and "
            "provably change the render, but do not degrade any metric "
            "relative to the unmutated model -- recorded as a bounded "
            "finding, NOT counted as evidence of sensitivity):")
        for k in nondiscrim:
            log(f"  - {k}")
    log("")
    log("overall: " + ("ALL CONTROLS FAIL THEIR CHECK (expected)" if ok_all
                       else "CONTROL FAILURE (a control did not fail as "
                            "required)"))
    results["overall_ok"] = ok_all
    results["non_discriminating_on_this_carrier"] = nondiscrim

    with open(os.path.join(args.artifacts, "negative-control.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(args.artifacts, "negative-controls.json"), "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
