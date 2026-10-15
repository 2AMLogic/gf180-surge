#!/usr/bin/env python3
"""SXT-028f negative controls re-run against the REAL reference bundle.

tools/reverb2_negative_controls.py grades every control model-vs-model (the
frozen model is its own reference), which is enough to show the checks are
live but says nothing about the pinned engine. This file re-runs the two
controls that the issue's acceptance names against the committed
pinned-engine reference bundle (reports/SXT-028f/fixtures/), driven by the
SAME declared input boundary as the model render itself
(model/effects/run_reverb2_model.prepare).

  NC-REF-0  VACUITY / liveness. Grade the engine's own per-slot-bypass bus
            as if it were the model output. It MUST FAIL the budgets --
            otherwise the Reverb 2 contributes less than the budget on this
            carrier and the agreement PASS next to it would mean nothing.
  NC-A-REF  Generic substitute (ADAPTED): the same convenient generic
            reverb as the model-side NC-A (four feedback combs, no allpass
            diffusion, no damping, no predelay, no sub-sample read), fed the
            real input and graded against the real engine wet reference. It
            MUST FAIL the [PROPOSED] agreement budgets. If a generic passed
            here, the finding would be the budgets, not the leaf.
  NC-B-REF  Dropped tail: the committed model render truncated at the
            declared tail offset, and separately zeroed across the declared
            tail region, graded by the same declared-region stereo tail gate
            against the real reference. Both MUST FAIL the gate that the
            full model render passes.

Exits 0 iff every control fails the check it targets (and the liveness
predicates hold). CLAIM SCOPE: these controls show the reference-backed
checks are live and discriminating. They create no preset-support, coverage
or musical-quality claim.

Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-reverb 2"))

import compare_audio_reference as car  # noqa: E402
from compare_chorus_reference import (  # noqa: E402
    PROPOSED, PROPOSED_TAIL, channel_metrics, read_wav_stereo_f32,
)
from reverb2_model import ENGINE_PROFILE, MAX_DELAY_LEN, model_revision  # noqa: E402
from reverb2_negative_controls import GenericReverbSubstitute  # noqa: E402

import run_reverb2_model as rrm  # noqa: E402

LSB = 2.0 ** -21
FIXTURES = os.path.join(REPO, "reports", "SXT-028f", "fixtures")
ARTDIR = os.path.join(REPO, "reports", "SXT-028f", "artifacts")
NCDIR = os.path.join(REPO, "reports", "SXT-028f", "negative-controls")
CASES = [(slug, seq)
         for slug in ("tacobell", "moire1", "mystical")
         for seq in ("seq-notes-coverage-v1", "seq-poly-8-v1")]


def budgets(ref, cand):
    chs = {"L": channel_metrics(ref[0], cand[0]),
           "R": channel_metrics(ref[1], cand[1]),
           "mono": channel_metrics(0.5 * (ref[0] + ref[1]),
                                   0.5 * (cand[0] + cand[1]))}
    worst = chs["mono"]
    results = {
        "max_abs_diff_lsb": worst["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"] >= PROPOSED["spectral_corr_min"],
    }
    return {
        "max_abs_diff_lsb": worst["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"],
        "spectral_corr_definition": car.SPECTRAL_CORR_DEFINITION,
        "budget_results": results,
        "all_pass": all(results.values()),
    }


def tail(ref, cand, region, sidecar_rel):
    tc, tc_lr, ok, why = car.stereo_tail_gate(
        ref, cand, dict(region, sidecar=sidecar_rel), LSB)
    return {"mono": tc, "lr": tc_lr, "ok": bool(ok), "reason": why}


def run_case(slug, seq, fixtures_dir, art_dir):
    with open(os.path.join(REPO, "model", "effects", "fx_inputs",
                           f"type-reverb 2-{slug}.json")) as f:
        cfg = json.load(f)
    prep = rrm.prepare(slug, seq, cfg, fixtures_dir)
    sidecar = os.path.join(fixtures_dir, f"{slug}__{seq}.json")
    region = car.declared_tail_region(sidecar, "wet")
    sidecar_rel = os.path.relpath(sidecar, REPO)
    ref, _sr = read_wav_stereo_f32(
        os.path.join(REPO, prep["side"]["wet"]["wav"]))
    model, _sr2 = read_wav_stereo_f32(
        os.path.join(art_dir, f"model__{slug}__{seq}.f32.wav"))

    out = {"slug": slug, "sequence": seq,
           "reference_wet_sha256": prep["side"]["wet"]["sha256"],
           "controls": []}

    # ---- baseline: the frozen model itself must PASS both checks, or the
    # controls below are being compared against a broken baseline.
    base_b = budgets(ref, model)
    base_t = tail(ref, model, region, sidecar_rel)
    out["baseline_frozen_model"] = {"budgets": base_b, "tail": base_t,
                                    "ok": base_b["all_pass"] and base_t["ok"]}

    # ---- NC-REF-0 vacuity: the engine's own bypass bus as the candidate
    byp = prep["bypass"]
    vb = budgets(ref, byp)
    vt = tail(ref, byp, region, sidecar_rel)
    out["controls"].append({
        "control": "NC-REF-0 vacuity (engine per-slot-bypass bus graded as "
                   "the candidate)",
        "ok": not vb["all_pass"],
        "metrics": vb, "tail": vt,
        "verdict": ("CONTROL-OK (removing the Reverb 2 FAILS the agreement "
                    "budgets, so the budgets are resolving the Reverb 2's "
                    "own contribution on this carrier)"
                    if not vb["all_pass"] else
                    "CONTROL-BROKEN / VACUOUS (the Reverb 2 contributes less "
                    "than the budget here: an agreement PASS on this carrier "
                    "would mean nothing)"),
    })

    # ---- NC-A-REF generic substitute against the real reference
    sub = GenericReverbSubstitute(prep["inst"]["params"], "generic",
                                  profile=ENGINE_PROFILE,
                                  line_len=MAX_DELAY_LEN)
    gen, _clip = rrm.render_with(sub, prep)
    gb = budgets(ref, gen)
    gt = tail(ref, gen, region, sidecar_rel)
    out["controls"].append({
        "control": "NC-A-REF generic substitute (ADAPTED) vs the pinned "
                   "engine wet reference",
        "ok": not gb["all_pass"],
        "label": "ADAPTED -- excluded from original-preset coverage",
        "metrics": gb, "tail": gt,
        "verdict": ("CONTROL-OK (the generic substitute FAILS the [PROPOSED] "
                    "agreement budgets on real reference audio; ADAPTED != "
                    "supported)" if not gb["all_pass"] else
                    "CONTROL-BROKEN (a generic substitute passed against the "
                    "real reference: the finding is the budgets, not the "
                    "leaf)"),
    })

    # ---- NC-B-REF dropped tail against the real reference
    off, length = region["tail_offset"], region["tail_frames"]
    trunc = model[:, :off].copy()
    zeroed = model.copy()
    zeroed[:, off:off + length] = 0.0
    t_trunc = tail(ref, trunc, region, sidecar_rel)
    t_zero = tail(ref, zeroed, region, sidecar_rel)
    live = base_t["ok"] and bool(base_t["mono"].get("tail_present"))
    ok_b = live and (not t_trunc["ok"]) and (not t_zero["ok"])
    out["controls"].append({
        "control": "NC-B-REF dropped tail vs the pinned engine wet reference",
        "ok": ok_b, "live": live,
        "declared_region": {"tail_offset": off, "tail_frames": length,
                            "source": region.get("tail_region_source")},
        "baseline_full_tail": base_t, "truncated": t_trunc, "zeroed": t_zero,
        "verdict": ("CONTROL-OK (truncated and zeroed tails FAIL the "
                    "declared-region tail gate that the full model render "
                    "passes against the real reference)" if ok_b else
                    ("CONTROL-VACUOUS (the reference tail region carries no "
                     "energy)" if not live else
                     "CONTROL-BROKEN (a dropped tail passed the gate)")),
    })
    out["ok"] = (out["baseline_frozen_model"]["ok"]
                 and all(c["ok"] for c in out["controls"]))
    return out


def case_id(slug, seq):
    return f"{slug}__{seq}"


def select_cases(spec):
    """Resolve a --cases selector against the declared CASES.

    Returns (cases, None) or (None, diagnostic). None (flag omitted) means
    the full declared run. An empty, malformed (empty token, duplicate) or
    unknown selector is refused, including a valid+unknown mix: requested
    coverage that cannot execute must never become a zero-work PASS."""
    declared = [case_id(s, q) for s, q in CASES]
    if spec is None:
        return list(CASES), None
    tokens = spec.split(",")
    if any(t == "" for t in tokens):
        return None, (f"malformed --cases {spec!r}: empty selector token "
                      "(empty selection or stray comma)")
    dup = sorted({t for t in tokens if tokens.count(t) > 1})
    if dup:
        return None, f"malformed --cases {spec!r}: duplicate IDs {dup}"
    unknown = [t for t in tokens if t not in declared]
    if unknown:
        return None, (f"unknown --cases ID(s) {unknown}; declared: "
                      f"{declared}")
    return [(s, q) for s, q in CASES if case_id(s, q) in set(tokens)], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures-dir", default=FIXTURES)
    ap.add_argument("--art-dir", default=ARTDIR)
    ap.add_argument("--out", default=os.path.join(NCDIR,
                                                  "reference-controls.json"))
    ap.add_argument("--cases", help="comma-separated slug__seq subset")
    args = ap.parse_args()

    cases, err = select_cases(args.cases)
    if err:
        print("status: FAIL (NOT_RUN) -- " + err + "; requested coverage "
              "did not execute; no controls run and no report written "
              f"(any existing {args.out} is NOT output of this invocation)",
              file=sys.stderr)
        return 2
    declared_ids = [case_id(s, q) for s, q in CASES]
    requested_ids = (args.cases.split(",") if args.cases is not None
                     else declared_ids)
    rows = []
    for slug, seq in cases:
        row = run_case(slug, seq, args.fixtures_dir, args.art_dir)
        rows.append(row)
        for c in row["controls"]:
            print("%-4s %-10s %-24s %s"
                  % ("ok" if c["ok"] else "FAIL", slug, seq, c["verdict"]))
        sys.stdout.flush()

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028f",
        "follow_up": "F-028f-1 (#126)",
        "model_revision": model_revision(),
        "alloc_profile": ENGINE_PROFILE.name,
        "claim_scope": "model-vs-PINNED-ENGINE controls on the committed "
                       "reference bundle. They show the reference-backed "
                       "checks are live and discriminating; they create no "
                       "preset-support, coverage or musical-quality claim.",
        "proposed_budgets": PROPOSED,
        "proposed_tail_budget": dict(PROPOSED_TAIL),
        "coverage": {
            "declared_case_ids": declared_ids,
            "requested_case_ids": requested_ids,
            "executed_case_ids": [case_id(r["slug"], r["sequence"])
                                  for r in rows],
            "declared_count": len(declared_ids),
            "executed_count": len(rows),
            "scope": ("full" if len(rows) == len(declared_ids)
                      else "subset"),
            "note": "status grades agreement only on the executed cases; a "
                    "subset PASS is not full acceptance.",
        },
        "cases": rows,
        "status": "PASS" if all(r["ok"] for r in rows) else "FAIL",
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    cov = doc["coverage"]
    print("coverage: %s (%d/%d declared cases executed)"
          % (cov["scope"], cov["executed_count"], cov["declared_count"]))
    print("status:", doc["status"])
    return 0 if doc["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
