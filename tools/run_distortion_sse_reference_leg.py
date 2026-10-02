#!/usr/bin/env python3
"""SXT-028e-sse (#136): drive the whole model-vs-pinned-engine reference leg.

One entry point so the leg is reproducible as a single command and so the
negative controls cannot be quietly skipped: every control below is run, its
verdict is read back, and `reference-leg.json`'s `controls_ok` is False unless
each one FAILED the comparison exactly as required.

Legs produced
=============
`primary`    one comparison per declared synthetic carrier x sequence, on the
             unmodified `original` wet bus. These are the achieved max/rms/corr
             numbers the issue's acceptance asks for. RECORDED, NOT TUNED.
`bypass`     per-slot bypass comparisons (model 3): each reference bus with
             exactly one Distortion slot Off, compared against the model with
             the same slot removed. The unmodified `original` wet reference is
             untouched by these legs.
`controls`   the live negative controls, each of which MUST FAIL:
               NC-A       a generic single-rate tanh substitute
               NC-A2      the SIBLING leaf's `lookup_waveshape` table shaper
                          substituted for `GetQuadWaveshaper`
               NC-SHARED  ONE shared effect instance in place of the two
                          per-instance ones (shared instead of per-instance
                          state)
               NC-B       the declared tail region dropped (zeroed)
               NC-C       the WRONG settle boundary: the fixture's 0.25 s
                          synth settle run through the effect as well, so
                          the model's lipol/coefficient ramps are
                          pre-converged where the engine's are not
                          (model/effects/run_distortion_sse_model.py,
                          `artifacts/settle-boundary.json`)
             If NC-A2 PASSES, this leg is measuring the wrong thing and the
             run is reported as such instead of being published.

Original tool, Apache-2.0.
"""

import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import distortion_sse_synthetic as syn  # noqa: E402

ART = os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts")
FIX = os.path.join(REPO, "reports", "SXT-028e-sse", "fixtures")
RUNNER = os.path.join(REPO, "model", "effects", "run_distortion_sse_model.py")
COMPARER = os.path.join(REPO, "tools", "compare_distortion_sse_reference.py")
PY = sys.executable

# Controls are graded on FX model 5 (`OJD`), the same bed the committed
# model-side controls use (tools/distortion_sse_negative_controls.py).
CONTROL_SLUG = "syn-m5"
CONTROL_SEQ = "seq-poly-8-v1"
BYPASS_SLUG = "syn-m3"
BYPASS_SEQ = "seq-poly-8-v1"


def sh(cmd):
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr, time.time() - t0


REUSE_MODEL = False      # --reuse-model: re-grade existing renders in place


def run_model(slug, seq, out_name, leg="original", substitute=None,
              share_state=False, drop_tail_blocks=0, silent_preroll_blocks=0):
    path0 = os.path.join(ART, out_name)
    if REUSE_MODEL and os.path.exists(path0):
        return path0, None
    cmd = [PY, RUNNER, "--slug", slug, "--seq", seq, "--leg", leg,
           "--out-name", out_name]
    if substitute:
        cmd += ["--substitute", substitute]
    if share_state:
        cmd += ["--share-state"]
    if drop_tail_blocks:
        cmd += ["--drop-tail-blocks", str(drop_tail_blocks)]
    if silent_preroll_blocks:
        cmd += ["--silent-preroll-blocks", str(silent_preroll_blocks)]
    rc, out, err, dt = sh(cmd)
    if rc != 0:
        return None, f"model run rc={rc}: {err.strip()[:400]}"
    return os.path.join(ART, out_name), None


def run_compare(slug, seq, model_wav, bus, json_name, label=None):
    cmd = [PY, COMPARER, "--slug", slug, "--seq", seq, "--bus", bus,
           "--model", model_wav, "--json", os.path.join(ART, json_name)]
    if label:
        cmd += ["--label", label]
    rc, out, err, dt = sh(cmd)
    path = os.path.join(ART, json_name)
    if not os.path.exists(path):
        return None, f"compare rc={rc}: {err.strip()[:400]}"
    return json.load(open(path)), None


def syn_preroll():
    """The fixture's own synth-settle length, read from the runner."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("rdsm", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return int(mod.FIXTURE_SETTLE_BLOCKS)


def declared_tail_blocks(slug, seq):
    sc = json.load(open(os.path.join(FIX, f"{slug}__{seq}.json")))
    return int(round(float(sc["render"]["tail_s"]) * sc["render"]["sample_rate"]
                     / sc["render"]["block_size"]))


def summarize(rec):
    m = rec["channels"]["mono"]
    return {
        "max_abs_diff_lsb": m["max_abs_diff_lsb"],
        "rms_diff_dbfs": m["rms_diff_dbfs"],
        "spectral_corr": m["spectral_corr"],
        "best_shift": m["best_shift"],
        "tail_rms_rel_db": rec["tail_check"]["tail_rms_rel_db"],
        "tail_gate_ok": rec["tail_gate_ok"],
        "budget_results": rec["proposed_budget_results"],
        "verdict": rec["verdict"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=("primary", "bypass", "controls"),
                    action="append")
    ap.add_argument("--carriers", help="comma-separated carrier subset")
    ap.add_argument("--reuse-model", action="store_true",
                    help="re-grade the model renders already in the artifact "
                         "directory instead of regenerating them. The model "
                         "runner is deterministic, so this only saves time; "
                         "the default regenerates everything.")
    ap.add_argument("--out", default=os.path.join(ART, "reference-leg.json"))
    args = ap.parse_args()
    global REUSE_MODEL
    REUSE_MODEL = bool(args.reuse_model)
    which = set(args.only or ("primary", "bypass", "controls"))
    carriers = (args.carriers.split(",") if args.carriers
                else sorted(syn.CARRIERS))

    result = {
        "leaf": "SXT-028e-sse",
        "issue": "#136 (SXT-028e-sse follow-up): oracle-host reference leg",
        "claim": "claim (2) model-vs-pinned-engine agreement only. Not claim "
                 "(1) RTL-vs-frozen-model (separate, exact, #121) and not "
                 "claim (3) the instrument sounds good (no listening record).",
        "carrier_kind": "DECLARED-SYNTHETIC for every row below; the three "
                        "corpus carriers are NOT_RUN with measured reasons in "
                        "artifacts/render-refusals.txt",
        "budgets": "the [PROPOSED] SXT-023 effect-slice values, imported from "
                   "tools/compare_chorus_reference.py; nothing is frozen here "
                   "and nothing was relaxed",
        "settle_boundary": "the fixture's 0.25 s synth settle is NOT run "
                           "through the effect; measured, not assumed "
                           "(artifacts/settle-boundary.json) and held in "
                           "place by control NC-C",
        "primary": {},
        "bypass": {},
        "controls": {},
        "not_run": [],
    }

    if "primary" in which:
        for slug in carriers:
            for seq in syn.SEQUENCES_FOR[slug]:
                key = f"{slug}__{seq}"
                wav, why = run_model(slug, seq, f"model__{key}.f32.wav")
                if why:
                    result["not_run"].append({"leg": "primary", "id": key,
                                              "reason": why})
                    print("NOT_RUN primary", key, why, file=sys.stderr)
                    continue
                rec, why = run_compare(slug, seq, wav, "original",
                                       f"compare-{key}.json")
                if why:
                    result["not_run"].append({"leg": "primary", "id": key,
                                              "reason": why})
                    print("NOT_RUN primary", key, why, file=sys.stderr)
                    continue
                result["primary"][key] = dict(
                    summarize(rec), fx_model_index=rec["fx_model_index"],
                    quad_waveshaper=rec["quad_waveshaper"])
                print("primary", key, result["primary"][key]["verdict"][:60])

    if "bypass" in which:
        slug, seq = BYPASS_SLUG, BYPASS_SEQ
        for leg in syn.carrier_legs(slug):
            if not leg.startswith("bypass-fx"):
                continue
            key = f"{slug}__{seq}-{leg}"
            wav, why = run_model(slug, seq, f"model__{key}.f32.wav", leg=leg)
            if why:
                result["not_run"].append({"leg": "bypass", "id": key,
                                          "reason": why})
                continue
            rec, why = run_compare(slug, seq, wav, leg, f"compare-{key}.json",
                                   label=f"per-slot bypass leg {leg}")
            if why:
                result["not_run"].append({"leg": "bypass", "id": key,
                                          "reason": why})
                continue
            result["bypass"][key] = summarize(rec)
            print("bypass", key, result["bypass"][key]["verdict"][:60])

    if "controls" in which:
        slug, seq = CONTROL_SLUG, CONTROL_SEQ
        tail_blocks = declared_tail_blocks(slug, seq)
        specs = [
            ("NC-A", dict(substitute="nc-a"),
             "a generic single-rate tanh substitute (no oversampling, no "
             "halfband, no pre/post EQ, no feedback, no quad-waveshaper "
             "state) in place of the frozen chain",
             "budget"),
            ("NC-A2", dict(substitute="nc-a2"),
             "the SXT-028e (#57) `lookup_waveshape` table shaper substituted "
             "for `GetQuadWaveshaper`, chain otherwise untouched",
             "budget"),
            ("NC-SHARED", dict(share_state=True),
             "ONE shared effect instance driving both the ains1 and the send1 "
             "slot (shared instead of per-instance state)",
             "budget"),
            ("NC-B", dict(drop_tail_blocks=tail_blocks),
             f"the whole declared tail region ({tail_blocks} blocks) dropped "
             "(zeroed) from the model render",
             "tail"),
            ("NC-C", dict(silent_preroll_blocks=syn_preroll()),
             f"the WRONG settle boundary: the fixture's {syn_preroll()}-block "
             "synth settle also run through the effect, pre-converging the "
             "lipol and coefficient ramps the engine has not started yet",
             "budget"),
        ]
        for cid, kwargs, what, gate in specs:
            key = f"{slug}__{seq}-{cid}"
            wav, why = run_model(slug, seq, f"model__{key}.f32.wav", **kwargs)
            if why:
                result["controls"][cid] = {"status": "NOT_RUN", "reason": why,
                                           "what": what}
                print("NOT_RUN control", cid, why, file=sys.stderr)
                continue
            rec, why = run_compare(slug, seq, wav, "original",
                                   f"compare-{key}.json", label=f"{cid}: {what}")
            if why:
                result["controls"][cid] = {"status": "NOT_RUN", "reason": why,
                                           "what": what}
                continue
            s = summarize(rec)
            failed = s["verdict"].startswith("FAIL")
            tail_failed = not s["tail_gate_ok"]
            ok = tail_failed if gate == "tail" else failed
            result["controls"][cid] = dict(
                s, what=what, must="FAIL", gate=gate, ok=bool(ok),
                status="CONTROL-OK" if ok else "CONTROL-BROKEN")
            print("control", cid, result["controls"][cid]["status"],
                  s["verdict"][:60])

    ran = [c for c in result["controls"].values()
           if c.get("status") != "NOT_RUN"]
    result["controls_ok"] = bool(ran) and all(c["ok"] for c in ran)
    if "controls" in which and not result["controls_ok"]:
        result["warning"] = (
            "AT LEAST ONE NEGATIVE CONTROL DID NOT FAIL AS REQUIRED. This leg "
            "is measuring the wrong thing; its primary numbers must not be "
            "published as agreement until the control is fixed.")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"\nwrote {os.path.relpath(args.out, REPO)}: "
          f"{len(result['primary'])} primary, {len(result['bypass'])} bypass, "
          f"{len(result['controls'])} controls, controls_ok="
          f"{result['controls_ok']}, {len(result['not_run'])} NOT_RUN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
