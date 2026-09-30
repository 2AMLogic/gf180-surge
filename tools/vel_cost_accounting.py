#!/usr/bin/env python3
"""SXT-036 (#70) cost accounting against the SXT-015 accounting -- ORACLE-
INDEPENDENT (iverilog + committed corpus artifacts only; no pinned engine).

Issue #70 acceptance item 4 reads: "Cycle/state costs recorded against SXT-016
probes and the SXT-015 accounting; divergences recorded, not reconciled away."
The first increment recorded the SXT-016 half (`artifacts/costs.txt`: the
scheduler probe has no per-source-evaluation row, divergence recorded). The
**SXT-015 half was never recorded**. This tool records it.

What SXT-015 charges (model/resources/accounting.py, cost profile
`placeholder-v0`), since the shape decision of #239:

    mod_cycles = _modroute_evaluations(g, worst_voices) * REG.cyc_modroute_frame

i.e. **15 cycles per modulation routing row EVALUATION**, where a global or
scene-list row is evaluated once per frame and a **voice**-list row once per
worst-case live voice per frame. `cyc_modroute_frame` is still a `placeholder`
param whose estimate_ref says "SXT-016", and no SXT-016 probe replaces it: of
the 76 committed probe records, `sxt015_replacement.replaces` covers
cyc_filter_unit_frame, cyc_fxdelay_frame, cyc_fxgeneric_frame,
cyc_fxreverb1_frame, cyc_osc_unison_voice_frame and cyc_event_frame -- never
cyc_modroute_frame (asserted here, and reported STALE if that ever changes).

What this leaf measures, on the exact behavioral schedule it froze
(`rtl/voice/tb_vel.sv` counters, `OPS` line):

    route evaluations = routes x per-voice control passes

Both sources this leaf implements (`ms_velocity` 1, `ms_releasevelocity` 30)
are PER-VOICE sources, and their routes are voice-list rows, so a voice row's
work scales with the number of LIVE VOICES in the frame -- not with the row
count alone.

That measured law was FIRST RECORDED HERE as a SHAPE divergence against an
accounting that charged every row once per frame. #239 took the shape
decision it fed: the accounting now charges a voice row once per worst-case
live voice per frame, so the shape divergence is RESOLVED and this tool
CROSS-CHECKS it (`shape_resolution` below; a carrier whose accounted
modulation term stops equalling `evaluations x cyc_modroute_frame` is a
failure here, not a re-record). What remains diverging is the per-evaluation
CONSTANT -- 15 accounted cycles against a 2..8 derived bracket -- and only an
SXT-016 probe may pin that. Nothing in this leaf is re-tuned to make the two
agree; the pin below was RE-RECORDED from the live model, never adjusted to
keep a number small.

Claim discipline (AGENTS.md):
  * Op counts (multiplies, adds, compares, control passes, route evaluations)
    are MEASURED, exactly, on the iverilog behavioral schedule.
  * Cycles are NOT measured. Where a cycles number appears it is DERIVED under
    two explicitly named readings of the SXT-016 assumptions (A-DSP-1c,
    A-ALU-1) and reported as a BRACKET, never as a single value and never as a
    probe result. No technology, synthesis, timing or hardware claim is made.
  * This establishes no model-vs-pinned-engine agreement (item 2) and none of
    the reference-budget controls (item 5); both stay NOT_RUN on this host
    (#96/#232). Supported-preset delta stays 0.

Controls (each must demonstrably fail the check it targets):
  K1 per-frame shape       predicting route evaluations with the RETIRED
                           voice-count-independent shape (routes x frames,
                           what SXT-015 charged before #239) must MISPREDICT
                           the measured count.
  K2 route-count-blind     predicting with a fixed route count must MISPREDICT
                           across the route-table sweep.
  K3 attribution           an empty route table must measure exactly zero
                           multiplies and zero evaluations, while the
                           per-frame prediction is still positive.
  K4 pin drift (refusal)   a mutated SXT-015 pin (profile / digest /
                           cyc_modroute_frame) must REFUSE, never silently
                           re-baseline the recorded divergence.
  K5 probe-claim detector  a synthetic probe record claiming to replace
                           cyc_modroute_frame must be DETECTED (the "no probe
                           pins this row" statement is falsifiable).
  K6 state cross-check     the 512-bit per-slot state figure is only
                           meaningful because a scene-wide register FAILS
                           exactness; that verdict is read back from the
                           committed control transcript, and reported NOT_RUN
                           (never assumed) if the transcript is absent.

Exit codes: 0 = every measured law held and every control fired; 1 = a
measured law failed or a control did not fire; 2 = a pin refusal (SXT-015 cost
model or graphs.jsonl moved); 3 = laws held and controls fired, but something
is NOT_RUN / STALE and recorded as such.

Usage:
  python3 tools/vel_cost_accounting.py --artifacts reports/SXT-036/artifacts
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

from _rtl_compile_common import compile_and_run            # noqa: E402

RUNNER = os.path.join(REPO, "model", "voice", "run_vel_model.py")
CMP = os.path.join(REPO, "tools", "compare_vel_rtl_model.py")
TB_VEL = os.path.join(REPO, "rtl", "voice", "tb_vel.sv")
VEL_INPUTS = os.path.join(REPO, "model", "voice", "attacky_vel_inputs.json")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
PROBE_DIR = os.path.join(REPO, "reports", "sxt-016", "probes")
SCHEDULER_PROBE = os.path.join(
    PROBE_DIR, "probe_scheduler__event_queue_and_control__a24__m32__onchip.json")
CONTROLS_JSON_REL = "negative-controls.json"

# sha256 pinned in the body of issue #70 ("Inputs / outputs / state")
GRAPHS_SHA256 = ("c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df"
                 "39204715")

# ---------------------------------------------------------------- SXT-015 pins
# The comparison below is only meaningful against a KNOWN cost model. If any of
# these moves, this artifact is re-RECORDED against the new model -- the leaf is
# never re-tuned to keep a divergence small, and the tool must not silently
# carry an old comparison forward. Fail closed (exit 2).
#
# RE-RECORDED for the #239 shape decision (2026-09-30): `model_version`
# 1.0.0 -> 1.1.0 and `params_digest` 646942e9c3887ecb -> a639d3115ae1a0ca,
# both read off the live model. `cyc_modroute_frame` is UNCHANGED at 15 --
# the decision changed the number of evaluations charged, not the constant,
# and this pin was not adjusted in any other way.
PIN_SXT015 = {
    "model_version": "sxt-015-accounting/1.1.0",
    "cost_profile": "placeholder-v0",
    "params_digest": "a639d3115ae1a0ca",
    "cyc_modroute_frame": 15,
    "clock_hz": 480000000,
    "sample_rate_hz": 48000,
    "reserve_fraction": 0.2,
}
SXT015_ROW = "cyc_modroute_frame"
# the shape finding this tool first recorded was dispositioned there (the
# accounting now charges voice rows per live voice); the per-evaluation
# CONSTANT is still SXT-016 work, not voice-leaf work
FOLLOWUP_ISSUE = 239

# claims quoted by the first increment's hand-assembled artifacts/costs.txt,
# re-derived here so that file stops being an unchecked hand assembly. A change
# makes costs.txt STALE (reported, not silently corrected).
PIN_COSTS_TXT = {
    "qmul_per_running_voice_block": 6,     # = the 6 declared fixture routes
    "per_slot_state_bits": 512,            # 8 slots x {vel_q, relvel_q} x 32 b
    "probe_cycles_per_event": 88,
    "probe_state_ram_bits": 512,
}

N_SLOTS = 8                 # rtl/voice/tb_vel.sv NSLOTS
SOURCE_WORD_BITS = 32       # Q10.21 control word
SOURCES_PER_SLOT = 2        # {vel_q, relvel_q}

# stimuli measured: the leaf-local per-instance carrier, the three sequences
# NAMED by #70, and the only committed polyphonic note fixture (which is where
# the shape divergence is largest).
STIMULI = ("sxt036-vel-overlap-v1", "seq-notes-coverage-v1",
           "seq-notes-repeated-v1", "seq-notes-holds-v1", "seq-poly-8-v1")
SWEEP_SEQ = "sxt036-vel-overlap-v1"
SWEEP_ROUTES = (0, 1, 2, 3, 4, 5, 6)

CARRIERS = [
    "resources/data/patches_3rdparty/Bluelight/Pads/Bad News.fxp",
    "resources/data/patches_3rdparty/Bluelight/Pads/Rainy Day Dreamaway.fxp",
    "resources/data/patches_3rdparty/Damon Armani/Pads/House Of Chords.fxp",
]
FIXTURE_CARRIER = "resources/data/patches_factory/Basses/Attacky.fxp"

# Two NAMED readings of the SXT-016 assumptions, used only to bracket a
# candidate cycles-per-evaluation figure. Neither is measured; neither is a
# probe; no technology claim.
READING_MAC = ("A-DSP-1c read as 'the 32x32->64 multiply, its rounding add and "
               "its saturation clamp are one MAC pass' + A-ALU-1 for the "
               "32-bit accumulate")
READING_ALU = ("every op a separate cycle, with the 64-bit rounding add and "
               "the two 64-bit saturation compares costing 2 cycles each on a "
               "32-bit ALU (A-ALU-1 covers <=32-bit words only)")


class Refuse(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------ SXT-015 surface
def live_sxt015():
    """Read the live SXT-015 cost model (never a second copy of its values)."""
    from model.resources.accounting import MODEL_VERSION, params_digest
    from model.resources.params import REG
    return {
        "model_version": MODEL_VERSION,
        "cost_profile": REG.cost_profile,
        "params_digest": params_digest(),
        "cyc_modroute_frame": REG.cyc_modroute_frame,
        "clock_hz": REG.clock_hz,
        "sample_rate_hz": REG.sample_rate_hz,
        "reserve_fraction": REG.reserve_fraction,
    }


def pin_drift(live, pin):
    """Pure: names every pinned SXT-015 value that moved (K4's check)."""
    return [f"{k}: pinned {pin[k]!r} != live {live.get(k)!r}"
            for k in sorted(pin) if live.get(k) != pin[k]]


def probes_replacing(records, row):
    """Pure: probe names whose sxt015_replacement claims to replace `row`."""
    out = []
    for name, rec in records:
        rep = (rec.get("sxt015_replacement") or {}).get("replaces") or ""
        if row in rep:
            out.append(name)
    return sorted(out)


def load_probe_records(probe_dir):
    recs = []
    for p in sorted(glob.glob(os.path.join(probe_dir, "*.json"))):
        with open(p, encoding="utf-8") as f:
            recs.append((os.path.basename(p), json.load(f)))
    return recs


def md_row_split(graph):
    """Split a normalized graph's modulation rows the way SXT-015 counts them.

    Returns global / per-scene scene-list / per-scene voice-list counts. The
    TOTAL is cross-checked against SXT-015's own `_count_modroutes` so this
    split can never drift away from the quantity the accounting charges.
    """
    from model.resources.accounting import _count_modroutes
    md = graph.get("md", {})
    scenes = md.get("s", [])
    split = {
        "global": len(md.get("g", [])),
        "scene_rows_per_scene": [len(sc.get("s", [])) for sc in scenes],
        "voice_rows_per_scene": [len(sc.get("v", [])) for sc in scenes],
    }
    split["scene_rows"] = sum(split["scene_rows_per_scene"])
    split["voice_rows"] = sum(split["voice_rows_per_scene"])
    split["total"] = split["global"] + split["scene_rows"] + split["voice_rows"]
    counted = _count_modroutes(graph)
    if split["total"] != counted:
        raise Refuse(f"row split {split['total']} != SXT-015 _count_modroutes "
                     f"{counted}; the accounting's row definition moved")
    return split


def graph_rows(paths):
    want, found = set(paths), {}
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("p") in want:
                found[row["p"]] = row
    missing = sorted(want - set(found))
    if missing:
        raise Refuse(f"carrier absent from graphs.jsonl: {missing}")
    return found


# --------------------------------------------------------------- measurement
def sidecar_with_routes(src_path, n_routes, dest_path):
    """A declared-route sidecar truncated to its first `n_routes` routes."""
    with open(src_path, encoding="utf-8") as f:
        sc = json.load(f)
    if n_routes > len(sc["fixture_routes"]):
        raise Refuse(f"sidecar has {len(sc['fixture_routes'])} declared "
                     f"routes, asked for {n_routes}")
    sc["fixture_routes"] = sc["fixture_routes"][:n_routes]
    sc["provenance"] = (sc.get("provenance", "") + " [route-table sweep: "
                        f"truncated to the first {n_routes} declared routes by "
                        "tools/vel_cost_accounting.py; depths unchanged]")
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(sc, f, indent=2)
        f.write("\n")
    return dest_path


def parse_ops(stdout):
    """Read the tb_vel.sv `OPS` counter line (measured op profile)."""
    for ln in reversed(stdout.splitlines()):
        if ln.startswith("OPS "):
            return {k: int(v) for k, v in
                    (tok.split("=") for tok in ln.split()[1:])}
    return None


def run_tb_vel(run_dir):
    """Compile+run rtl/voice/tb_vel.sv in `run_dir`; return its op counters."""
    res = compile_and_run(
        TB_VEL, run_dir, out_name="tb_vel_cost.vvp", absolute=True,
        compile_in_workdir=True, quiet_compile=True, capture_output=True,
        trace_name="tb_vel_trace.txt", report_sim_fails=True,
        stimulus_files=["rtl/vel_init.hex", "rtl/vel_routes.hex",
                        "rtl/vel_ctrl.hex"])
    if res.sim_fails:
        raise Refuse(f"tb_vel.sv simulation failure: {res.sim_fails}")
    ops = parse_ops(res.stdout)
    if ops is None:
        raise Refuse("tb_vel.sv emitted no OPS counter line")
    return ops


def trace_stats(trace):
    """Frames, per-voice control passes, live-voice histogram, ROM reads.

    ROM reads are counted from the declared stimulus stream (create/release
    flags) rather than from an RTL counter on purpose: those latch blocks are
    mutation anchors for the state controls and stay byte-identical.
    """
    blocks = trace["blocks"]
    live = [len(b["voices"]) for b in blocks]
    return {
        "frames": len(blocks),
        "control_passes": sum(live),
        "max_live_voices": max(live) if live else 0,
        "mean_live_voices": (sum(live) / len(live)) if live else 0.0,
        "event_rom_reads": sum(len(b["create"]) + len(b["release"])
                              for b in blocks),
        "routes": len(trace["vel_routes"]),
    }


def measure(seq, work, tag, vel_inputs=None):
    """Render a stimulus, check exactness, and read the measured op profile."""
    d = os.path.join(work, tag)
    cmd = [sys.executable, RUNNER, "--sequence", seq, "--out-dir", d]
    if vel_inputs:
        cmd += ["--vel-inputs", vel_inputs]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Refuse(f"model runner exit {r.returncode}: {r.stderr[-300:]}")
    with open(os.path.join(d, "model_trace.json"), encoding="utf-8") as f:
        trace = json.load(f)
    stats = trace_stats(trace)
    ops = run_tb_vel(d)
    # positive control: the cost is measured on a schedule that is exact
    # against the frozen model, not on some other schedule.
    rc = subprocess.run([sys.executable, CMP, "--run-dir", d],
                        capture_output=True, text=True)
    try:
        exact = json.loads(rc.stdout)
    except json.JSONDecodeError:
        exact = {"verdict": "ERROR", "mismatches": None}
    shutil.rmtree(d, ignore_errors=True)
    return {"sequence": seq, **stats, "ops": ops,
            "exactness_verdict": exact.get("verdict"),
            "exactness_mismatches": exact.get("mismatches")}


def op_laws(m):
    """The measured cost law of this leaf's control plane, per run.

    Each entry is (name, holds). A violated law is a FAIL: the law is what the
    cost record states, so it is checked on every measured run rather than
    asserted once.
    """
    o, r, p = m["ops"], m["routes"], m["control_passes"]
    return [
        ("passes == model-trace control passes", o["passes"] == p),
        ("evals == routes x passes", o["evals"] == r * p),
        ("mul32 == evals (one 32x32 multiply per evaluation)",
         o["mul32"] == o["evals"]),
        ("add64 == evals (one rounding add per evaluation)",
         o["add64"] == o["evals"]),
        ("cmp64 == 2 x evals (two saturation compares per evaluation)",
         o["cmp64"] == 2 * o["evals"]),
        ("add32 == evals (one route-sum accumulation per evaluation)",
         o["add32"] == o["evals"]),
    ]


def cycles_bracket(evals):
    """Candidate cycles for `evals` route evaluations under the two NAMED
    readings. DERIVED, not measured; not a probe; no technology claim."""
    return {"mac_reading": 2 * evals, "alu_reading": 8 * evals}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    args = ap.parse_args()
    art = os.path.abspath(args.artifacts)
    os.makedirs(art, exist_ok=True)
    lines, out = [], {}
    rc_hold = 0          # 3 if something is NOT_RUN / STALE
    ok_all = True

    def log(s=""):
        lines.append(s)
        print(s)

    def bad(s):
        nonlocal ok_all
        ok_all = False
        log(s)

    log("SXT-036 cost accounting against the SXT-015 accounting (#70 "
        "acceptance item 4, second half) -- ORACLE-INDEPENDENT.")
    log("Op counts are MEASURED on the iverilog behavioral schedule. Cycles "
        "are DERIVED under two named readings and reported as a bracket, "
        "never as a probe result. No technology/timing/hardware claim.")
    log("")

    # ------------------------------------------------------------- 0. pins --
    live = live_sxt015()
    drift = pin_drift(live, PIN_SXT015)
    if drift:
        for d in drift:
            print(f"REFUSED (SXT-015 cost model moved): {d}", file=sys.stderr)
        print("Re-RECORD this artifact against the new cost model; never "
              "re-tune the leaf to keep the divergence small.", file=sys.stderr)
        return 2
    got = sha256(GRAPHS)
    if got != GRAPHS_SHA256:
        print(f"REFUSED: graphs.jsonl sha256 {got} != pinned "
              f"{GRAPHS_SHA256}", file=sys.stderr)
        return 2
    log("[pins] SXT-015 cost model: " + ", ".join(
        f"{k}={live[k]}" for k in ("model_version", "cost_profile",
                                   "params_digest", "cyc_modroute_frame")))
    log(f"       graphs.jsonl sha256 {got[:16]}.. == value pinned by #70")
    out["pins"] = {"sxt015": live, "graphs_sha256": got}

    # K4: the pin check is falsifiable (mutated pin must refuse)
    k4 = pin_drift(dict(live, cyc_modroute_frame=live["cyc_modroute_frame"] + 1),
                   PIN_SXT015)
    k5_records = load_probe_records(PROBE_DIR)
    claimed = probes_replacing(k5_records, SXT015_ROW)
    k5_synthetic = probes_replacing(
        [("synthetic-control.json",
          {"sxt015_replacement": {"replaces": SXT015_ROW, "sxt015_value": 15}})],
        SXT015_ROW)
    log(f"[K4 pin-drift control] a mutated cyc_modroute_frame is detected: "
        f"{bool(k4)} -> {'REFUSES as required' if k4 else 'CONTROL BROKEN'}")
    if not k4:
        bad("    K4 did not fire")
    log(f"[K5 probe-claim control] a synthetic probe record claiming to "
        f"replace {SXT015_ROW} is detected: {k5_synthetic} -> "
        f"{'DETECTED as required' if k5_synthetic else 'CONTROL BROKEN'}")
    if not k5_synthetic:
        bad("    K5 did not fire")
    out["controls"] = {"K4_pin_drift": {"fires": bool(k4), "drift": k4},
                       "K5_probe_claim_detector": {"fires": bool(k5_synthetic)}}

    log(f"[SXT-016 coverage] {len(k5_records)} committed probe records; "
        f"records replacing {SXT015_ROW}: {claimed or 'none'}")
    if claimed:
        log(f"    STALE: a probe now pins {SXT015_ROW}. This leaf's "
            "measurement is no longer the only input for that row -- "
            "re-record against the probe before comparing.")
        rc_hold = 3
    else:
        log(f"    {SXT015_ROW} is a `placeholder` param (estimate_ref names "
            "SXT-016) that NO probe replaces. This leaf supplies the first "
            "measured per-route evaluation count for it; it is a refinement "
            "INPUT, not a replacement (only an SXT-016 probe pins a row).")
    out["sxt016_probe_coverage"] = {
        "probe_records": len(k5_records),
        "records_replacing_row": claimed,
        "row": SXT015_ROW,
        "status": "STALE" if claimed else "unpinned_by_any_probe",
    }
    log("")

    work = tempfile.mkdtemp(prefix="sxt036-cost-")
    try:
        # ----------------------------------------- 1. measured cost law -----
        log("MEASURED cost law (tb_vel.sv OPS counters; each run also checked "
            "EXACT against the frozen model as a positive control):")
        log(f"  {'stimulus':26s} {'R':>2s} {'frames':>7s} {'passes':>7s} "
            f"{'evals':>7s} {'mul32':>7s} {'add32':>7s} {'maxV':>4s} "
            f"{'ROM rd':>7s} {'exact':>6s}")
        runs = {}
        for seq in STIMULI:
            m = measure(seq, work, "stim-" + seq)
            runs[seq] = m
            laws = op_laws(m)
            broken = [n for n, ok in laws if not ok]
            log(f"  {seq:26s} {m['routes']:2d} {m['frames']:7d} "
                f"{m['control_passes']:7d} {m['ops']['evals']:7d} "
                f"{m['ops']['mul32']:7d} {m['ops']['add32']:7d} "
                f"{m['max_live_voices']:4d} {m['event_rom_reads']:7d} "
                f"{str(m['exactness_verdict']):>6s}")
            if broken:
                bad(f"    LAW VIOLATED on {seq}: {broken}")
            if m["exactness_verdict"] != "PASS":
                bad(f"    positive control failed on {seq}: "
                    f"{m['exactness_verdict']} "
                    f"mismatches={m['exactness_mismatches']}")
        log("")
        log("  Every run: evals == routes x per-voice control passes, with "
            "exactly 1 mul32 + 1 add64 + 2 cmp64 + 1 add32 per evaluation. "
            "Per-frame work therefore scales with LIVE VOICES, not with the "
            "row count alone.")
        out["measured_runs"] = runs

        # ------------------------------------------- 2. route-table sweep ---
        log("")
        log(f"ROUTE-TABLE SWEEP on {SWEEP_SEQ} (declared sidecar truncated to "
            "its first R routes; depths unchanged):")
        log(f"  {'R':>2s} {'passes':>7s} {'evals':>7s} {'mul32':>7s} "
            f"{'evals-R*passes':>15s} {'exact':>6s}")
        sweep = {}
        for n in SWEEP_ROUTES:
            side = sidecar_with_routes(
                VEL_INPUTS, n, os.path.join(work, f"vel_inputs_r{n}.json"))
            m = measure(SWEEP_SEQ, work, f"sweep-r{n}", vel_inputs=side)
            sweep[n] = m
            if m["routes"] != n:
                bad(f"    sweep R={n} produced {m['routes']} routes")
            delta = m["ops"]["evals"] - n * m["control_passes"]
            log(f"  {n:2d} {m['control_passes']:7d} {m['ops']['evals']:7d} "
                f"{m['ops']['mul32']:7d} {delta:15d} "
                f"{str(m['exactness_verdict']):>6s}")
            if delta != 0:
                bad(f"    LAW VIOLATED at R={n}")
            if m["exactness_verdict"] != "PASS":
                bad(f"    positive control failed at R={n}")
        out["route_table_sweep"] = sweep

        # ------------------------------------------------- 3. K1/K2/K3 ------
        log("")
        log("CONTROLS on the measured law (each must MISPREDICT):")
        base = runs[SWEEP_SEQ]
        # K1: SXT-015's shape ignores live voices -> predict routes x frames
        k1_pred = base["routes"] * base["frames"]
        k1_meas = base["ops"]["evals"]
        k1_fires = base["control_passes"] != base["frames"]
        if not k1_fires:
            log(f"  [K1 per-frame shape] NOT_RUN - stimulus '{SWEEP_SEQ}' has "
                "exactly one control pass per frame, so the two shapes "
                "coincide and the control cannot fire")
            rc_hold = 3
        else:
            ok = k1_pred != k1_meas
            log(f"  [K1 per-frame shape] the retired shape (routes x frames) "
                f"predicts {k1_pred}, measured {k1_meas} -> "
                f"{'MISPREDICTS as required' if ok else 'CONTROL BROKEN'}")
            if not ok:
                bad("    K1 did not fire")
        # worst case over the measured stimuli: the polyphonic fixture
        worst = max(runs.values(), key=lambda m: m["max_live_voices"])
        log(f"      worst measured shape gap: '{worst['sequence']}' peaks at "
            f"{worst['max_live_voices']} live voices, so a voice row's peak "
            f"per-frame work is {worst['max_live_voices']}x what the RETIRED "
            "shape charged for it. Since #239 the accounting charges a voice "
            "row at its own worst-case voice count, so this gap is what the "
            "decision closed, not an outstanding understatement.")
        # K2: a route-count-blind prediction
        fixed = 6
        k2_bad = [n for n, m in sweep.items()
                  if fixed * m["control_passes"] != m["ops"]["evals"]]
        log(f"  [K2 route-count-blind] predicting with a fixed R={fixed} "
            f"mispredicts at R in {sorted(k2_bad)} -> "
            f"{'MISPREDICTS as required' if k2_bad else 'CONTROL BROKEN'}")
        if not k2_bad:
            bad("    K2 did not fire")
        # K3: attribution
        zero = sweep[0]
        k3_ok = (zero["ops"]["evals"] == 0 and zero["ops"]["mul32"] == 0
                 and fixed * zero["frames"] > 0)
        log(f"  [K3 attribution] empty route table measures evals="
            f"{zero['ops']['evals']} mul32={zero['ops']['mul32']} while the "
            f"per-frame prediction is {fixed * zero['frames']} -> "
            + ("all measured multiply work is attributable to the routes"
               if k3_ok else "CONTROL BROKEN"))
        if not k3_ok:
            bad("    K3 did not fire")
        out["controls"].update({
            "K1_per_frame_shape": {"fires": k1_fires,
                                   "predicted": k1_pred, "measured": k1_meas},
            "K2_route_count_blind": {"fires": bool(k2_bad),
                                     "mispredicted_at": sorted(k2_bad)},
            "K3_attribution": {"fires": k3_ok,
                               "evals_at_zero_routes": zero["ops"]["evals"]},
        })

        # ------------------------------- 4. per-evaluation cost + cycles -----
        per_eval = {"mul32": 1, "add64": 1, "cmp64": 2, "add32": 1}
        log("")
        log("MEASURED per-route-evaluation op profile (SXT-016 op taxonomy): "
            + ", ".join(f"{k}={v}" for k, v in per_eval.items()))
        br = cycles_bracket(1)
        log(f"  DERIVED candidate cycles per evaluation (NOT measured, NOT a "
            f"probe): {br['mac_reading']} .. {br['alu_reading']}")
        log(f"    low  reading: {READING_MAC}")
        log(f"    high reading: {READING_ALU}")
        log(f"  SXT-015 charges {live['cyc_modroute_frame']} cycles per row "
            "EVALUATION (#239 shape). The accounted constant is therefore "
            f"{live['cyc_modroute_frame'] / br['alu_reading']:.2f}x to "
            f"{live['cyc_modroute_frame'] / br['mac_reading']:.2f}x the "
            "derived bracket for EVERY row class -- conservative per "
            "evaluation, and now applied to the measured number of "
            "evaluations rather than to the row count (see below). The "
            "constant itself stays a placeholder only SXT-016 may pin.")
        out["per_evaluation"] = {
            "measured_ops": per_eval,
            "derived_cycles_bracket": [br["mac_reading"], br["alu_reading"]],
            "readings": {"low": READING_MAC, "high": READING_ALU},
            "sxt015_cycles_per_row_per_frame": live["cyc_modroute_frame"],
        }

        # ------------------------------------ 5. carriers: shape divergence --
        log("")
        log("SXT-015 ACCOUNTING vs THE MEASURED SHAPE, on the carriers named "
            "by #70 (rows from graphs.jsonl; accounted cycles from "
            "model/resources/accounting.py):")
        from model.resources.accounting import account_graph
        rows = graph_rows(CARRIERS + [FIXTURE_CARRIER])
        log(f"  {'carrier':34s} {'g':>2s} {'sc':>3s} {'vc':>3s} "
            f"{'rows':>4s} {'acct cyc':>9s} {'worstV':>6s} "
            f"{'evals/frame':>11s} {'shape x':>8s}")
        carriers_out = {}
        shape_conformance = {}
        for path in CARRIERS + [FIXTURE_CARRIER]:
            g = rows[path]["g"]
            split = md_row_split(g)
            acct = account_graph(rows[path])
            worst_v = acct["voice"]["worst_case_voices"]
            accounted_cycles = acct["budget"]["cost_cycles_per_frame"]["modulation"]
            evals_per_frame = (split["global"] + split["scene_rows"]
                               + split["voice_rows"] * worst_v)
            # since #239 this is a CONFORMANCE check, not a divergence
            # record: the accounting must charge exactly the measured number
            # of row evaluations. A carrier that stops matching means the
            # shape moved again and this artifact must be re-recorded.
            conforms = (accounted_cycles
                        == evals_per_frame * live["cyc_modroute_frame"])
            shape_conformance[path] = conforms
            if not conforms:
                bad(f"    accounted modulation term for {path} is not "
                    "evaluations x cyc_modroute_frame; the accounting shape "
                    "moved away from the measured law")
            shape_x = evals_per_frame / split["total"] if split["total"] else None
            name = os.path.basename(path)
            log(f"  {name:34s} {split['global']:2d} {split['scene_rows']:3d} "
                f"{split['voice_rows']:3d} {split['total']:4d} "
                f"{accounted_cycles:9.0f} {worst_v:6d} "
                f"{evals_per_frame:11d} "
                f"{('%.2f' % shape_x) if shape_x else '   n/a':>8s}")
            carriers_out[path] = {
                "row_split": split, "worst_case_voices": worst_v,
                "scene_mode": acct["voice"]["scene_mode_name"],
                "accounted_modulation_cycles_per_frame": accounted_cycles,
                "measured_shape_evaluations_per_frame": evals_per_frame,
                "shape_factor": shape_x,
                "accounted_total_cycles_per_frame":
                    acct["budget"]["cost_cycles_per_frame"]["total"],
                "accounted_status": acct.get("status"),
                "derived_cycles_bracket_for_evaluations":
                    list(cycles_bracket(evals_per_frame).values()),
                "accounting_charges_the_measured_shape": conforms,
            }
        log("")
        log("  g = global rows, sc = scene-list rows, vc = voice-list rows "
            "(both of this leaf's sources are PER-VOICE, so their routes are "
            "voice-list rows). 'evals/frame' applies the measured shape at "
            "the accounting's own worst-case voice count; 'shape x' is that "
            "count divided by the ROWS (it is a property of the graph, not of "
            "the accounting, and stays > 1 for every carrier with voice rows).")
        log("  SHAPE: RESOLVED in #239 and cross-checked here. SXT-015 "
            "charges a global/scene row once per frame and a VOICE row once "
            "per worst-case live voice per frame, so 'acct cyc' == "
            "'evals/frame' x cyc_modroute_frame on every carrier above "
            f"({all(shape_conformance.values())}). Before that decision the "
            "accounting charged every row once per frame and understated the "
            "row-evaluation count by the 'shape x' column; that record is in "
            "this file's git history and in reports/sxt-015/EVIDENCE.md.")
        log("  STILL DIVERGING (recorded, not reconciled): the per-EVALUATION "
            f"constant. SXT-015 charges {live['cyc_modroute_frame']} cycles; "
            "the derived bracket above is 2..8. That is a placeholder-vs-"
            "derived gap, not a shape gap, and only an SXT-016 probe may pin "
            f"it (#{FOLLOWUP_ISSUE} explicitly did not). Nothing here is "
            "tuned to make the two agree.")
        log("  Scope limit: the modulation term is a small part of these "
            "accounts (voice cost dominates) and every carrier above is "
            "already `rejected` (budget_overflow) under placeholder-v0, so on "
            "THESE carriers the decision changed a TERM and no fit verdict. "
            "Corpus-wide it did move 9 of 3,561 placeholder-v0 closures, all "
            "within_budget -> OVERFLOW; they are enumerated in "
            "reports/sxt-015/EVIDENCE.md and are not preset-support claims.")
        log(f"  Note on the fixture carrier: {os.path.basename(FIXTURE_CARRIER)}"
            " has NO voice rows of its own, so the shape is invisible on it "
            "(shape x = 1.00) and only appears on the carriers #70 names. "
            "That is why the fixture adds DECLARED synthetic voice routes.")
        out["carriers"] = carriers_out
        out["shape_resolution"] = {
            "decision_issue": FOLLOWUP_ISSUE,
            "accounting_shape": "global/scene-list rows once per frame; "
                                "voice-list rows once per worst-case live "
                                "voice per frame",
            "accounting_charges_the_measured_shape":
                all(shape_conformance.values()),
            "per_carrier": shape_conformance,
            "remaining_divergence": "per-evaluation constant only "
                                    "(cyc_modroute_frame placeholder vs the "
                                    "derived bracket); SXT-016 pins it",
        }

        # -------------------------------------------- 6. state accounting ---
        state_bits = N_SLOTS * SOURCES_PER_SLOT * SOURCE_WORD_BITS
        log("")
        log(f"STATE: {N_SLOTS} slots x {SOURCES_PER_SLOT} source registers x "
            f"{SOURCE_WORD_BITS} b = {state_bits} bits of per-instance source "
            "state (rtl/voice/tb_vel.sv).")
        log("  SXT-015 still has no separate modulation-source state ROW: "
            "modulation rows feed cycles only, and on-chip state is "
            "worst_voices x voice_base_state_bytes + osc + filter + LFO "
            "rows. The ambiguity this leaf recorded (is the per-voice source "
            "register inside that bucket or missing from it?) was DECIDED in "
            f"#{FOLLOWUP_ISSUE}: it is declared INSIDE "
            "voice_base_state_bytes, whose estimate_ref now enumerates the "
            "per-voice modulation-source registers explicitly. The 4096 B "
            "value was NOT re-tuned, and this leaf's 8 B/voice for two "
            "sources is a lower bound on a full source set, never a row "
            "value; SXT-016 re-derives the bucket and may split the row out.")
        # K6: the per-slot count is only meaningful because the shared-register
        # alternative demonstrably FAILS exactness. Read that verdict back from
        # the committed transcript rather than assuming it.
        ctl_path = os.path.join(art, CONTROLS_JSON_REL)
        k6 = {"status": "NOT_RUN",
              "reason": f"{CONTROLS_JSON_REL} absent from {art}"}
        if os.path.exists(ctl_path):
            with open(ctl_path, encoding="utf-8") as f:
                ctl = json.load(f)
            shared = (ctl.get("results", {}).get("rtl-shared-slot") or {})
            fired = bool(shared.get("fails_as_required"))
            mism = (shared.get("exactness") or {}).get("mismatches")
            k6 = {"status": "PASS" if fired else "FAIL",
                  "shared_slot_mutant_mismatches": mism,
                  "source": CONTROLS_JSON_REL}
            log(f"  [K6 state cross-check] committed control transcript: the "
                f"scene-wide (shared) register mutant FAILS exactness with "
                f"{mism} mismatches -> the {state_bits}-bit per-instance "
                f"count is load-bearing, not padding"
                if fired else
                "  [K6 state cross-check] the shared-register mutant is NOT "
                "recorded as failing in the committed transcript")
            if not fired:
                bad("    K6 did not fire")
        else:
            log(f"  [K6 state cross-check] NOT_RUN - {k6['reason']}; the "
                f"{state_bits}-bit figure is reported without its control "
                "here (run tools/vel_negative_controls.py first)")
            rc_hold = 3
        out["state"] = {"per_instance_state_bits": state_bits,
                        "slots": N_SLOTS,
                        "sxt015_modulation_state_row": None,
                        "sxt015_modulation_state_disposition": {
                            "decision_issue": FOLLOWUP_ISSUE,
                            "decided": "declared inside "
                                       "voice_base_state_bytes (no separate "
                                       "row); value unchanged at 4096 B",
                            "retires_when": "SXT-016 re-derives the voice "
                                            "state bucket at the selected "
                                            "word lengths",
                        },
                        "K6_shared_register_control": k6}
        out["controls"]["K6_state_cross_check"] = k6

        # ------------------------------------- 7. costs.txt cross-check -----
        log("")
        log("CROSS-CHECK of the first increment's hand-assembled "
            "artifacts/costs.txt (a change here makes that file STALE):")
        with open(SCHEDULER_PROBE, encoding="utf-8") as f:
            probe = json.load(f)
        rederived = {
            "qmul_per_running_voice_block":
                base["ops"]["mul32"] // base["control_passes"],
            "per_slot_state_bits": state_bits,
            "probe_cycles_per_event": probe["cycles_per_event"],
            "probe_state_ram_bits": probe["state_ram_bits"],
        }
        stale = {k: (PIN_COSTS_TXT[k], rederived[k])
                 for k in PIN_COSTS_TXT if PIN_COSTS_TXT[k] != rederived[k]}
        for k in sorted(PIN_COSTS_TXT):
            log(f"  {k}: costs.txt {PIN_COSTS_TXT[k]} vs re-derived "
                f"{rederived[k]} -> {'OK' if k not in stale else 'STALE'}")
        if stale:
            log("  STALE: costs.txt must be re-recorded against these values.")
            rc_hold = 3
        out["costs_txt_cross_check"] = {"quoted": PIN_COSTS_TXT,
                                        "rederived": rederived,
                                        "stale": stale}

        # ----------------------------------------------------- 8. verdict ---
        log("")
        log("Not established here: model-vs-pinned-engine dry-render budgets "
            "(item 2) and the reference-budget negative controls (item 5) "
            "remain NOT_RUN - pinned oracle unavailable on dispatch host "
            "(#96/#232). Cycles above are derived under named assumptions, "
            "never measured; no synthesis, timing or hardware claim. "
            "Supported-preset delta from this leaf stays 0.")
        if not ok_all:
            verdict = "FAIL"
        elif rc_hold == 3:
            verdict = ("PASS for every law and control that ran; at least one "
                       "item NOT_RUN/STALE and recorded as such")
        else:
            verdict = ("PASS (every measured law held, every control fired, "
                       "divergences recorded)")
        log(f"VERDICT: {verdict}")
        out["followup_issue"] = FOLLOWUP_ISSUE
        out["verdict"] = ("FAIL" if not ok_all else
                          "PASS_WITH_NOT_RUN" if rc_hold == 3 else "PASS")
        out["oracle_dependent_items"] = {"2": "NOT_RUN", "5": "NOT_RUN"}
    finally:
        shutil.rmtree(work, ignore_errors=True)

    with open(os.path.join(art, "cost-accounting.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(art, "cost-accounting.json"), "w",
              encoding="utf-8") as f:
        json.dump({"tool": "vel_cost_accounting/1", **out}, f, indent=2)
        f.write("\n")
    if not ok_all:
        return 1
    return rc_hold


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)
