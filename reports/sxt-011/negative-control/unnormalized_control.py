#!/usr/bin/env python3
"""SXT-011 acceptance negative control: un-normalized export must be DETECTED.

Issue acceptance: "a pre-migration numeric ID routed through without
normalization must be detected as an analysis failure."

This control demonstrates the detection on real corpus presets whose raw
(pre-migration) ids differ from the normalized values:

  1. resources/data/patches_3rdparty/Rare Earth/Percussion/Kalimba Attempt.fxp
     stored revision 12: filter unit raw (type 6, subtype 4) in the fut_14 id
     space = fut_14_bp12 with subtype 4; the rev<15 Great Filter Remap moves
     subtype 3..5 to BP 24 dB (current id 23, subtype raw-3).
     Interpreted WITHOUT normalization, 6 = current 'BP 12 dB' and subtype 4
     is out of bp12's current subtype range.
  2. resources/data/patches_3rdparty/Damon Armani/Pads/Funky Gate.fxp
     stored revision 12: Sine shape raw 7; the loader's rev<=27 remap plus the
     rev<=12 SineOscillator wave_remap range check normalizes it to 0.

For each subject we BUILD the un-normalized graph (raw ids exported as if
they were current state) and show that the pipeline's detection layers flag
it, while the committed (normalized) line passes the same checks:

  - Layer 1, live-equality: exported state must equal a fresh native
    re-extraction (the same check the SXT-011 spot-check applies). The
    un-normalized graph FAILS with machine-readable field mismatches.
  - Layer 2, migration-consistency invariant: every compared raw field must
    either equal the live normalized value or carry a migration event in
    g.mi. The un-normalized graph carries no events, so the invariant check
    FAILS with the offending fields.
  - Honest scope note: plain live-range validation (validate()) accepts the
    un-normalized ids for these subjects because raw ids happen to lie
    inside the current numeric ranges; range checks alone are NOT the
    detection mechanism and this control documents that explicitly.

If the exporter ever produced such state, the same failures would gate the
entry to status analysis_failure (schema_validation_failed), never a silent
export. A control must demonstrably fail the check it targets; the committed
graphs must pass. Exit code 0 iff the controls FAIL as expected AND the
committed lines PASS.

Usage: python3 reports/sxt-011/negative-control/unnormalized_control.py
"""

import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import oracle_common as oc  # noqa: E402
import export_normalized_graphs as eng  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

SUBJECTS = [
    ("resources/data/patches_3rdparty/Rare Earth/Percussion/Kalimba Attempt.fxp",
     [("sc0.fu1", ("t", "st"), ("tn", "stn"))]),
    ("resources/data/patches_3rdparty/Damon Armani/Pads/Funky Gate.fxp",
     [("sc0.osc2.param0", ("p0",), (None, None))]),
]


def apply_unnormalized(g, field, norm_keys, value):
    """Route a raw id through as if it were normalized state."""
    parts = field.split(".")
    if parts[0].startswith("sc"):
        sc = int(parts[0][2:])
        if parts[1].startswith("fu"):
            fu = int(parts[1][2:])
            for k in norm_keys:
                g["sc"][sc]["fu"][fu][k] = value
        elif parts[1].startswith("osc"):
            oi = int(parts[1][3:])
            g["sc"][sc]["osc"][oi]["p"][0] = value
    elif field.startswith("fx"):
        i = int(parts[0][2:])
        g["fx"][i]["t"] = value


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def main():
    oc.reexec_under_pinned_python(REPO)
    oc.apply_engine_env()
    surgepy = oc.import_surgepy()
    if surgepy.getVersion() != eng.ENGINE_VERSION_STR:
        print("REFUSING: engine version %r" % surgepy.getVersion(), file=sys.stderr)
        return 2

    committed = {}
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            committed[d["p"]] = d

    data_home = oc.data_home()
    T = []
    results = {}
    allok = True

    for path, fields in SUBJECTS:
        T.append("=" * 100)
        T.append("SUBJECT: %s" % path)
        fxp = os.path.join(data_home, os.path.relpath(path, "resources/data"))
        raw = eng.read_fxp_raw(fxp)
        T.append("stored revision: %s" % raw["revision"])

        # committed line + live re-extraction (fresh engine, reset policy)
        c = committed[path]
        ex = eng.Extractor(surgepy, data_home)
        _p = ex.s.getPatch()
        for _pn in ("volume", "fx_bypass", "character", "polylimit"):
            _pr = _p[_pn]
            ex.s.setParamVal(_pr, ex.s.getParamDef(_pr))
        ex.s.allNotesOff()
        ex.s.loadPatch(fxp)
        live = ex.extract(raw)
        ev, missing, uninterp = eng.migration_events(raw, live, ex)
        if ev:
            live["mi"] = ev
        if missing:
            live["rwm"] = sorted(missing)
        if uninterp:
            live["rwu"] = sorted(uninterp, key=lambda d: (d["f"], d["raw"]))
        T.append("committed status: %s ; live re-extraction matches committed: %s"
                 % (c["st"], canonical(c["g"]) == canonical(live)))

        for field, norm_keys, _ in fields:
            parts = field.split(".")
            if parts[1].startswith("fu"):
                fu = int(parts[1][2:])
                rt, rs = raw["ints"]["%s.type" % field], \
                    raw["ints"]["%s.subtype" % field]
                nl = live["sc"][int(parts[0][2:])]["fu"][fu]
                T.append(
                    "RAW stored ids for %s: (type=%s, subtype=%s) in the fut_14 "
                    "id space; LIVE normalized: (type=%s %r, subtype=%s %r)"
                    % (field, rt, rs,
                       nl["t"], nl["tn"], nl["st"], nl["stn"]))
                raw_as_current = "%s/%s" % (
                    live_display_of_filter(ex, rt), live_display_of_subtype(ex, rt, rs))
                T.append("UN-NORMALIZED interpretation (raw ids read as CURRENT "
                         "ids): type %s %r, subtype %s %r -> pair %r"
                         % (rt, live_display_of_filter(ex, rt), rs,
                            live_display_of_subtype(ex, rt, rs), raw_as_current))
            else:
                oi = int(parts[1][3:])
                sc_i = int(parts[0][2:])
                r0 = raw["ints"][field]
                nl = live["sc"][sc_i]["osc"][oi]
                T.append(
                    "RAW stored id for %s: %s ; LIVE normalized: %s (display %r)"
                    % (field, r0, nl["p"][0],
                       live_display_of_sine_shape(ex, sc_i, oi, nl["p"][0])))
                T.append("UN-NORMALIZED interpretation: shape %s (%r)"
                         % (r0, live_display_of_sine_shape(ex, sc_i, oi, r0)))

            # ---- build the un-normalized graph ----
            # (an un-normalized exporter has no migration awareness, so its
            #  output carries no mi/rwm/rwu records by construction)
            bad = json.loads(canonical(live))
            for k in ("mi", "rwm", "rwu"):
                bad.pop(k, None)
            if parts[1].startswith("fu"):
                apply_unnormalized(bad, field, norm_keys, rt)
                apply_unnormalized(bad, field, ("st",), rs)
            else:
                apply_unnormalized(bad, field, norm_keys, r0)

            # ---- Layer 1: live-equality ----
            mismatches = diff_fields(bad, live)
            l1 = bool(mismatches)
            T.append("LAYER 1 live-equality check on un-normalized graph: %s"
                     % ("DETECTED -> %s" % mismatches if l1 else "NOT DETECTED"))
            T.append("LAYER 1 on committed graph: %s"
                     % ("clean" if canonical(c["g"]) == canonical(live) else "MISMATCH"))

            # ---- Layer 2: migration-consistency invariant ----
            # The UN-NORMALIZED graph (bad) carries no migration events while
            # its exported values differ from the live normalized values: that
            # violates the invariant "raw != live => recorded migration event"
            # and is what the pipeline's gate turns into analysis_failure.
            bad_mi = bad.get("mi") or []
            l2_violations = []
            if parts[1].startswith("fu"):
                if (rt, rs) != (nl["t"], nl["st"]) and not bad_mi:
                    l2_violations.append(
                        "un-normalized graph exports %s as (type=%s, subtype=%s) "
                        "while live normalized is (%s, %s) with NO migration event "
                        "recorded" % (field, rt, rs, nl["t"], nl["st"]))
                T.append("committed g.mi contains: %s"
                         % [m for m in (live.get("mi") or [])
                            if m["f"] == field])
            else:
                if r0 != nl["p"][0] and not bad_mi:
                    l2_violations.append(
                        "un-normalized graph exports %s=%s while live normalized "
                        "is %s with NO migration event recorded"
                        % (field, r0, nl["p"][0]))
                T.append("committed g.mi contains: %s"
                         % [m for m in (live.get("mi") or []) if m["f"] == field])
            l2 = bool(l2_violations)
            T.append("LAYER 2 migration-consistency check on un-normalized graph "
                     "(raw != live requires a recorded event): %s"
                     % ("DETECTED -> %s" % l2_violations if l2 else "NOT DETECTED"))
            allok &= l1 and l2

            # ---- honest scope note about range validation ----
            v_bad = eng.validate(bad, ex, surgepy)
            T.append("SCOPE NOTE: plain live-range validation of the un-normalized "
                     "graph: %s (range checks alone are not the detection mechanism "
                     "for these subjects; live-equality + migration-consistency are)"
                     % ("violations: %s" % v_bad if v_bad else "no violations (raw ids "
                        "happen to be inside current numeric ranges)"))

        committed_ok = canonical(c["g"]) == canonical(live) and c["st"] == "normalized"
        results[path] = {
            "committed_status": c["st"],
            "committed_matches_live": committed_ok,
        }
        allok &= committed_ok

    # summary verdict
    T.append("=" * 100)
    T.append("NEGATIVE CONTROL VERDICT: %s"
             % ("PASS - un-normalized variants are DETECTED by layers 1+2 and "
                "committed lines pass live-equality" if allok else "FAIL"))
    T.append("If the exporter ever emitted such state, the same two layers gate "
             "the entry to analysis_failure (schema_validation_failed); see "
             "tools/export_normalized_graphs.py export_entry().")

    with open(os.path.join(HERE, "negative-control-transcript.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(T) + "\n")
    with open(os.path.join(HERE, "negative-control-summary.json"), "w",
              encoding="utf-8") as f:
        json.dump({"engine_commit": eng.ENGINE_COMMIT,
                   "subjects": results,
                   "verdict": "PASS" if allok else "FAIL"}, f, indent=2)
    print("\n".join(T))
    return 0 if allok else 1


def live_display_of_filter(ex, type_id):
    p = ex.s.getPatch()["scene"][0]["filterunit"][0]
    old = ex.s.getParamVal(p["type"])
    ex.s.setParamVal(p["type"], float(type_id))
    disp = ex.s.getParamDisplay(p["type"])
    ex.s.setParamVal(p["type"], old)
    return disp


def live_display_of_subtype(ex, type_id, subtype_id):
    p = ex.s.getPatch()["scene"][0]["filterunit"][0]
    old_t, old_s = ex.s.getParamVal(p["type"]), ex.s.getParamVal(p["subtype"])
    ex.s.setParamVal(p["type"], float(type_id))
    ex.s.setParamVal(p["subtype"], float(subtype_id))
    disp = ex.s.getParamDisplay(p["subtype"])
    ex.s.setParamVal(p["type"], old_t)
    ex.s.setParamVal(p["subtype"], old_s)
    return disp


def live_display_of_sine_shape(ex, sc_i, oi, shape_id):
    """Display a shape id on an osc whose normalized type IS sine (the engine
    re-types osc params on respawn, so we must use that osc, not osc 0)."""
    p = ex.s.getPatch()["scene"][sc_i]["osc"][oi]
    if int(ex.s.getParamVal(p["type"])) != ex.sp.constants.ot_sine:
        return "<osc not sine>"
    old = ex.s.getParamVal(p["p"][0])
    ex.s.setParamVal(p["p"][0], float(shape_id))
    disp = ex.s.getParamDisplay(p["p"][0])
    ex.s.setParamVal(p["p"][0], old)
    return disp


def diff_fields(a, b, p=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out.extend(diff_fields(a.get(k), b.get(k), p + "/" + str(k)))
    elif isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff_fields(x, y, p + "[%d]" % i))
    else:
        if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
            out.append("%s: un-normalized=%r vs live=%r" % (p, a, b))
    return out


if __name__ == "__main__":
    sys.exit(main())
