#!/usr/bin/env python3
"""SXT-030 (#316): simulation bench + NC-1 validity gate for the
external-memory service/stall instrumentation.

Runs `rtl/instrumentation/tb_ext_mem_instr.sv` against
`rtl/instrumentation/ext_mem_instr.sv` (or a committed mutant of it) under
Icarus Verilog, parses the raw witnesses the bench writes, and grades them
against the validity gate of `docs/fpga-capture-calibration-procedure.md`
§9.2 exactly as written there:

  * the in-budget control run (L0, nominal service window) shows
    STALL_FRAMES == 0 and PASSes its comparison; and
  * the over-subscribed run shows all three witnesses firing (counters,
    stall_strobe on the frame timebase, audio-domain comparison); and
  * the three witnesses agree on the frame range; and
  * the over-subscribed output is not silent (held-sample policy).
  * counters fire but the audio comparison passes  -> not a PASS (too weak)
  * output degraded or silent with STALL_FRAMES == 0 -> NO_VERDICT

plus the take-integrity checks §9.1 implies (BUILD_ID read back and compared
with the expected identity, FRAME_COUNT against the bench's own frame count,
EXT_WORDS_* against the memory model's own access count); a take that fails
integrity is NO_VERDICT — the instrumentation is the suspect.

SCOPE: simulation only. The "audio-domain comparison" here is the bench's
exact per-frame comparison of the DUT output against a Python prediction of
the stub fixture's normal-path samples (the simulation analogue of the
Phase-D exactness leg; the Phase-A analog checks have no simulation analogue
beyond the dropout/stuck screens recorded here). No hardware measurement,
latency/underrun figure, synthesis result or qualification claim is made by
anything this tool writes. Every cycle figure is a consequence of the
declared simulation parameters below, not a measurement of any device.

Usage:
  python3 tools/sxt030_stall_bench.py            # print the results JSON
  python3 tools/sxt030_stall_bench.py --write    # also write
                                                 # reports/SXT-030/bench-results.json

Original to this repository (Apache-2.0). No Surge-derived material.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tools._rtl_compile_common import scan_stdout_for_load_failures  # noqa: E402,E501

RTL_DIR = os.path.join(REPO, "rtl", "instrumentation")
TB = os.path.join(RTL_DIR, "tb_ext_mem_instr.sv")
DUT = os.path.join(RTL_DIR, "ext_mem_instr.sv")
MUTANTS = {
    "silence_on_miss": os.path.join(
        RTL_DIR, "ext_mem_instr_silence_mutant.sv"),
    "zero_counters": os.path.join(
        RTL_DIR, "ext_mem_instr_zero_counters_mutant.sv"),
    "silence_zero_counters": os.path.join(
        RTL_DIR, "ext_mem_instr_silence_zero_counters_mutant.sv"),
    "throttle_never_engages": os.path.join(
        RTL_DIR, "ext_mem_instr_throttle_never_mutant.sv"),
}
RESULTS = os.path.join(REPO, "reports", "SXT-030", "bench-results.json")

# Declared simulation parameters (mirrors of the RTL/bench defaults).
CYCLES_PER_FRAME = 1000      # 48 MHz candidate core clock / 48 kHz frame
SVC_RESERVE = 8
SVC_WINDOW_NOMINAL = 960
MEM_LAT = 3                  # -> 4 core cycles per 32-bit word (E2 class)
FIX_WORDS = 6                # stub fixture: 4 reads + 2 writes per frame
HOLD_RESET = 0x4000
CFG_DEPTH = 1026             # tb cfg[] depth

# register map (word addresses)
REG = {
    "BUILD_ID": 0x00, "CTRL": 0x01, "STATUS": 0x02, "FRAME_COUNT": 0x03,
    "EXT_WORDS_RD": 0x04, "EXT_WORDS_WR": 0x05, "SVC_OCCUPANCY_MAX": 0x06,
    "STALL_FRAMES": 0x07, "STALL_CYCLES_MAX": 0x08,
    "FIRST_STALL_FRAME": 0x09, "LOADGEN_WORDS_PER_FRAME": 0x0A,
    "SVC_WINDOW_LIMIT": 0x0B,
    "EXT_WORDS_RD_TAG0": 0x10, "EXT_WORDS_RD_TAG1": 0x11,
    "EXT_WORDS_RD_TAG2": 0x12,
    "EXT_WORDS_WR_TAG0": 0x14, "EXT_WORDS_WR_TAG1": 0x15,
    "EXT_WORDS_WR_TAG2": 0x16,
}
ADDR_NAME = {v: k for k, v in REG.items()}
STATUS_BITS = {"OUTPUT_FAULT": 0, "FIRST_STALL_VALID": 1, "STALL_LED": 2,
               "STALL_FRAMES_SATURATED": 3}
COUNTERS = ("FRAME_COUNT", "EXT_WORDS_RD", "EXT_WORDS_WR",
            "SVC_OCCUPANCY_MAX", "STALL_FRAMES", "STALL_CYCLES_MAX",
            "FIRST_STALL_FRAME", "EXT_WORDS_RD_TAG0", "EXT_WORDS_RD_TAG1",
            "EXT_WORDS_RD_TAG2", "EXT_WORDS_WR_TAG0", "EXT_WORDS_WR_TAG1",
            "EXT_WORDS_WR_TAG2")

# §9.2 M1 ladder: words/frame added (4-byte accesses)
LADDER = (("L0", 0), ("L1", 174), ("L2", 348), ("L3", 696),
          ("L4", 1392), ("L5", 2784))
M2_TIGHT_WINDOW = 16         # < 24 cycles the 6-word fixture provably needs

M32 = 0xFFFFFFFF


# ------------------------------------------------------------ prediction
def scatter(tag, n, j):
    """Mirror of ext_mem_instr.sv `scatter`."""
    h = (((tag << 30) ^ (n << 12) ^ j) & M32) * 0x9E3779B1 & M32
    h ^= h >> 15
    return h & 0xFFFFFF


def mem_data(a):
    """Mirror of tb_ext_mem_instr.sv `mem_data`."""
    h = (a * 0x2545F491) & M32
    return (h ^ (h >> 13)) & M32


def predict(n):
    """Normal-path (l, r) sample of frame n for the stub fixture."""
    out = []
    for tag in (0, 1):
        d0 = mem_data(scatter(tag, n, 0))
        d1 = mem_data(scatter(tag, n, 1))
        s = (((d0 & 0xFFFF) ^ (d1 >> 16)) + (n & 0xFFFF)) & 0xFFFF
        out.append(s | 1)
    return tuple(out)


def build_id_of(dut_path):
    """Build-identity nonce: first 32 bits of sha256 over the DUT bytes."""
    with open(dut_path, "rb") as f:
        return int(hashlib.sha256(f.read()).hexdigest()[:8], 16)


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ------------------------------------------------------------ cases
def _window(frame, value):
    return (frame, REG["SVC_WINDOW_LIMIT"], value)


def _loadgen(frame, value):
    return (frame, REG["LOADGEN_WORDS_PER_FRAME"], value)


def ladder_case(words):
    return {"nframes": 16, "writes": [_loadgen(4, words), _loadgen(12, 0)],
            "commanded_frames": list(range(4, 12)) if words else [],
            "mechanism": "M1"}


CASES = {
    "in_budget": {"nframes": 24, "writes": [], "commanded_frames": [],
                  "mechanism": None},
    "m2_throttle": {"nframes": 24,
                    "writes": [_window(8, M2_TIGHT_WINDOW),
                               _window(16, SVC_WINDOW_NOMINAL)],
                    "commanded_frames": list(range(8, 16)),
                    "mechanism": "M2"},
    "edge_stall_in_frame0": {"nframes": 6,
                             "writes": [_window(0, M2_TIGHT_WINDOW),
                                        _window(3, SVC_WINDOW_NOMINAL)],
                             "commanded_frames": [0, 1, 2],
                             "mechanism": "M2"},
    "edge_two_bursts": {"nframes": 16,
                        "writes": [_window(3, M2_TIGHT_WINDOW),
                                   _window(5, SVC_WINDOW_NOMINAL),
                                   _window(9, M2_TIGHT_WINDOW),
                                   _window(12, SVC_WINDOW_NOMINAL)],
                        "commanded_frames": [3, 4, 9, 10, 11],
                        "mechanism": "M2"},
    "edge_saturation_stall_w3": {"nframes": 16, "stall_w": 3,
                                 "writes": [_window(2, M2_TIGHT_WINDOW),
                                            _window(14, SVC_WINDOW_NOMINAL)],
                                 "commanded_frames": list(range(2, 14)),
                                 "mechanism": "M2"},
}


# ------------------------------------------------------------ simulation
def iverilog_version():
    if shutil.which("iverilog") is None:
        return None
    out = subprocess.run(["iverilog", "-V"], capture_output=True, text=True,
                         check=False)
    return (out.stdout or out.stderr).splitlines()[0].strip()


def write_cfg(path, case):
    writes = sorted(case["writes"], key=lambda w: w[0])
    lines = [case["nframes"], len(writes)]
    lines += [(f << 40) | (a << 32) | (v & M32) for f, a, v in writes]
    lines += [0] * (CFG_DEPTH - len(lines))
    with open(path, "w") as f:
        for w in lines:
            f.write("%016x\n" % w)


def run_take(case, dut, workdir):
    """Compile and run one take; return the parsed raw witnesses."""
    os.makedirs(workdir, exist_ok=True)
    write_cfg(os.path.join(workdir, "cfg.hex"), case)
    bid = build_id_of(dut)
    stall_w = case.get("stall_w", 32)
    vvp = os.path.join(workdir, "tb.vvp")
    sim_fails = []
    cmd = ["iverilog", "-g2012",
           "-Ptb_ext_mem_instr.BUILD_ID=%d" % bid,
           "-Ptb_ext_mem_instr.STALL_W=%d" % stall_w,
           "-o", vvp, TB, os.path.abspath(dut)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        res = subprocess.run(["vvp", vvp], cwd=workdir, capture_output=True,
                             text=True, timeout=600, check=False)
        if res.returncode != 0:
            sim_fails.append("vvp exit %d" % res.returncode)
        sim_fails += scan_stdout_for_load_failures(res.stdout)
        if "SXT030_BENCH_DONE" not in res.stdout:
            sim_fails.append("bench did not reach its end marker")
    except subprocess.CalledProcessError as e:
        sim_fails.append("iverilog compile failed: %s" % (e.stderr or "")[-500:])
    except subprocess.TimeoutExpired:
        sim_fails.append("vvp timeout")
    parsed = {"sim_fails": sim_fails, "build_id_built": bid,
              "stall_w": stall_w}
    if sim_fails:
        return parsed
    parsed.update(parse_trace(os.path.join(workdir, "bench_trace.txt")))
    return parsed


def parse_trace(path):
    dumps = {0: {}, 1: {}, 2: {}}
    frames, strobes, orphans, errors = [], [], [], []
    mem = {}
    led = None
    z = None
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "D":
                dumps[int(p[1])][ADDR_NAME[int(p[2])]] = int(p[3])
            elif p[0] == "F":
                frames.append((int(p[1]), int(p[2]), int(p[3])))
            elif p[0] == "S":
                strobes.append(int(p[1]))
            elif p[0] == "Q":
                orphans.append(int(p[1]))
            elif p[0] == "M":
                mem[(int(p[1]), int(p[2]))] = int(p[3])
            elif p[0] == "L":
                led = int(p[1])
            elif p[0] == "E":
                errors.append(" ".join(p[1:]))
            elif p[0] == "Z":
                z = (int(p[1]), int(p[2]))
    return {"before": dumps[0], "after": dumps[1], "reset": dumps[2],
            "frames": frames, "strobes": strobes, "orphan_strobes": orphans,
            "mem": mem, "led": led, "errors": errors, "z": z}


# ------------------------------------------------------------ witnesses
def _status(v, bit):
    return (v >> STATUS_BITS[bit]) & 1


def witnesses(take, case, expected_build_id):
    """Reduce one parsed take to the three witnesses + integrity findings."""
    w = {"integrity": [], "nframes": case["nframes"]}
    if take["sim_fails"]:
        w["integrity"] = ["simulator: " + s for s in take["sim_fails"]]
        return w
    b, a, r = take["before"], take["after"], take["reset"]
    frames = take["frames"]

    # ---- integrity (instrumentation self-consistency; NO_VERDICT if not)
    integ = w["integrity"]
    if a.get("BUILD_ID") != expected_build_id:
        integ.append("BUILD_ID read back %r != expected %r"
                     % (a.get("BUILD_ID"), expected_build_id))
    for name in COUNTERS:
        if b.get(name, 0) != 0:
            integ.append("%s nonzero before the take (%d)" % (name, b[name]))
    if b.get("STATUS", 0) != 0:
        integ.append("STATUS nonzero before the take")
    if len(frames) != case["nframes"] or \
            [f[0] for f in frames] != list(range(case["nframes"])):
        integ.append("bench saw %d frames, take commanded %d"
                     % (len(frames), case["nframes"]))
    fc = a["FRAME_COUNT"] - b["FRAME_COUNT"]
    if fc != len(frames):
        integ.append("FRAME_COUNT delta %d != frames on the timebase %d"
                     % (fc, len(frames)))
    mem = take["mem"]
    mem_rd = sum(mem.get((0, t), 0) for t in range(4))
    mem_wr = sum(mem.get((1, t), 0) for t in range(4))
    if a["EXT_WORDS_RD"] - b["EXT_WORDS_RD"] != mem_rd:
        integ.append("EXT_WORDS_RD delta != memory-model reads %d" % mem_rd)
    if a["EXT_WORDS_WR"] - b["EXT_WORDS_WR"] != mem_wr:
        integ.append("EXT_WORDS_WR delta != memory-model writes %d" % mem_wr)
    for t in range(3):
        if a["EXT_WORDS_RD_TAG%d" % t] != mem.get((0, t), 0):
            integ.append("EXT_WORDS_RD_TAG%d != memory model" % t)
        if a["EXT_WORDS_WR_TAG%d" % t] != mem.get((1, t), 0):
            integ.append("EXT_WORDS_WR_TAG%d != memory model" % t)
    if mem_rd == 0:
        integ.append("no external traffic at all (EXT_WORDS_RD == 0)")
    integ += ["bench: " + e for e in take["errors"]]
    if take["orphan_strobes"]:
        integ.append("stall_strobe off the frame timebase at cycles %r"
                     % take["orphan_strobes"][:5])
    reset_bad = [n for n in COUNTERS + ("STATUS", "CTRL",
                                        "LOADGEN_WORDS_PER_FRAME")
                 if r.get(n, 0) != 0]
    if reset_bad or r.get("SVC_WINDOW_LIMIT") != SVC_WINDOW_NOMINAL:
        integ.append("post-take reset did not clear %r" % reset_bad)

    # ---- witness 1: counters (deltas over the take)
    st = a["STATUS"]
    w["counters"] = {
        "STALL_FRAMES": a["STALL_FRAMES"] - b["STALL_FRAMES"],
        "STALL_CYCLES_MAX": a["STALL_CYCLES_MAX"],
        "FIRST_STALL_FRAME": a["FIRST_STALL_FRAME"],
        "FIRST_STALL_VALID": _status(st, "FIRST_STALL_VALID"),
        "OUTPUT_FAULT": _status(st, "OUTPUT_FAULT"),
        "STALL_LED_STATUS": _status(st, "STALL_LED"),
        "STALL_FRAMES_SATURATED": _status(st, "STALL_FRAMES_SATURATED"),
        "FRAME_COUNT": fc,
        "EXT_WORDS_RD": a["EXT_WORDS_RD"] - b["EXT_WORDS_RD"],
        "EXT_WORDS_WR": a["EXT_WORDS_WR"] - b["EXT_WORDS_WR"],
        "EXT_WORDS_RD_TAG": [a["EXT_WORDS_RD_TAG%d" % t] for t in range(3)],
        "EXT_WORDS_WR_TAG": [a["EXT_WORDS_WR_TAG%d" % t] for t in range(3)],
        "SVC_OCCUPANCY_MAX": a["SVC_OCCUPANCY_MAX"],
        "BUILD_ID": a["BUILD_ID"],
    }
    c = w["counters"]
    w["counters_fire"] = bool(c["STALL_FRAMES"] > 0 and c["FIRST_STALL_VALID"]
                              and c["STALL_CYCLES_MAX"] > 0
                              and c["OUTPUT_FAULT"])

    # ---- witness 2: hardware strobe on the frame timebase (+ latching LED)
    w["strobe_frames"] = sorted(take["strobes"])
    w["stall_led_pin"] = take["led"]
    w["strobe_fire"] = bool(w["strobe_frames"]) and take["led"] == 1

    # ---- witness 3: audio-domain comparison against the prediction
    residual, silent, stuck = [], [], []
    prev = None
    for n, lft, rgt in frames:
        if (lft, rgt) != predict(n):
            residual.append(n)
        if lft == 0 or rgt == 0:
            silent.append(n)
        if prev is not None and (lft, rgt) == prev:
            stuck.append(n)
        prev = (lft, rgt)
    # held-sample policy (§9.1): every frame the strobe marks as a miss must
    # repeat the previous frame's output exactly (HOLD_RESET in frame 0) --
    # not silence, not a quiet or faded substitute
    out = {n: (lft, rgt) for n, lft, rgt in frames}
    held_bad = []
    for n in take["strobes"]:
        want = out.get(n - 1, (HOLD_RESET, HOLD_RESET))
        if out.get(n) != want:
            held_bad.append(n)
    w["held_policy_violations"] = held_bad
    w["residual_frames"] = residual
    w["dropout_frames"] = silent
    w["stuck_frames"] = stuck
    w["comparison"] = "PASS" if not residual else "FAIL"
    w["audio_fire"] = bool(residual)
    w["silent"] = bool(silent)
    w["commanded_frames"] = case["commanded_frames"]
    return w


def agreement(w):
    """Do the three witnesses localize the same frames? -> list of issues."""
    issues = []
    c = w["counters"]
    s, a = w["strobe_frames"], w["residual_frames"]
    if s != a:
        issues.append("strobe frames %r != residual frames %r" % (s, a))
    if s and c["FIRST_STALL_FRAME"] != s[0]:
        issues.append("FIRST_STALL_FRAME %d != first strobe frame %d"
                      % (c["FIRST_STALL_FRAME"], s[0]))
    if c["STALL_FRAMES_SATURATED"]:
        if len(s) < c["STALL_FRAMES"]:
            issues.append("saturated STALL_FRAMES %d exceeds strobes %d"
                          % (c["STALL_FRAMES"], len(s)))
    elif c["STALL_FRAMES"] != len(s):
        issues.append("STALL_FRAMES %d != strobe count %d"
                      % (c["STALL_FRAMES"], len(s)))
    return issues


def nc1_gate(inb, over):
    """§9.2 validity gate over an in-budget and an over-subscribed take."""
    reasons = []
    for label, w in (("in_budget", inb), ("over", over)):
        if w["integrity"]:
            return {"verdict": "NO_VERDICT",
                    "reasons": ["%s take integrity: %s" % (label, i)
                                for i in w["integrity"]]}
    for label, w in (("in_budget", inb), ("over", over)):
        if (w["audio_fire"] or w["silent"]) and \
                w["counters"]["STALL_FRAMES"] == 0:
            return {"verdict": "NO_VERDICT", "reasons": [
                "%s take: output degraded/silent with STALL_FRAMES == 0 -- "
                "the instrumentation is the suspect (§9.2)" % label]}
    ic = inb["counters"]
    if ic["STALL_FRAMES"] != 0:
        reasons.append("in-budget STALL_FRAMES %d != 0" % ic["STALL_FRAMES"])
    if inb["strobe_frames"] or inb["stall_led_pin"]:
        reasons.append("in-budget run raised stall_strobe/LED")
    if ic["OUTPUT_FAULT"]:
        reasons.append("in-budget run set OUTPUT_FAULT")
    if inb["comparison"] != "PASS":
        reasons.append("in-budget comparison FAIL")
    if reasons:
        return {"verdict": "FAIL", "reasons": reasons}
    if over["counters_fire"] and not over["audio_fire"]:
        return {"verdict": "FAIL", "reasons": [
            ("counters fire but the audio comparison passes: the control is "
             "too weak -- strengthen it (§9.2); not a PASS")]}
    for k, name in (("counters_fire", "counters"), ("strobe_fire", "strobe"),
                    ("audio_fire", "audio comparison")):
        if not over[k]:
            reasons.append("over-subscribed witness did not fire: " + name)
    if reasons:
        return {"verdict": "FAIL", "reasons": reasons}
    reasons += agreement(over)
    if over["held_policy_violations"]:
        reasons.append("stalled frames %r do not hold the previous frame's "
                       "sample (§9.1 deadline-miss policy)"
                       % over["held_policy_violations"][:8])
    if over["silent"]:
        reasons.append("over-subscribed output is silent at frames %r -- "
                       "the held-sample policy is violated"
                       % over["dropout_frames"][:8])
    if reasons:
        return {"verdict": "FAIL", "reasons": reasons}
    return {"verdict": "PASS", "reasons": []}


# ------------------------------------------------------------ driver
def _summ(w):
    keep = ("integrity", "counters", "counters_fire", "strobe_frames",
            "stall_led_pin", "strobe_fire", "residual_frames",
            "dropout_frames", "stuck_frames", "comparison", "audio_fire",
            "silent", "held_policy_violations", "commanded_frames")
    return {k: w[k] for k in keep if k in w}


def run_all(workroot):
    """Every take and gate of the bench; returns the results dict."""
    def take(name, case, dut):
        t = run_take(case, dut, os.path.join(workroot, name))
        return witnesses(t, case, build_id_of(dut))

    res = {"takes": {}, "gates": {}, "ladder": {}, "controls": {}}
    real = {}
    for name, case in CASES.items():
        real[name] = take("real-" + name, case, DUT)
        res["takes"][name] = _summ(real[name])

    res["gates"]["NC1_M2"] = nc1_gate(real["in_budget"],
                                      real["m2_throttle"])
    for name in ("edge_stall_in_frame0", "edge_two_bursts",
                 "edge_saturation_stall_w3"):
        res["gates"]["NC1_" + name] = nc1_gate(real["in_budget"], real[name])

    # M1 ladder: climb until STALL_FRAMES > 0 (§9.2)
    rungs, first = [], None
    for rung, words in LADDER:
        w = take("real-m1-" + rung, ladder_case(words), DUT)
        rungs.append({"rung": rung, "words_per_frame_added": words,
                      "bytes_per_s_added": words * 4 * 48000,
                      "stall_frames": w.get("counters", {}).get(
                          "STALL_FRAMES"),
                      "comparison": w.get("comparison"),
                      "take": _summ(w)})
        if w.get("counters", {}).get("STALL_FRAMES", 0) > 0:
            first = (rung, w)
            break
    res["ladder"] = {"rungs": rungs,
                     "first_stalling_rung": first[0] if first else None}
    res["gates"]["NC1_M1"] = (nc1_gate(real["in_budget"], first[1]) if first
                              else {"verdict": "FAIL", "reasons": [
                                  "ladder exhausted without a stall"]})

    # live negative controls: each mutant on the in-budget + M2 takes
    expected = {"silence_on_miss": "FAIL", "zero_counters": "NO_VERDICT",
                "silence_zero_counters": "NO_VERDICT",
                "throttle_never_engages": "FAIL"}
    for name, path in MUTANTS.items():
        inb = take("mut-%s-in_budget" % name, CASES["in_budget"], path)
        ovr = take("mut-%s-m2" % name, CASES["m2_throttle"], path)
        g = nc1_gate(inb, ovr)
        res["controls"][name] = {
            "dut": os.path.relpath(path, REPO),
            "gate": g, "expected_gate": expected[name],
            "control_status": "PASS" if g["verdict"] == expected[name]
                              else "FAIL",
            "over_take": _summ(ovr)}
    # build-identity mismatch: the real M2 take graded against a wrong id
    bad_case = CASES["m2_throttle"]
    t = run_take(bad_case, DUT, os.path.join(workroot, "real-m2-badid"))
    bad = witnesses(t, bad_case, build_id_of(DUT) ^ 0x1)
    g = nc1_gate(real["in_budget"], bad)
    res["controls"]["build_id_mismatch"] = {
        "dut": os.path.relpath(DUT, REPO), "gate": g,
        "expected_gate": "NO_VERDICT",
        "control_status": "PASS" if g["verdict"] == "NO_VERDICT" else "FAIL"}
    return res


def results_record(res):
    srcs = [TB, DUT] + list(MUTANTS.values())
    return {
        "schema": "sxt030-stall-bench/1",
        "issue": 316,
        "scope": ("SIMULATION ONLY (Icarus Verilog). No hardware measurement, "
                  "latency/underrun figure, synthesis/timing/power result, "
                  "or qualification claim."),
        "declared_parameters": {
            "cycles_per_frame": CYCLES_PER_FRAME,
            "svc_reserve_cycles": SVC_RESERVE,
            "svc_window_nominal": SVC_WINDOW_NOMINAL,
            "m2_tight_window": M2_TIGHT_WINDOW,
            "mem_latency_cycles": MEM_LAT,
            "cycles_per_word": MEM_LAT + 1,
            "fixture_words_per_frame": FIX_WORDS,
            "hold_reset_sample": HOLD_RESET,
        },
        "sources_sha256": {os.path.relpath(p, REPO): sha256_file(p)
                           for p in srcs},
        "results": res,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    ver = iverilog_version()
    if ver is None:
        print(json.dumps({"status": "NOT_RUN",
                          "reason": "iverilog not available"}))
        return 2
    work = tempfile.mkdtemp(prefix="sxt030-")
    try:
        rec = results_record(run_all(work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    text = json.dumps(rec, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    print("simulator: %s" % ver, file=sys.stderr)
    if args.write:
        os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
        with open(RESULTS, "w") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
