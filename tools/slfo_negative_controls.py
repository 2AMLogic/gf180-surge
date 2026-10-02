#!/usr/bin/env python3
"""SXT-041 negative controls: each control must DEMONSTRABLY FAIL the check it
targets; a control the chosen metric provably cannot see is reported as
NON-DISCRIMINATING (and carried in the exactness domain instead) rather than
counted as a pass. Patterns: reports/sxt-022/artifacts/negative-control.txt,
tools/lfo_negative_controls.py, tools/kt_negative_controls.py.

Carrier: the declared synthetic SLFO fixture on `Basses/Attacky.fxp`
(`model/voice/attacky_slfo_inputs.json`). References are the committed
pinned-engine DRY renders, retained UNMODIFIED (AGENTS.md bypass rule) —
only the model / the RTL is mutated.

Reference-domain controls (must FAIL the reference-budget check)
  C1 routing-zeroed, PER DESTINATION CLASS — scene-LFO -> Filter 1 Cutoff
     depth forced to 0, and separately -> Filter 1 Resonance (issue #75
     acceptance, first required control).
  C2 source-swap — the landed modwheel bound in place of the scene LFO at
     the same depths, on the modwheel staircase sequence (issue #75
     acceptance, second required control).
  C3 per-note retrigger — the scene LFOs attacked/released on EVERY
     note-on/note-off (voice-LFO semantics applied to a scene LFO). This is
     the control that discriminates this leaf's headline claim S2/S3: the
     pinned engine gates on `getNonReleasedVoices(scene) == 0`.
  C4 gated process — the scene LFOs advanced only while a gated voice
     exists (voice-LFO residency applied to a scene LFO; S5).

Control-plane / exactness-domain controls
  C5 zero-delay route — the scene route applied from the CURRENT block's
     output instead of the previous block's (S4). One engine block is
     0.67 ms, so on a 1 Hz scene LFO the AUDIO metric cannot discriminate
     it; that is measured and recorded here, and the control is carried by
     the control-plane trace diff plus the RTL mutant below.
  C6 shared-instead-of-per-instance — all six instances collapsed onto one
     shared state set (S1; AGENTS.md shared-state control).
  C7 RTL mutants, all of which must FAIL integer equality:
       slfo_broken_mutant.sv   output round-half-up bias off by one shift
       slfo_nodelay_mutant.sv  the one-block route latch dropped (S4)
       slfo_shared_mutant.sv   one shared state set for all six (S1)

Probes (NOT controls — they are allowed, and expected, to come back clean)
  P8 settle replay — skipping the reference renderer's 375 settle blocks.
     With the fixture's keytrigger trigmode the first attack restarts the
     phase and the EG is `lfoeg_stuck` until then, so the settle is
     PROVABLY a no-op on this fixture; a non-degenerate result here would
     mean the frozen settle replay is doing something it should not.

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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_slfo.sv")
RUNNER = os.path.join(REPO, "model", "voice", "run_slfo_model.py")
CMP_AUDIO = os.path.join(REPO, "tools", "compare_audio_reference.py")
CMP_SLFO = os.path.join(REPO, "tools", "compare_slfo_rtl_model.py")

SEQ_OVERLAP = "sxt041-slfo-overlap-v1"
SEQ_RETRIG = "seq-notes-repeated-v1"
SEQ_MODWHEEL = "seq-modwheel-v1"
REF_TAG = "slfo-fixture"

# (name, anchor, replacement) for each RTL mutant generated from tb_slfo.sv.
RTL_MUTANTS = (
    (
        "slfo_broken_mutant.sv",
        "output round-half-up bias off by one shift",
        (("32'sd1 <<< (F_WAVE - FQ - 1)", "32'sd1 <<< (F_WAVE - FQ - 2)"),),
    ),
    (
        "slfo_nodelay_mutant.sv",
        "the one-block scene-route latch dropped: the six instances are "
        "advanced BEFORE modulation_scene is applied, so the route consumes "
        "the current block's output",
        (
            ("      cut_sum = 0; reso_sum = 0;\n",
             "      advance_all();   // MUTANT: advance before the apply\n"
             "      cut_sum = 0; reso_sum = 0;\n"),
            ("      // 3. the unconditional six-instance advance, then "
             "re-latch\n      advance_all();\n",
             "      // 3. MUTANT: the advance was hoisted above the apply\n"),
        ),
    ),
    (
        "slfo_shared_mutant.sv",
        "one shared state set for all six instances (per-instance scene-LFO "
        "state merged)",
        (
            ("    for (i = 0; i < NSLFO; i++) route_out[i] = output21[i];\n",
             "    for (i = 1; i < NSLFO; i++) begin   // MUTANT: shared state\n"
             "      phase[i] = phase[0]; eg_state[i] = eg_state[0];\n"
             "      env_ph[i] = env_ph[0]; env_val[i] = env_val[0];\n"
             "      output21[i] = output21[0];\n"
             "    end\n"
             "    for (i = 0; i < NSLFO; i++) route_out[i] = output21[i];\n"),
        ),
    ),
)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_mutant(name, mutations, out_dir):
    src = open(TB, encoding="utf-8").read()
    out = src
    for anchor, repl in mutations:
        if out.count(anchor) != 1:
            raise RuntimeError(f"{name}: anchor {anchor!r} occurs "
                               f"{out.count(anchor)} times in tb_slfo.sv "
                               "(expected exactly 1)")
        out = out.replace(anchor, repl)
    if out == src:
        raise RuntimeError(f"{name}: mutation produced an identical file")
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return path


def control_plane_diff(frozen_trace, mutant_trace):
    """Quantified control-plane divergence between two model traces.

    Reports how many blocks differ and the largest absolute difference, for
    the two control-plane signals this leaf freezes: the once-per-block scene
    route sums and the six per-instance outputs. This is what makes a control
    that the AUDIO metric cannot see still demonstrably a real change.
    """
    with open(frozen_trace) as f:
        a = json.load(f)
    with open(mutant_trace) as f:
        b = json.load(f)
    blocks = min(len(a["blocks"]), len(b["blocks"]))
    sum_blocks = 0
    sum_max = 0
    out_blocks = 0
    out_max = 0
    first = None
    for i in range(blocks):
        ba, bb = a["blocks"][i], b["blocks"][i]
        da = [abs(x - y) for x, y in zip(ba["slfo_route_sums"],
                                         bb["slfo_route_sums"])]
        if any(da):
            sum_blocks += 1
            sum_max = max(sum_max, max(da))
            if first is None:
                first = {"block": ba["b"],
                         "frozen_route_sums": ba["slfo_route_sums"],
                         "mutant_route_sums": bb["slfo_route_sums"]}
        oa = [abs(x["output"] - y["output"])
              for x, y in zip(ba["slfo"], bb["slfo"])]
        if any(oa):
            out_blocks += 1
            out_max = max(out_max, max(oa))
    return {
        "blocks_compared": blocks,
        "route_sum_blocks_differing": sum_blocks,
        "route_sum_max_abs_delta_q21": sum_max,
        "instance_output_blocks_differing": out_blocks,
        "instance_output_max_abs_delta_q21": out_max,
        "discriminating": bool(sum_blocks or out_blocks),
        "first_differing_block": first,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--reference-dir", required=True,
                    help=f"dir with reference-<seq>-{REF_TAG}.wav")
    args = ap.parse_args()

    art = args.artifacts
    os.makedirs(art, exist_ok=True)
    lines = []
    results = {}
    ok_all = True

    def log(s=""):
        lines.append(s)
        print(s)

    def ref_wav(seq):
        return os.path.join(args.reference_dir,
                            f"reference-{seq}-{REF_TAG}.wav")

    def model_render(tag, seq, extra):
        out_dir = os.path.join(art, f"model-{tag}")
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        rc, out, err = sh([sys.executable, RUNNER, "--sequence", seq,
                           "--out-dir", out_dir] + extra)
        if rc != 0:
            log(f"[{tag}] model runner exited {rc}: {err[-2000:]}")
            return None
        return out_dir

    def metrics(name, seq, model_wav):
        out_json = os.path.join(art, f"audio-nc-{name}.json")
        rc, out, err = sh([sys.executable, CMP_AUDIO, "--ref", ref_wav(seq),
                           "--model", model_wav, "--json", out_json])
        if rc not in (0, 1):
            log(f"[{name}] comparator exited {rc}: {err}")
            return None
        with open(out_json) as f:
            return json.load(f), os.path.relpath(out_json, REPO)

    # ---- frozen baselines (not controls; the yardstick for the controls) --
    baselines = {}
    for seq in (SEQ_OVERLAP, SEQ_RETRIG, SEQ_MODWHEEL):
        d = model_render(f"baseline-{seq}", seq, [])
        if d is None:
            return 1
        got = metrics(f"baseline-{seq}", seq, os.path.join(d, "model.wav"))
        if got is None:
            return 1
        m, _ = got
        baselines[seq] = {"dir": d, "metrics": m,
                          "sha256": sha256_file(os.path.join(d, "model.wav"))}

    log("SXT-041 negative controls — scene-LFO (ms_slfo1..6) slice")
    log("date: " + datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"))
    log("engine pin: surge-synthesizer/surge@"
        "58914e59c608ed4384ba6002e44c3465c58b2e71 (48 kHz, block 32)")
    log("")
    log("FROZEN-MODEL baselines (the yardstick; they FAIL the [PROPOSED] "
        "max/rms budgets themselves — same error class as SXT-022/SXT-032 — "
        "so every control is also reported against these numbers, never "
        "against a 'pass' the model does not have):")
    for seq, bl in baselines.items():
        m = bl["metrics"]
        log(f"  {seq}: max={m['max_abs_diff_lsb']:.0f} "
            f"rms={m['rms_diff_dbfs']:.3f}dBFS "
            f"spec={m['spectral_corr']:.4f} -> {m['verdict']}")
    log("")

    def audio_control(name, seq, extra, counted=True, expect_degenerate=False):
        nonlocal ok_all
        d = model_render(name, seq, extra)
        if d is None:
            ok_all = False
            results[name] = {"control_ok": False, "why": "runner failed"}
            return None
        wav = os.path.join(d, "model.wav")
        sha = sha256_file(wav)
        base = baselines[seq]
        changed = sha != base["sha256"]
        got = metrics(name, seq, wav)
        if got is None:
            ok_all = False
            results[name] = {"control_ok": False, "why": "comparator failed"}
            return None
        m, mfile = got
        bm = base["metrics"]
        worse = [w for w, c in (
            ("max", m["max_abs_diff_lsb"] > bm["max_abs_diff_lsb"]),
            ("rms", m["rms_diff_lsb"] > bm["rms_diff_lsb"]),
            ("spectral", m["spectral_corr"] < bm["spectral_corr"])) if c]
        fails_budget = m["verdict"].startswith("FAIL")
        cp = None
        if changed:
            cp = control_plane_diff(
                os.path.join(base["dir"], "model_trace.json"),
                os.path.join(d, "model_trace.json"))
        entry = {
            "sequence": seq,
            "runner_flags": extra,
            "expected": "DEGENERATE (probe)" if expect_degenerate
                        else ("FAIL" if counted else "FAIL (uncounted)"),
            "verdict": m["verdict"],
            "fails_reference_budget": fails_budget,
            "render_changed": changed,
            "model_sha256": sha,
            "max_abs_diff_lsb": m["max_abs_diff_lsb"],
            "rms_diff_dbfs": m["rms_diff_dbfs"],
            "spectral_corr": m["spectral_corr"],
            "baseline_max_abs_diff_lsb": bm["max_abs_diff_lsb"],
            "baseline_rms_diff_dbfs": bm["rms_diff_dbfs"],
            "baseline_spectral_corr": bm["spectral_corr"],
            "degrades_vs_frozen_model": worse,
            "audio_discriminating": bool(worse),
            "control_plane_diff": cp,
            "counted_as_control": bool(counted and not expect_degenerate),
            "metrics_file": mfile,
        }
        if expect_degenerate:
            entry["control_ok"] = not changed
            log(f"[{name}] render {'CHANGED' if changed else 'BIT-IDENTICAL'} "
                f"-> {'PROBE OK (provably a no-op)' if not changed else 'PROBE FAILED'}")
            if changed:
                ok_all = False
        else:
            entry["control_ok"] = bool(fails_budget and changed)
            log(f"[{name}] max={m['max_abs_diff_lsb']:.0f} "
                f"(base {bm['max_abs_diff_lsb']:.0f}) "
                f"rms={m['rms_diff_dbfs']:.3f} (base {bm['rms_diff_dbfs']:.3f}) "
                f"spec={m['spectral_corr']:.4f} (base {bm['spectral_corr']:.4f}) "
                f"-> {m['verdict']}; changed={changed}; "
                f"degrades={worse or 'NONE (audio-NON-DISCRIMINATING on this '
                                     'carrier)'}")
            if cp:
                log(f"    control-plane: route-sum blocks differing="
                    f"{cp['route_sum_blocks_differing']}/"
                    f"{cp['blocks_compared']} max|delta|="
                    f"{cp['route_sum_max_abs_delta_q21']} Q10.21; "
                    f"instance-output blocks differing="
                    f"{cp['instance_output_blocks_differing']} max|delta|="
                    f"{cp['instance_output_max_abs_delta_q21']}")
            if counted:
                ok_all &= entry["control_ok"]
        results[name] = entry
        return entry

    # ---- C1 routing-zeroed, per destination class -------------------------
    log("C1 routing-zeroed, per destination class (required control)")
    audio_control("cutoff-zeroed", SEQ_OVERLAP, ["--zero-dest", "cutoff"])
    audio_control("reso-zeroed", SEQ_OVERLAP, ["--zero-dest", "reso"])
    audio_control("all-routes-zeroed", SEQ_OVERLAP, ["--zero-routes"])
    log("")

    # ---- C2 source swap ----------------------------------------------------
    log("C2 source-swap: the landed modwheel in place of the scene LFO "
        "(required control)")
    audio_control("source-swap", SEQ_MODWHEEL, ["--source-swap"])
    log("")

    # ---- C3 per-note retrigger (the scene-scope gate) ----------------------
    log("C3 per-note retrigger: voice-LFO attack/release semantics applied "
        "to a scene LFO (discriminates this leaf's headline S2/S3 claim)")
    audio_control("per-note-retrigger", SEQ_OVERLAP, ["--per-note-retrigger"])
    log("")

    # ---- C4 gated process --------------------------------------------------
    log("C4 gated process: the scene LFOs advanced only while a gated voice "
        "exists (S5)")
    audio_control("gated-process", SEQ_OVERLAP, ["--gated-process"])
    log("")

    # ---- C5/C6 control-plane-carried controls ------------------------------
    log("C5 zero-delay route (S4) and C6 shared-instance (S1): reported in "
        "the audio domain AND carried in the control-plane / exactness "
        "domain, because one engine block is 0.67 ms and the audio metric "
        "may not see it")
    audio_control("zero-delay-route", SEQ_OVERLAP, ["--zero-delay-route"],
                  counted=False)
    audio_control("shared-instance", SEQ_OVERLAP, ["--shared-instance"],
                  counted=False)
    for nm in ("zero-delay-route", "shared-instance"):
        cp = results[nm].get("control_plane_diff") or {}
        okcp = bool(cp.get("discriminating"))
        results[nm]["control_plane_control_ok"] = okcp
        results[nm]["counted_as_control"] = True
        results[nm]["control_ok"] = okcp
        log(f"  [{nm}] control-plane control -> "
            f"{'FAILS the frozen control-plane trace (expected)' if okcp else 'NOT DISCRIMINATING (control failure)'}")
        ok_all &= okcp
    log("")

    # ---- P8 settle probe ---------------------------------------------------
    log("P8 settle-replay probe (NOT a control): the 375 settle blocks must "
        "be a provable no-op on a keytrigger fixture")
    audio_control("no-settle", SEQ_OVERLAP, ["--no-settle"],
                  expect_degenerate=True)
    log("")

    # ---- C7 RTL mutants ----------------------------------------------------
    log("C7 RTL mutants (must FAIL RTL-vs-model integer equality)")
    run_dir = baselines[SEQ_OVERLAP]["dir"]
    mutant_dir = os.path.join(art, "rtl-mutants")
    os.makedirs(mutant_dir, exist_ok=True)
    for name, why, mutations in RTL_MUTANTS:
        path = write_mutant(name, mutations, mutant_dir)
        out_json = os.path.join(art, f"exactness-mutant-{name}.json")
        rc, out, err = sh([sys.executable, CMP_SLFO, "--run-dir", run_dir,
                           "--tb", path, "--out", out_json])
        if not os.path.exists(out_json):
            log(f"[{name}] comparator produced no verdict: {err[-800:]}")
            ok_all = False
            results[name] = {"control_ok": False, "why": "no verdict"}
            continue
        with open(out_json) as f:
            m = json.load(f)
        okm = m["verdict"] == "FAIL" and m["comparison"] == "FAIL"
        log(f"[{name}] {why}")
        log(f"    verdict={m['verdict']} comparison={m['comparison']} "
            f"mismatches={m['mismatches']} first={m['first_failures'][:1]}")
        results[name] = {
            "expected": "FAIL",
            "verdict": m["verdict"],
            "comparison": m["comparison"],
            "mismatches": m["mismatches"],
            "first_failures": m["first_failures"][:3],
            "mutation": why,
            "mutant_file": os.path.relpath(path, REPO),
            "control_ok": okm,
            "counted_as_control": True,
            "metrics_file": os.path.relpath(out_json, REPO),
        }
        ok_all &= okm
    log("")

    counted = {k: v for k, v in results.items()
               if isinstance(v, dict) and v.get("counted_as_control")}
    nondiscrim = sorted(k for k, v in counted.items()
                        if v.get("audio_discriminating") is False)
    results["overall_ok"] = ok_all
    results["counted_controls"] = sorted(counted)
    results["audio_non_discriminating_on_this_carrier"] = nondiscrim
    results["claim_scope"] = (
        "Controls only. This transcript establishes that each listed "
        "mutation demonstrably fails the check it targets; it establishes no "
        "fidelity, preset-support or preset-quality claim, and the frozen "
        "model itself FAILS the [PROPOSED] max/rms budgets on every fixture "
        "(recorded, not tuned).")
    if ok_all:
        log("overall: ALL COUNTED CONTROLS DEMONSTRABLY FAIL (expected)")
    else:
        log("overall: CONTROL FAILURE (a control did not fail as required)")
    if nondiscrim:
        log("audio-non-discriminating on this carrier (carried in the "
            "control-plane/exactness domain): " + ", ".join(nondiscrim))

    with open(os.path.join(art, "negative-control.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(art, "negative-controls.json"), "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
