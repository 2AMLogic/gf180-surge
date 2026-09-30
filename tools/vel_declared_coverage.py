#!/usr/bin/env python3
"""SXT-036 declared-sequence coverage: run the frozen velocity /
release-velocity model and the RTL-vs-model integer-exactness harnesses over
the THREE SEQUENCES NAMED BY ISSUE #70 (`fixtures/sequences/`), not only the
leaf-local `sxt036-vel-overlap-v1` sequence.

Issue #70 names, under "Fixtures and oracle -> Sequences":
  fixtures/sequences/seq-notes-coverage-v1.json
  fixtures/sequences/seq-notes-repeated-v1.json
  fixtures/sequences/seq-notes-holds-v1.json

What this establishes (claim 1 only): RTL == frozen model, exactly, on the
declared stimuli -- `tb_vel.sv` (control plane: per-instance source words and
per-destination route sums) and `tb_voice.sv` (the unchanged audio datapath
driven by the same run). It establishes NOTHING about model-vs-pinned-engine
agreement (acceptance item 2, NOT_RUN, #96), fidelity, or sound quality.

COVERAGE IS REPORTED SEPARATELY FROM AGREEMENT (AGENTS.md): the report
records which velocity / release-velocity source words each declared
sequence actually exercises and on which frozen destinations a nonzero route
term is observed, so a green exactness verdict on a stimulus that never
moves a source cannot be mistaken for coverage of that source.

The declared set is monophonic, so it cannot discriminate the per-instance-state
rule (recorded coverage gap). That limitation is SURVEYED rather than asserted:
`seq-poly-8-v1`, the only polyphonic note fixture committed in
`fixtures/sequences/`, is rendered and measured with the same trace-derived
criterion, so the report can state whether ANY committed shared fixture could
close the gap instead of only the three named ones.

Fail-closed: a named sequence missing from `fixtures/sequences/` is a refusal
(exit 2), never a silent fallback to the leaf-local sequence directory.

Exit codes: 0 = exact on every declared sequence with no coverage gap
recorded; 3 = exact everywhere but at least one coverage gap recorded (a gap
is a property of the stimuli, not an agreement failure, so it never turns a
green exactness verdict red -- it is printed and stored instead); 1 = a FAIL
exactness verdict; 2 = refusal.

Usage:
  python3 tools/vel_declared_coverage.py --artifacts reports/SXT-036/artifacts
  python3 tools/vel_declared_coverage.py --artifacts DIR --skip-datapath
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "model", "voice", "run_vel_model.py")
CMP_VEL = os.path.join(REPO, "tools", "compare_vel_rtl_model.py")
CMP_VOICE = os.path.join(REPO, "tools", "compare_rtl_model.py")
SEQ_DIR = os.path.join(REPO, "fixtures", "sequences")

# the sequences named by issue #70 (SXT-036), in issue order
DECLARED = ["seq-notes-coverage-v1", "seq-notes-repeated-v1",
            "seq-notes-holds-v1"]

# NOT one of the sequences named by #70. The declared set is monophonic, so the
# per-instance-state controls cannot fire on it (recorded coverage gap). This is
# the only polyphonic NOTE fixture committed in fixtures/sequences/, i.e. the
# only committed candidate that could close that gap without a leaf-local
# stimulus, so it is measured (not assumed) with the same trace-derived
# criterion the controls use.
POLY_CANDIDATE = "seq-poly-8-v1"

DEST_ORDER = ["cutoff", "reso", "fegmod", "vca"]


class Refuse(Exception):
    pass


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def declared_path(seq):
    p = os.path.join(SEQ_DIR, seq + ".json")
    if not os.path.exists(p):
        raise Refuse(f"declared sequence absent from fixtures/sequences: {seq}")
    return p


def trace_coverage(trace_path):
    """Source-word and destination-term coverage actually exercised."""
    with open(trace_path, encoding="utf-8") as f:
        t = json.load(f)
    vel_words, relvel_words = set(), set()
    dest_nonzero = [0, 0, 0, 0]
    records = 0
    concurrent = 0
    max_live = 0
    for blk in t["blocks"]:
        max_live = max(max_live, len(blk["voices"]))
        if (len(blk["voices"]) > 1
                and len({tuple(r["vel_words"]) for r in blk["voices"]}) > 1):
            concurrent += 1
        for rec in blk["voices"]:
            records += 1
            vel_words.add(rec["vel_words"][0])
            relvel_words.add(rec["vel_words"][1])
            for i, s in enumerate(rec["vel_route_sums"]):
                if s != 0:
                    dest_nonzero[i] += 1
    return {
        "blocks": len(t["blocks"]),
        "voice_block_records": records,
        "max_concurrent_voices": max_live,
        # the precondition the per-instance-state controls need in order to
        # be able to fire at all (see tools/vel_negative_controls.py)
        "concurrent_distinct_source_word_blocks": concurrent,
        "distinct_vel_q": sorted(vel_words),
        "distinct_relvel_q": sorted(relvel_words),
        "nonzero_relvel_q": sorted(w for w in relvel_words if w != 0),
        "voice_blocks_with_nonzero_route_sum":
            dict(zip(DEST_ORDER, dest_nonzero)),
        "routes": t.get("vel_routes", []),
    }


def exactness(cmp_tool, run_dir):
    rc, out, err = sh([sys.executable, cmp_tool, "--run-dir", run_dir])
    try:
        return rc, json.loads(out)
    except Exception:
        return rc, {"verdict": "ERROR", "mismatches": None,
                    "stderr_tail": err[-300:]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--skip-datapath", action="store_true",
                    help="skip the tb_voice.sv datapath comparison "
                         "(control-plane exactness only)")
    args = ap.parse_args()
    art = os.path.abspath(args.artifacts)
    os.makedirs(art, exist_ok=True)
    work = tempfile.mkdtemp(prefix="sxt036-declared-")
    lines, per_seq, ok = [], {}, True

    def log(s=""):
        lines.append(s)
        print(s, flush=True)

    log("SXT-036 declared-sequence coverage (issue #70 named sequences)")
    log("Claim established: RTL == frozen model, exactly (claim 1). "
        "Model-vs-pinned-engine agreement: NOT_RUN (#96). No fidelity or "
        "sound-quality claim.")
    log("")

    for seq in DECLARED:
        path = declared_path(seq)
        run_dir = os.path.join(work, seq)
        rc, out, err = sh([sys.executable, RUNNER, "--sequence", path,
                           "--out-dir", run_dir])
        if rc != 0:
            log(f"[{seq}] model runner exit {rc}: {err[-300:]}")
            per_seq[seq] = {"model_runner_exit": rc}
            ok = False
            continue
        cov = trace_coverage(os.path.join(run_dir, "model_trace.json"))
        rc_v, jv = exactness(CMP_VEL, run_dir)
        log(f"[{seq}] tb_vel.sv control plane: {jv['verdict']} "
            f"mismatches={jv['mismatches']} checked={jv.get('checked')}")
        if jv["verdict"] != "PASS":
            ok = False
        entry = {"sequence_path": os.path.relpath(path, REPO),
                 "control_plane": jv, "coverage": cov}
        if args.skip_datapath:
            log(f"[{seq}] tb_voice.sv datapath: SKIPPED (--skip-datapath)")
            entry["datapath"] = {"verdict": "NOT_RUN",
                                 "reason": "--skip-datapath"}
        else:
            rc_d, jd = exactness(CMP_VOICE, run_dir)
            log(f"[{seq}] tb_voice.sv datapath:     {jd['verdict']} "
                f"mismatches={jd['mismatches']} checked={jd.get('checked')}")
            if jd["verdict"] != "PASS":
                ok = False
            entry["datapath"] = jd
        log(f"    coverage: {cov['blocks']} blocks, "
            f"{cov['voice_block_records']} voice-block records; "
            f"max concurrent voices={cov['max_concurrent_voices']}; "
            f"distinct vel_q={cov['distinct_vel_q']}; "
            f"nonzero relvel_q={cov['nonzero_relvel_q']}")
        log(f"    voice-blocks with a nonzero route term per destination: "
            f"{cov['voice_blocks_with_nonzero_route_sum']}")
        per_seq[seq] = entry
        shutil.rmtree(run_dir, ignore_errors=True)
        log("")

    # --- survey: can ANY committed fixture discriminate per-instance state? --
    survey = {}
    cand_path = declared_path(POLY_CANDIDATE)
    cand_dir = os.path.join(work, POLY_CANDIDATE)
    rc, out, err = sh([sys.executable, RUNNER, "--sequence", cand_path,
                       "--out-dir", cand_dir])
    if rc != 0:
        log(f"[survey {POLY_CANDIDATE}] model runner exit {rc}: {err[-200:]}")
        survey = {"model_runner_exit": rc}
        ok = False
    else:
        cov = trace_coverage(os.path.join(cand_dir, "model_trace.json"))
        rc_v, jv = exactness(CMP_VEL, cand_dir)
        log(f"[survey {POLY_CANDIDATE}] NOT named by #70; measured because it "
            f"is the only polyphonic note fixture in fixtures/sequences/")
        log(f"    tb_vel.sv control plane: {jv['verdict']} "
            f"mismatches={jv['mismatches']} checked={jv.get('checked')}")
        log(f"    max concurrent voices={cov['max_concurrent_voices']}; "
            f"distinct vel_q={cov['distinct_vel_q']}; nonzero relvel_q="
            f"{cov['nonzero_relvel_q']}; blocks with >=2 concurrently-live "
            f"voices carrying DISTINCT source words="
            f"{cov['concurrent_distinct_source_word_blocks']}")
        discriminates = cov["concurrent_distinct_source_word_blocks"] > 0
        log("    -> " + ("this fixture DOES discriminate per-instance state"
                         if discriminates else
                         "eight voices, but every one carries the same "
                         "velocity (and the same release velocity), so a "
                         "scene-wide shared register is still behaviourally "
                         "identical here: it does NOT discriminate "
                         "per-instance state either"))
        if jv["verdict"] != "PASS":
            ok = False
        survey = {"sequence_path": os.path.relpath(cand_path, REPO),
                  "named_by_issue_70": False,
                  "control_plane": jv, "coverage": cov,
                  "datapath": {"verdict": "NOT_RUN",
                               "reason": "not a sequence named by #70; run "
                                         "here only as the per-instance-state "
                                         "discrimination survey"},
                  "discriminates_per_instance_state": discriminates}
        shutil.rmtree(cand_dir, ignore_errors=True)
    log("")

    # --- coverage roll-up, reported separately from the agreement verdicts ---
    all_vel = sorted({w for e in per_seq.values()
                      for w in e.get("coverage", {}).get("distinct_vel_q", [])})
    all_relvel = sorted({w for e in per_seq.values()
                         for w in e.get("coverage", {}).get("nonzero_relvel_q", [])})
    dest_cov = {d: sum(e.get("coverage", {})
                       .get("voice_blocks_with_nonzero_route_sum", {}).get(d, 0)
                       for e in per_seq.values()) for d in DEST_ORDER}
    concurrent = sum(e.get("coverage", {})
                     .get("concurrent_distinct_source_word_blocks", 0)
                     for e in per_seq.values())
    log("Coverage roll-up over the declared set (NOT an agreement claim):")
    log(f"  ms_velocity source words exercised:         {all_vel}")
    log(f"  ms_releasevelocity nonzero words exercised: {all_relvel}")
    log(f"  voice-blocks with a nonzero route term:     {dest_cov}")
    log(f"  blocks with >=2 concurrently-live voices carrying distinct "
        f"source words: {concurrent}")
    gaps = []
    if len(all_vel) < 2:
        gaps.append("the declared set exercises fewer than two distinct "
                    "ms_velocity source words")
    if not all_relvel:
        gaps.append("the declared set never drives ms_releasevelocity "
                    "nonzero: a green exactness verdict would not cover "
                    "the release-velocity source")
    for d in DEST_ORDER:
        if dest_cov[d] == 0:
            gaps.append(f"no nonzero route term ever observed on "
                        f"destination '{d}'")
    if concurrent == 0:
        gap = ("every declared sequence is monophonic (no block ever "
               "has two concurrently-live voices with distinct source "
               "words), so the PER-INSTANCE-STATE rule is NOT "
               "discriminated by the declared set: a scene-wide shared "
               "{vel, relvel} register would pass these runs. That "
               "control fires only on an overlapping stimulus (the "
               "leaf-local 'sxt036-vel-overlap-v1'); "
               "tools/vel_negative_controls.py reports it NOT_RUN on "
               "these sequences rather than passing it")
        if survey.get("discriminates_per_instance_state") is False:
            gap += (f". Surveyed beyond the declared set: {POLY_CANDIDATE}, "
                    "the only polyphonic note fixture committed in "
                    "fixtures/sequences/, holds eight voices at ONE velocity "
                    "and one release velocity, so it does not discriminate "
                    "either - no committed shared fixture closes this gap, "
                    "which is why the leaf-local stimulus exists")
        gaps.append(gap)
    for g in gaps:
        log(f"  COVERAGE GAP: {g}")
    if not gaps:
        log("  no coverage gap recorded for the declared set")
    log("")
    log("Not established here: model-vs-pinned-engine dry-render budgets "
        "(item 2) and the reference-budget negative controls (item 5) remain "
        "NOT_RUN - pinned oracle unavailable on dispatch host (#96).")
    log(f"AGREEMENT (RTL == frozen model, integer equality): "
        f"{'PASS' if ok else 'FAIL'}")
    log(f"COVERAGE: {len(gaps)} gap(s) recorded" if gaps
        else "COVERAGE: no gap recorded")

    with open(os.path.join(art, "declared-sequence-coverage.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(art, "declared-sequence-coverage.json"), "w",
              encoding="utf-8") as f:
        json.dump({"agreement": "PASS" if ok else "FAIL",
                   "claim": "RTL == frozen model (integer equality) on the "
                            "sequences named by issue #70",
                   "reference_budget_items": "NOT_RUN (#96)",
                   "coverage_rollup": {
                       "vel_q_words": all_vel,
                       "relvel_q_nonzero_words": all_relvel,
                       "voice_blocks_with_nonzero_route_sum": dest_cov,
                       "concurrent_distinct_source_word_blocks": concurrent,
                       "gaps": gaps},
                   "per_instance_state_survey": survey,
                   "sequences": per_seq}, f, indent=2)
        f.write("\n")
    shutil.rmtree(work, ignore_errors=True)
    # 0 = exact everywhere and no coverage gap; 3 = exact everywhere but at
    # least one recorded coverage gap (coverage is reported separately from
    # agreement, so a gap is not an agreement failure); 1 = a FAIL verdict.
    if not ok:
        return 1
    return 3 if gaps else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)
