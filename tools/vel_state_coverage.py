#!/usr/bin/env python3
"""SXT-036 (#70) per-instance STATE coverage census of the committed note
fixtures. Oracle-independent: model runs only, no iverilog, no pinned engine.

Issue #70 states the per-instance rule for this leaf: "routes are per-scene
and per-destination; state is never shared across scenes", and the frozen
model adds the construction-time rule cited from the pinned engine
(`SurgeVoice` ctor: `releaseVelocitySource.set_output(0, 0)`), i.e. a REUSED
voice slot must start from a cleared release-velocity register.

Three stimulus preconditions decide whether a control that targets those
rules can fire at all:

  per_instance   >= 2 concurrently-live voices carrying DISTINCT (vel_q,
                 relvel_q) words in some block -- otherwise a scene-wide
                 shared register is behaviourally identical to per-voice
                 registers.
  slot_reuse     a slot is CREATED again after its previous voice was
                 released with a NONZERO release-velocity word -- otherwise
                 a missing constructor clear is unobservable.
  release_word   a running voice is released with a nonzero release-velocity
                 word -- otherwise a release latch applied one block late is
                 unobservable.

This census reports, per sequence, whether each precondition holds, so that
`tools/vel_negative_controls.py`'s NOT_RUN verdicts are backed by measured
coverage rather than by assertion. Coverage is reported SEPARATELY from
agreement (AGENTS.md): nothing here is a pass of any acceptance item, and in
particular nothing here establishes model-vs-pinned-engine agreement (item 2)
or the reference-budget controls (item 5), both NOT_RUN on this host (#96).

Two stages:
  1. STATIC screen over every committed sequence JSON (fixtures/sequences/
     and model/voice/sequences/): note counts, distinct note-on velocities,
     and nonzero MIDI release velocities. A sequence with NO nonzero release
     velocity can never satisfy `slot_reuse` or `release_word` -- that is a
     property of the file, provable without rendering, and it is recorded as
     IMPOSSIBLE (not as NOT_RUN of a control).
  2. DYNAMIC measurement, by rendering a named subset through
     `model/voice/run_vel_model.py` and reading the three preconditions off
     the resulting model trace.

Exit codes: 0 = some SHARED fixture (fixtures/sequences/) satisfies all three
preconditions; 3 = at least one precondition is satisfied by no shared
fixture (a recorded coverage gap, by design not a failure); 1 = a run error.

Usage:
  python3 tools/vel_state_coverage.py --artifacts reports/SXT-036/artifacts
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "model", "voice", "run_vel_model.py")
SHARED_DIR = os.path.join(REPO, "fixtures", "sequences")
LOCAL_DIR = os.path.join(REPO, "model", "voice", "sequences")

# rendered subset: the three sequences NAMED BY #70, the only committed
# polyphonic note fixture, and this leaf's two local stimuli
DYNAMIC = ("seq-notes-coverage-v1", "seq-notes-repeated-v1",
           "seq-notes-holds-v1", "seq-poly-8-v1",
           "sxt036-vel-overlap-v1", "sxt036-vel-corners-v1")
DECLARED = ("seq-notes-coverage-v1", "seq-notes-repeated-v1",
            "seq-notes-holds-v1")
PRECONDITIONS = ("per_instance", "slot_reuse", "release_word")


def trace_preconditions(trace):
    """Measure the three stimulus preconditions from a model trace.

    Single implementation, imported by tools/vel_negative_controls.py so the
    census and the controls can never disagree about whether a control was
    able to fire.
    """
    concurrent = sum(
        1 for blk in trace["blocks"]
        if len(blk["voices"]) > 1
        and len({tuple(r["vel_words"]) for r in blk["voices"]}) > 1)
    last_relvel = {}
    reuse, release_words = 0, 0
    for blk in trace["blocks"]:
        by_slot = {r["slot"]: r for r in blk["voices"]}
        for slot in blk["create"]:
            if last_relvel.get(slot, 0) != 0:
                reuse += 1
            last_relvel[slot] = 0
        for slot in blk["release"]:
            rec = by_slot.get(slot)
            w = rec["vel_words"][1] if rec else 0
            last_relvel[slot] = w
            if rec is not None and w != 0:
                release_words += 1
    return {
        "concurrent_distinct_source_word_blocks": concurrent,
        "slot_reuse_after_nonzero_release_velocity_blocks": reuse,
        "release_blocks_with_nonzero_relvel_word": release_words,
        "per_instance": concurrent > 0,
        "slot_reuse": reuse > 0,
        "release_word": release_words > 0,
    }


def static_screen(path):
    seq = json.load(open(path, encoding="utf-8"))
    ev = seq.get("events", [])
    ons = [e for e in ev if e.get("type") == "note_on"]
    offs = [e for e in ev if e.get("type") == "note_off"]
    nz_rel = [e for e in offs if int(e.get("velocity", 0)) != 0]
    # gated overlap: how many notes are simultaneously held down (a lower
    # bound on voice concurrency, which also includes release tails)
    marks = sorted([(e["t"], 1) for e in ons] + [(e["t"], -1) for e in offs])
    cur = peak = 0
    for _t, d in marks:
        cur += d
        peak = max(peak, cur)
    return {
        "id": seq.get("id", os.path.splitext(os.path.basename(path))[0]),
        "note_ons": len(ons), "note_offs": len(offs),
        "distinct_note_on_velocities":
            len({int(e.get("velocity", 0)) for e in ons}),
        "nonzero_release_velocities": len(nz_rel),
        "max_gated_overlap": peak,
        # provable without rendering: no nonzero release velocity anywhere
        # => neither release-velocity precondition can ever hold
        "release_preconditions_impossible": len(nz_rel) == 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--sequences", nargs="*", default=list(DYNAMIC),
                    help="sequences to render and measure dynamically")
    args = ap.parse_args()
    art = os.path.abspath(args.artifacts)
    os.makedirs(art, exist_ok=True)
    lines = []

    def log(s=""):
        lines.append(s)
        print(s)

    log("SXT-036 per-instance STATE coverage census (#70) -- oracle-"
        "independent (model runs only). Coverage, reported separately from "
        "agreement; no acceptance item passes here.")
    log("")

    # ------------------------------------------------------ static screen --
    paths = sorted(glob.glob(os.path.join(SHARED_DIR, "*.json"))) + \
        sorted(glob.glob(os.path.join(LOCAL_DIR, "*.json")))
    static = {}
    log("STATIC screen of every committed sequence with note events "
        "(shared fixtures/sequences/ first, then model/voice/sequences/):")
    log(f"  {'sequence':32s} {'on':>3s} {'off':>3s} {'distinct vel':>12s} "
        f"{'nonzero relvel':>14s} {'gated overlap':>13s}")
    for p in paths:
        try:
            st = static_screen(p)
        except (json.JSONDecodeError, KeyError):
            continue
        if st["note_ons"] == 0:
            continue
        st["shared"] = os.path.dirname(p) == SHARED_DIR
        static[st["id"]] = st
        log(f"  {st['id']:32s} {st['note_ons']:3d} {st['note_offs']:3d} "
            f"{st['distinct_note_on_velocities']:12d} "
            f"{st['nonzero_release_velocities']:14d} "
            f"{st['max_gated_overlap']:13d}")
    shared_with_relvel = [s for s in static.values()
                          if s["shared"] and s["nonzero_release_velocities"]]
    log("")
    log(f"  {len(static)} sequences screened; "
        f"{sum(1 for s in static.values() if s['shared'])} are shared "
        f"fixtures. Shared fixtures carrying ANY nonzero MIDI release "
        f"velocity: {len(shared_with_relvel)} "
        f"({', '.join(s['id'] for s in shared_with_relvel) or 'none'}).")
    log("  For every other shared fixture both release-velocity "
        "preconditions are IMPOSSIBLE by inspection of the file (no nonzero "
        "release velocity exists to latch), so no render is needed to say "
        "so -- and that is a coverage statement, not a control verdict.")
    log("")

    # ----------------------------------------------------------- dynamic ---
    work = tempfile.mkdtemp(prefix="sxt036-cov-")
    dyn, rc = {}, 0
    log("DYNAMIC measurement (rendered through model/voice/run_vel_model.py; "
        "no iverilog, no oracle):")
    log(f"  {'sequence':32s} {'per_instance':>12s} {'slot_reuse':>11s} "
        f"{'release_word':>13s}")
    for sid in args.sequences:
        d = os.path.join(work, sid)
        r = subprocess.run([sys.executable, RUNNER, "--sequence", sid,
                            "--out-dir", d], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"  {sid:32s} RUN ERROR exit {r.returncode}: "
                f"{r.stderr.strip()[-160:]}")
            rc = 1
            continue
        with open(os.path.join(d, "model_trace.json"), encoding="utf-8") as f:
            pre = trace_preconditions(json.load(f))
        pre["shared"] = static.get(sid, {}).get("shared", False)
        dyn[sid] = pre
        log(f"  {sid:32s} "
            f"{('YES %d' % pre['concurrent_distinct_source_word_blocks']) if pre['per_instance'] else 'no':>12s} "
            f"{('YES %d' % pre['slot_reuse_after_nonzero_release_velocity_blocks']) if pre['slot_reuse'] else 'no':>11s} "
            f"{('YES %d' % pre['release_blocks_with_nonzero_relvel_word']) if pre['release_word'] else 'no':>13s}")
        shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    log("")

    # ------------------------------------------------------------ verdict --
    gaps = []
    for key in PRECONDITIONS:
        shared_ok = [s for s, v in dyn.items() if v["shared"] and v[key]]
        local_ok = [s for s, v in dyn.items() if not v["shared"] and v[key]]
        declared_ok = [s for s in DECLARED if dyn.get(s, {}).get(key)]
        log(f"  precondition '{key}': satisfied by "
            f"{len(declared_ok)}/{len(DECLARED)} sequences NAMED by #70, "
            f"{len(shared_ok)} shared fixture(s) "
            f"({', '.join(shared_ok) or 'none'}), "
            f"{len(local_ok)} leaf-local stimulus/stimuli "
            f"({', '.join(local_ok) or 'none'}).")
        if not shared_ok:
            gaps.append(key)
    log("")
    if gaps:
        log(f"RECORDED COVERAGE GAP: no SHARED fixture satisfies "
            f"{', '.join(repr(g) for g in gaps)}. Controls targeting "
            "those rules can only fire on a leaf-local stimulus; on a "
            "shared fixture they are reported NOT_RUN with the precondition "
            "named, never as a pass. Adding such a stimulus to "
            "fixtures/sequences/ would be a change to shared fixtures and is "
            "out of this leaf's scope.")
        rc = rc or 3
    else:
        log("No coverage gap: every precondition is satisfied by at least "
            "one shared fixture.")

    with open(os.path.join(art, "state-coverage.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(art, "state-coverage.json"), "w",
              encoding="utf-8") as f:
        json.dump({"tool": "vel_state_coverage/1",
                   "declared_sequences": list(DECLARED),
                   "static_screen": static,
                   "dynamic": dyn,
                   "preconditions": list(PRECONDITIONS),
                   "shared_fixture_gaps": gaps,
                   "oracle_dependent_items": {"2": "NOT_RUN", "5": "NOT_RUN"}},
                  f, indent=2)
        f.write("\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
