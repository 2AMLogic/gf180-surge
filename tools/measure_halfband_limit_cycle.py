#!/usr/bin/env python3
"""F-176-2 (#181): measure the shared `HalfbandD2` zero-input limit cycle.

WHAT THIS IS. `model/voice/voice_model.py::HalfbandD2` -- the shared Q10.21
scene decimator modelling `sst::filters::HalfRate::HalfRateFilter(M=6, steep)
::process_block_D2` -- does not settle to zero on zero input. The allpass
recursion

    y[n] = x[n-2] + a * (x[n] - y[n-2])

under round-half-up `qmul` has a dead band, so the filter's zero-input state
can enter a non-decaying cycle instead of decaying to the zero state. #176
found one instance of this (an impulse settling to +/-26 Q10.21 LSB) and
recorded it as F-176-2 in `reports/sxt-026/EVIDENCE.md` section 2a. One
impulse is not a bound. This tool measures the settled amplitude across a
DECLARED input sweep, and it measures it EXACTLY rather than by observing a
long tail:

  * every case drives the filter with a declared stimulus and then cuts the
    input to zero;
  * during the silence the filter's FULL state (bx/by/ax/ay, 72 words) is
    hashed after every engine block; when a state recurs, the block sequence
    between the two occurrences repeats forever BY CONSTRUCTION (the zero-input
    map is deterministic), so the recorded settled amplitude is a proof, not an
    extrapolation from "it was still there after N frames";
  * the reported period is reduced to the minimal output period of that cycle.

A case that does not reach a recurrence inside `--max-silence-blocks` is
reported as NO_VERDICT (`settled_peak_q21: null`), never as zero, and makes the
tool exit non-zero.

WHAT THIS IS NOT. This is a property of the frozen fixed-point model, measured
on the frozen model. No reference render is read, no pinned engine is executed,
no budget is graded, and nothing here is a fidelity, preset-support or
musical-quality claim. The pinned float kernel has no limit cycle at all (see
`reports/halfband-branch-order/` and `tools/halfband_d2_ordering_probe.py`);
that difference is a word-length consequence of the Q10.21 freeze, and the
size of it is exactly what is measured here.

DECLARED INPUT RANGE. Every consumer of the shared decimator clips its input
to +/-8.0 (the engine's `sceneout` hard clip) immediately before the decimator
-- `model/voice/run_model.py` (limit_i +/- qint(8.0)) and `rtl/voice/
tb_voice.sv` (clamp8) -- so the declared input range of this measurement is
|x| <= 8.0 in Q10.21, and the sweep includes the range end.

LEGS
  sweep     (always) the declared stimulus sweep, per-case settled amplitude
            and the stated worst case.
  control   (always) REQUIRED failure control: the same sweep with a decimator
            whose state is zeroed at every block boundary must settle to 0 on
            every case. If it does not, the harness is not observing the
            filter's own state and the sweep means nothing. The control also
            fails closed if the uncontrolled sweep found no non-zero case at
            all (nothing was being observed in the first place).
  contrast  (always) the SAME recursion and the SAME quoted coefficients in
            float64 instead of Q10.21, on the same cases, to show the cycle is
            a word-length consequence of the freeze rather than a property of
            the recursion. This is a float EMULATION of the recursion, NOT the
            pinned kernel: executing the pinned kernel needs the external
            oracle host (`oracle/sxt022/build_halfband_probe.sh`), and when
            that is unavailable the pinned-kernel comparison is NOT_RUN, not
            assumed.
  rtl       (--rtl) the three RTL copies of the decimator
            (`rtl/voice/tb_voice.sv`, `rtl/oscillators/classic/tb_classic.sv`,
            `rtl/oscillators/sine/tb_sine.sv`) are checked, not assumed, to
            reproduce the same settled amplitude: their cascade text is
            extracted VERBATIM, compared across the three files, spliced into a
            generated probe testbench together with tb_voice.sv's own verbatim
            `qmul`/`qround1`, run under iverilog, and compared to the model
            sample-for-sample over the whole run INCLUDING the settled tail.
  leaves    (--leaves) in situ: for each affected leaf, whether the region
            after the last voice dies is inside the leaf's committed
            RTL-vs-model compared window, and whether a live limit cycle is
            present there. `--leaf-rtl` additionally runs each leaf's own
            committed comparator (needs iverilog; ~30 s per leaf).

Usage:
  python3 tools/measure_halfband_limit_cycle.py \\
      --rtl --leaves --leaf-rtl \\
      --out reports/halfband-limit-cycle/artifacts/zero-input-limit-cycle-sweep.json

Original to this repository (Apache-2.0).
"""

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import voice_model as vm  # noqa: E402
from _rtl_compile_common import compile_and_run  # noqa: E402

FORMAT = "sxt-halfband-zero-input-limit-cycle/1"
ISSUE = 181

BLOCK_OS = vm.BLOCK_SIZE_OS              # 64 input (96 kHz) samples per block
BLOCK = vm.BLOCK_SIZE                    # 32 output (48 kHz) samples per block
CLIP8 = vm.qint(8.0)                     # declared input range end
INT16_LSB_Q21 = vm.ONE // 32768          # 64 Q10.21 LSB == one int16 LSB

DRIVE_BLOCKS = 32                        # 2048 input samples of stimulus
MAX_SILENCE_BLOCKS = 4096                # fail-closed cap (262,144 samples)


# --------------------------------------------------------------- stimuli ---

def _clip(v):
    return -CLIP8 if v < -CLIP8 else (CLIP8 if v > CLIP8 else v)


def stim_impulse(amp, n):
    xs = [0] * n
    xs[0] = _clip(vm.qint(amp))
    return xs


def stim_dc(amp, n):
    return [_clip(vm.qint(amp))] * n


def stim_sine(amp, f, n):
    return [_clip(vm.qint(amp * math.sin(2.0 * math.pi * f * i)))
            for i in range(n)]


def stim_square(amp, f, n):
    a = _clip(vm.qint(amp))
    return [a if math.sin(2.0 * math.pi * f * i) >= 0.0 else -a
            for i in range(n)]


def stim_two_tone(amp, f1, f2, n):
    return [_clip(vm.qint(amp * (math.sin(2.0 * math.pi * f1 * i)
                                 + math.sin(2.0 * math.pi * f2 * i))))
            for i in range(n)]


def stim_noise(amp, seed, n):
    rng = random.Random(seed)
    return [_clip(vm.qint(rng.uniform(-amp, amp))) for _ in range(n)]


# Amplitudes span one Q10.21 LSB to the declared range end (+/-8, the sceneout
# clip). 1/2097152 is exactly 1 LSB; 8.0 is the clip itself.
AMPS = [1.0 / vm.ONE, 1e-4, 1e-3, 0.01, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]

# Frequencies as a fraction of the DECIMATOR INPUT rate (96 kHz). The filter's
# transition is at 0.25 of the input rate (= Nyquist of the 48 kHz output), so
# < 0.25 is passband and > 0.25 is stopband; both are swept, plus the band
# edges and the input-rate Nyquist (0.5) itself.
FREQS = [0.002, 0.005, 0.01, 0.02, 0.035, 0.05, 0.075, 0.1, 0.125, 0.15,
         0.175, 0.2, 0.22, 0.235, 0.245, 0.2495, 0.25, 0.2505, 0.255, 0.265,
         0.28, 0.3, 0.32, 0.33, 0.35, 0.375, 0.395, 0.405, 0.415, 0.43, 0.45,
         0.47, 0.49, 0.4975, 0.5]


def declared_cases(n_drive):
    """The declared input sweep. Every case is (id, family, params, samples)."""
    cases = []

    def add(cid, family, params, xs):
        cases.append({"case": cid, "family": family, "params": params,
                      "samples": xs})

    for amp in AMPS:
        for sign in (1.0, -1.0):
            add("impulse a=%+.9g" % (sign * amp), "impulse",
                {"amp": sign * amp}, stim_impulse(sign * amp, n_drive))
    for amp in AMPS:
        for sign in (1.0, -1.0):
            add("dc a=%+.9g" % (sign * amp), "dc",
                {"amp": sign * amp}, stim_dc(sign * amp, n_drive))
    for f in FREQS:
        for amp in (0.01, 0.1, 0.5, 1.0, 8.0):
            add("sine f=%.4f a=%g" % (f, amp), "sine",
                {"f_of_input_rate": f, "amp": amp},
                stim_sine(amp, f, n_drive))
    for f in FREQS[::3]:
        for amp in (0.1, 0.5, 8.0):
            add("square f=%.4f a=%g" % (f, amp), "square",
                {"f_of_input_rate": f, "amp": amp},
                stim_square(amp, f, n_drive))
    for f1, f2 in ((0.01, 0.31), (0.05, 0.45), (0.1, 0.4), (0.2, 0.3),
                   (0.2495, 0.2505), (0.125, 0.375)):
        for amp in (0.25, 4.0):
            add("two-tone f=%.4f,%.4f a=%g" % (f1, f2, amp), "two_tone",
                {"f1_of_input_rate": f1, "f2_of_input_rate": f2, "amp": amp},
                stim_two_tone(amp, f1, f2, n_drive))
    for amp in (1e-3, 0.01, 0.1, 0.5, 1.0, 8.0):
        for seed in range(8):
            add("noise a=%g seed=%d" % (amp, seed), "noise",
                {"amp": amp, "seed": seed}, stim_noise(amp, seed, n_drive))
    return cases


# ------------------------------------------------------- limit-cycle probe ---

class ZeroedAtBlockBoundary(vm.HalfbandD2):
    """FAILURE CONTROL: the frozen recursion with its state zeroed at every
    block boundary. A measurement that still reports a non-zero settled
    amplitude under this control is not observing the filter's own state."""

    def process(self, inp):
        self.__init__()
        return vm.HalfbandD2.process(self, inp)


def _state(hb):
    return (tuple(map(tuple, hb.bx)) + tuple(map(tuple, hb.by))
            + tuple(map(tuple, hb.ax)) + tuple(map(tuple, hb.ay)))


def _minimal_period(seq):
    """Smallest p dividing len(seq) with seq[i] == seq[i % p] for all i."""
    n = len(seq)
    for p in range(1, n + 1):
        if n % p:
            continue
        if all(seq[i] == seq[i % p] for i in range(n)):
            return p
    return n


def measure_case(xs, cls=vm.HalfbandD2, max_silence_blocks=MAX_SILENCE_BLOCKS):
    """Drive `xs`, then cut to silence and find the zero-input cycle EXACTLY.

    Returns a dict; `settled_peak_q21 is None` means no state recurrence was
    reached inside the cap (NO_VERDICT), which is never reported as zero.
    """
    hb = cls()
    drive_out = []
    for i in range(0, len(xs), BLOCK_OS):
        blk = list(xs[i:i + BLOCK_OS])
        blk += [0] * (BLOCK_OS - len(blk))
        drive_out += hb.process(blk)

    seen = {}                      # state -> index of the block that follows it
    outs = []                      # per-block output lists, during silence
    for b in range(max_silence_blocks):
        st = _state(hb)
        if st in seen:
            first = seen[st]
            cyc_blocks = outs[first:]
            flat = [s for blk in cyc_blocks for s in blk]
            p = _minimal_period(flat)
            cyc = flat[:p]
            peak = max((abs(s) for s in cyc), default=0)
            return {
                "status": "MEASURED",
                "drive_peak_q21": max((abs(s) for s in drive_out), default=0),
                "lead_in_blocks": first,
                "lead_in_input_samples": first * BLOCK_OS,
                "cycle_blocks": len(cyc_blocks),
                "cycle_period_out_samples": p,
                "cycle_period_input_samples": 2 * p,
                "cycle_out_samples": cyc if p <= 16 else cyc[:16],
                "cycle_out_truncated": p > 16,
                "cycle_sum_q21": sum(cyc),
                "nyquist_alternating": bool(p == 2 and cyc[1] == -cyc[0]
                                            and cyc[0] != 0),
                "settled_peak_q21": peak,
                "settled_peak_int16_lsb": peak / float(INT16_LSB_Q21),
                # JSON `null`, never -Infinity: the repository forbids
                # non-standard JSON tokens in committed report artifacts
                # (tests/test_stereo_tail_gate.py). A dBFS-of-exact-silence is
                # an unrepresentable value, not a missing measurement --
                # `settled_peak_q21 == 0` says which of the two this is.
                "settled_peak_dbfs": (None if peak == 0 else
                                      20.0 * math.log10(peak / float(vm.ONE))),
                "settled_peak_dbfs_is_null_because":
                    "the cycle is exactly zero (silence has no dBFS); "
                    "settled_peak_q21 == 0 distinguishes this from NO_VERDICT"
                    if peak == 0 else None,
            }
        seen[st] = len(outs)
        outs.append(hb.process([0] * BLOCK_OS))
    return {"status": "NO_VERDICT",
            "drive_peak_q21": max((abs(s) for s in drive_out), default=0),
            "lead_in_blocks": None, "lead_in_input_samples": None,
            "cycle_blocks": None, "cycle_period_out_samples": None,
            "cycle_period_input_samples": None, "cycle_out_samples": None,
            "cycle_out_truncated": None, "cycle_sum_q21": None,
            "nyquist_alternating": None,
            "settled_peak_q21": None, "settled_peak_int16_lsb": None,
            "settled_peak_dbfs": None,
            "settled_peak_dbfs_is_null_because": "NO_VERDICT",
            "note": "no state recurrence within --max-silence-blocks; NOT zero"}


def run_sweep(cases, cls=vm.HalfbandD2, max_silence_blocks=MAX_SILENCE_BLOCKS):
    rows = []
    for c in cases:
        m = measure_case(c["samples"], cls=cls,
                         max_silence_blocks=max_silence_blocks)
        row = {"case": c["case"], "family": c["family"], "params": c["params"]}
        row.update(m)
        rows.append(row)
    return rows


def summarize(rows):
    measured = [r for r in rows if r["status"] == "MEASURED"]
    unresolved = [r["case"] for r in rows if r["status"] != "MEASURED"]
    peaks = [r["settled_peak_q21"] for r in measured]
    worst = max(peaks) if peaks else None
    worst_cases = sorted(r["case"] for r in measured
                         if r["settled_peak_q21"] == worst)
    nz = [r for r in measured if r["settled_peak_q21"] > 0]
    return {
        "cases": len(rows),
        "cases_measured": len(measured),
        "cases_unresolved": unresolved,
        "cases_with_nonzero_limit_cycle": len(nz),
        "cases_settling_to_exact_zero": len(measured) - len(nz),
        "worst_settled_peak_q21": worst,
        "worst_settled_peak_int16_lsb": (None if worst is None
                                        else worst / float(INT16_LSB_Q21)),
        # `null` (never -Infinity) both when nothing resolved and when every
        # case settled to exact zero; the two are told apart by
        # `cases_unresolved` / `worst_settled_peak_q21`.
        "worst_settled_peak_dbfs": (
            None if not worst else
            round(20.0 * math.log10(worst / float(vm.ONE)), 2)),
        "worst_cases": worst_cases[:8],
        "worst_case_count": len(worst_cases),
        "int16_lsb_in_q21": INT16_LSB_Q21,
        "worst_below_one_int16_lsb": (None if worst is None
                                      else worst < INT16_LSB_Q21),
        "all_nonzero_cycles_nyquist_alternating":
            all(r["nyquist_alternating"] for r in nz) if nz else None,
        "distinct_settled_peaks_q21": sorted({r["settled_peak_q21"]
                                              for r in measured}),
        "max_lead_in_input_samples": max((r["lead_in_input_samples"]
                                         for r in measured), default=None),
    }


class FloatD2:
    """The SAME recursion and the SAME quoted coefficients, in float64.

    Not the pinned kernel (that is float32 SIMD and needs the external oracle
    host); this is the frozen model's own arithmetic with the Q10.21
    quantization removed, which is exactly the axis under test.
    """

    def __init__(self):
        self.bx = [[0.0, 0.0, 0.0] for _ in range(6)]
        self.by = [[0.0, 0.0, 0.0] for _ in range(6)]
        self.ax = [[0.0, 0.0, 0.0] for _ in range(6)]
        self.ay = [[0.0, 0.0, 0.0] for _ in range(6)]

    def process(self, inp):
        cb, ca = [], []
        for x_in in inp:
            xb = xa = float(x_in)
            for j in range(6):
                y = self.bx[j][1] + vm.HALFBAND_B[j] * (xb - self.by[j][1])
                self.bx[j] = [xb, self.bx[j][0], self.bx[j][1]]
                self.by[j] = [y, self.by[j][0], self.by[j][1]]
                xb = y
                y = self.ax[j][1] + vm.HALFBAND_A[j] * (xa - self.ay[j][1])
                self.ax[j] = [xa, self.ax[j][0], self.ax[j][1]]
                self.ay[j] = [y, self.ay[j][0], self.ay[j][1]]
                xa = y
            cb.append(xb)
            ca.append(xa)
        return [(cb[2 * n] + ca[2 * n + 1]) * 0.5 for n in range(len(inp) // 2)]


def float_contrast(cases, sweep_rows, silence_blocks=2048):
    """Drive the float64 recursion with the same cases and the same silence.

    Reports the peak of the LAST silence block (in Q10.21 LSB, so it is
    directly comparable to the fixed-point sweep) and whether it quantizes to
    zero. A decaying float tail is not itself a claim about the pinned kernel;
    it says the dead band comes from the quantizer, not the recursion.
    """
    worst_last = 0.0
    worst_case = None
    rounds_to_zero = 0
    n = 0
    for c, r in zip(cases, sweep_rows):
        if r["status"] != "MEASURED" or not r["settled_peak_q21"]:
            continue          # only cases the fixed-point sweep found a cycle on
        n += 1
        hb = FloatD2()
        xs = list(c["samples"])
        for i in range(0, len(xs), BLOCK_OS):
            blk = xs[i:i + BLOCK_OS]
            hb.process(blk + [0] * (BLOCK_OS - len(blk)))
        last = []
        for _ in range(silence_blocks):
            last = hb.process([0] * BLOCK_OS)
        peak = max((abs(v) for v in last), default=0.0)
        if round(peak) == 0:
            rounds_to_zero += 1
        if peak > worst_last:
            worst_last, worst_case = peak, r["case"]
    return {
        "leg": "float64 EMULATION of the same recursion with the same quoted "
               "coefficients (vm.HALFBAND_A/HALFBAND_B), Q10.21 quantization "
               "removed",
        "is_not": "NOT the pinned kernel. Executing the pinned "
                  "HalfRateFilter(M=6, steep) needs the external oracle host "
                  "(oracle/sxt022/build_halfband_probe.sh); no pinned-kernel "
                  "zero-input measurement is made or assumed here.",
        "pinned_kernel_zero_input_measurement": "NOT_RUN",
        "cases": n,
        "silence_blocks": silence_blocks,
        "silence_input_samples": silence_blocks * BLOCK_OS,
        "worst_last_block_peak_q21_units": worst_last,
        "worst_last_block_peak_case": worst_case,
        "cases_whose_float_tail_rounds_to_zero_q21": rounds_to_zero,
        "all_float_tails_round_to_zero_q21": n > 0 and rounds_to_zero == n,
    }


def failure_control(sweep_rows, control_rows):
    """The control must drive every settled amplitude to 0, and the
    uncontrolled sweep must have found something to drive to 0."""
    bad = [r["case"] for r in control_rows
           if r["status"] != "MEASURED" or r["settled_peak_q21"] != 0]
    live = sum(1 for r in sweep_rows
               if r["status"] == "MEASURED" and r["settled_peak_q21"] > 0)
    ok = (not bad) and live > 0
    return {
        "control": "decimator state zeroed at every block boundary "
                   "(ZeroedAtBlockBoundary)",
        "requirement": "every case must settle to exactly 0 under the control, "
                       "and the uncontrolled sweep must contain at least one "
                       "non-zero settled amplitude for the control to be "
                       "observing anything",
        "control_cases": len(control_rows),
        "control_cases_nonzero": len(bad),
        "control_offenders": bad[:8],
        "uncontrolled_nonzero_cases": live,
        "verdict": "PASS" if ok else "FAIL",
    }


# ------------------------------------------------------------- RTL splice ---
#
# The second acceptance box of #181 requires the RTL copies to be CHECKED, not
# assumed, to reproduce the same settled amplitude. Re-typing the cascade into
# a hand-written probe would check the re-typing, so instead the cascade text
# is lifted VERBATIM out of each RTL copy's own `decimate_and_output` task and
# spliced into a generated probe together with that file's own `qmul`,
# `qround1`/inline round and `clamp8`. The single substitution is the
# coefficient window each file reads out of its own `cfg` array.

RTL_COPIES = [
    "rtl/voice/tb_voice.sv",
    "rtl/oscillators/classic/tb_classic.sv",
    "rtl/oscillators/sine/tb_sine.sv",
]


def _balanced_block(text, start):
    """Return text[start:end] covering one begin…end balanced region."""
    depth = 0
    i = start
    tok = re.compile(r"\b(begin|end)\b")
    while True:
        m = tok.search(text, i)
        if not m:
            raise SystemExit("unbalanced begin/end while extracting RTL")
        depth += 1 if m.group(1) == "begin" else -1
        i = m.end()
        if depth == 0:
            return text[start:text.index("\n", i) + 1]


def extract_decimator(rel):
    """Extract one RTL copy's decimator text verbatim.

    Returns a dict with the verbatim cascade loop (the outer
    `for (k = 0; k < BLOCK_OS; k++) begin … end` that feeds `scene_l` through
    both 6-stage allpass chains into `chainb`/`chaina`), the verbatim
    reconstruction assignment (`bl = …;`), and a normalized cascade in which
    the file's own `cfg` coefficient window is replaced by `HB_B[i]`/`HB_A[i]`
    so the three copies can be compared as text.
    """
    path = os.path.join(REPO, rel)
    text = open(path, encoding="utf-8").read()
    if "task automatic decimate_and_output" not in text:
        raise SystemExit("%s: no decimate_and_output task" % rel)
    task = text.split("task automatic decimate_and_output", 1)[1]
    task = task[:task.index("endtask")]

    m = re.search(r"^[ \t]*for \(k = 0; k < BLOCK_OS; k\+\+\) begin$", task,
                  re.M)
    if not m:
        raise SystemExit("%s: no BLOCK_OS cascade loop" % rel)
    cascade = _balanced_block(task, m.start())
    if "i < 6" not in cascade:
        raise SystemExit("%s: cascade loop has no 6-stage chain" % rel)

    bases = sorted({int(x) for x in re.findall(r"cfg\[(\d+)\+i\]", cascade)})
    if len(bases) != 2 or bases[1] - bases[0] != 6:
        raise SystemExit("%s: unexpected coefficient window %r" % (rel, bases))
    norm = cascade.replace("32'(cfg[%d+i])" % bases[0], "HB_B[i]", 1)
    norm = norm.replace("32'(cfg[%d+i])" % bases[1], "HB_A[i]", 1)
    if "cfg[" in norm:
        raise SystemExit("%s: cfg reference left in normalized cascade" % rel)

    r = re.search(r"^[ \t]*bl = .*;$", task, re.M)
    if not r:
        raise SystemExit("%s: no reconstruction assignment" % rel)
    recon = r.group(0)

    funcs = {}
    for name in ("qmul", "clamp8", "qround1"):
        f = re.search(r"^[ \t]*function automatic [^\n]*\b%s\b\(.*?^[ \t]*"
                      r"endfunction\n" % re.escape(name), text, re.M | re.S)
        if f:
            funcs[name] = f.group(0)
    if "qmul" not in funcs or "clamp8" not in funcs:
        raise SystemExit("%s: qmul/clamp8 not found" % rel)
    return {"file": rel, "cascade_verbatim": cascade,
            "cascade_normalized": norm, "cfg_bases": bases,
            "reconstruction_verbatim": recon, "functions": funcs}


PROBE_TEMPLATE = """// GENERATED by tools/measure_halfband_limit_cycle.py (issue #181) --
// DO NOT EDIT and DO NOT COMMIT. The cascade loop, the reconstruction
// assignment and the qmul/clamp8/qround1 functions below are spliced VERBATIM
// out of %(src)s, so this probe exercises that file's own arithmetic text
// rather than a re-typing of it. The only substitution is the coefficient
// window (`32'(cfg[%(b0)d+i])` -> `HB_B[i]`, `32'(cfg[%(b1)d+i])` -> `HB_A[i]`),
// and leading whitespace on the spliced lines.
module tb_halfband_limit_cycle;
  localparam int BLOCK_OS = 64;
  localparam int BLOCK    = 32;
  localparam logic signed [31:0] ONE = 32'sd2097152;

  integer qmul_count = 0;

%(functions)s

  logic signed [31:0] HB_B [6];
  logic signed [31:0] HB_A [6];
  logic signed [31:0] hbx1_b [6], hbx2_b [6], hby1_b [6], hby2_b [6];
  logic signed [31:0] hbx1_a [6], hbx2_a [6], hby1_a [6], hby2_a [6];
  logic signed [31:0] scene_l [BLOCK_OS];
  logic signed [31:0] chainb [BLOCK_OS];
  logic signed [31:0] chaina [BLOCK_OS];
  logic signed [31:0] xb, xa, yb, ya, bl;
  integer i, k, blk, fin, fout, rc, nblocks, v;

  initial begin
    HB_B[0] = 32'sd%(b_0)d; HB_B[1] = 32'sd%(b_1)d; HB_B[2] = 32'sd%(b_2)d;
    HB_B[3] = 32'sd%(b_3)d; HB_B[4] = 32'sd%(b_4)d; HB_B[5] = 32'sd%(b_5)d;
    HB_A[0] = 32'sd%(a_0)d; HB_A[1] = 32'sd%(a_1)d; HB_A[2] = 32'sd%(a_2)d;
    HB_A[3] = 32'sd%(a_3)d; HB_A[4] = 32'sd%(a_4)d; HB_A[5] = 32'sd%(a_5)d;
    for (i = 0; i < 6; i++) begin
      hbx1_b[i] = 0; hbx2_b[i] = 0; hby1_b[i] = 0; hby2_b[i] = 0;
      hbx1_a[i] = 0; hbx2_a[i] = 0; hby1_a[i] = 0; hby2_a[i] = 0;
    end
    fin  = $fopen("hb_stim.txt", "r");
    fout = $fopen("%(out)s", "w");
    if (fin == 0 || fout == 0) begin $display("FATAL fopen"); $finish; end
    rc = $fscanf(fin, "%%d", nblocks);
    for (blk = 0; blk < nblocks; blk++) begin
      // harness (NOT spliced RTL): each declared case starts from the reset
      // state, exactly as the model's per-case HalfbandD2() does.
      rc = $fscanf(fin, "%%d", v);
      if (v != 0) begin
        for (i = 0; i < 6; i++) begin
          hbx1_b[i] = 0; hbx2_b[i] = 0; hby1_b[i] = 0; hby2_b[i] = 0;
          hbx1_a[i] = 0; hbx2_a[i] = 0; hby1_a[i] = 0; hby2_a[i] = 0;
        end
      end
      for (k = 0; k < BLOCK_OS; k++) begin
        rc = $fscanf(fin, "%%d", v);
        scene_l[k] = v;
      end
%(cascade)s
      for (k = 0; k < BLOCK; k++) begin
%(recon)s
        $fwrite(fout, "%%0d\\n", bl);
      end
    end
    $fclose(fin); $fclose(fout);
    $display("DONE blocks=%%0d qmuls=%%0d", nblocks, qmul_count);
    $finish;
  end
endmodule
"""


def _reindent(text, pad):
    """Re-indent a spliced block; only leading whitespace changes."""
    lines = text.rstrip("\n").split("\n")
    strip = min((len(x) - len(x.lstrip()) for x in lines if x.strip()),
                default=0)
    return "\n".join((pad + x[strip:]) if x.strip() else x
                     for x in lines) + "\n"


def build_probe(copy, workdir, tag):
    coeff = {}
    for i in range(6):
        coeff["b_%d" % i] = vm.HALFBAND_B_Q[i]
        coeff["a_%d" % i] = vm.HALFBAND_A_Q[i]
    order = [n for n in ("qmul", "clamp8", "qround1") if n in copy["functions"]]
    sv = PROBE_TEMPLATE % dict(
        coeff,
        src=copy["file"],
        b0=copy["cfg_bases"][0], b1=copy["cfg_bases"][1],
        functions="\n".join(copy["functions"][n] for n in order),
        cascade=_reindent(copy["cascade_normalized"], "      "),
        recon=_reindent(copy["reconstruction_verbatim"], "        "),
        out="hb_out_%s.txt" % tag)
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, "tb_hb_lc_%s.sv" % tag)
    with open(path, "w", encoding="utf-8") as f:
        f.write(sv)
    return path


def _model_stream_and_plan(cases, sweep_rows, tail_blocks):
    """-> (plan, model output stream, [(reset_flag, [64 samples]), …])."""
    plan, stream, stim = [], [], []
    for c, r in zip(cases, sweep_rows):
        if r["status"] != "MEASURED":
            continue
        xs = list(c["samples"])
        if len(xs) % BLOCK_OS:
            xs += [0] * (BLOCK_OS - len(xs) % BLOCK_OS)
        drive_blocks = len(xs) // BLOCK_OS
        silence = r["lead_in_blocks"] + r["cycle_blocks"] + tail_blocks
        xs += [0] * (silence * BLOCK_OS)
        nblk = drive_blocks + silence
        hb = vm.HalfbandD2()
        out = []
        for i in range(nblk):
            out += hb.process(xs[i * BLOCK_OS:(i + 1) * BLOCK_OS])
        plan.append({
            "case": r["case"],
            "blocks": nblk,
            "first_out": len(stream),
            # the cycle's first block, measured by the model, in output samples
            "settled_from_out": len(stream)
                                + (drive_blocks + r["lead_in_blocks"]) * BLOCK,
        })
        stream += out
        for i in range(nblk):
            stim.append((1 if i == 0 else 0,
                         xs[i * BLOCK_OS:(i + 1) * BLOCK_OS]))
    return plan, stream, stim


def rtl_leg(cases, sweep_rows, workdir, tail_blocks=8):
    """Run every declared case through each RTL copy's own spliced text.

    Each case is followed by exactly the silence the model needed to reach its
    cycle plus `tail_blocks` more blocks, so the compared window provably
    contains the settled region rather than only the decay.
    """
    os.makedirs(workdir, exist_ok=True)
    copies = [extract_decimator(rel) for rel in RTL_COPIES]
    norms = {c["cascade_normalized"] for c in copies}

    plan, model_stream, stim = _model_stream_and_plan(cases, sweep_rows,
                                                      tail_blocks)
    with open(os.path.join(workdir, "hb_stim.txt"), "w") as f:
        f.write("%d\n" % sum(p["blocks"] for p in plan))
        for reset, blk in stim:
            f.write("%d\n" % reset)
            f.write("\n".join(str(v) for v in blk))
            f.write("\n")

    per_copy = []
    for copy in copies:
        tag = re.sub(r"\W+", "_", copy["file"])
        probe = build_probe(copy, workdir, tag)
        compile_and_run(probe, workdir, out_name="tb_hb_lc_%s.vvp" % tag,
                        absolute=True, compile_in_workdir=True,
                        run_by_name=True,
                        trace_name="hb_out_%s.txt" % tag)
        with open(os.path.join(workdir, "hb_out_%s.txt" % tag),
                  encoding="utf-8") as f:
            rtl = [int(x) for x in f.read().split()]
        if len(rtl) != len(model_stream):
            per_copy.append({"file": copy["file"], "verdict": "FAIL",
                             "reason": "probe emitted %d samples, model %d"
                                       % (len(rtl), len(model_stream))})
            continue
        mism = [i for i, (a, b) in enumerate(zip(model_stream, rtl)) if a != b]
        # tb_classic.sv / tb_sine.sv wrap the reconstruction in their own
        # +/-8 clip, which the SHARED model class does not contain (the voice
        # leaf applies the equivalent clip to scene_l upstream of the
        # decimator instead). A mismatch is "explained by that leaf clip" only
        # when the model's unclamped word is outside +/-8 and the RTL word is
        # exactly the clip -- anything else is an arithmetic disagreement.
        clip_explained = [i for i in mism
                          if abs(model_stream[i]) > CLIP8
                          and rtl[i] == (CLIP8 if model_stream[i] > 0
                                         else -CLIP8)]
        unexplained = [i for i in mism if i not in set(clip_explained)]
        peak_disagree, settled, settled_mism = [], 0, 0
        for p in plan:
            hi = p["first_out"] + p["blocks"] * BLOCK
            s = p["settled_from_out"]
            settled += hi - s
            settled_mism += sum(1 for i in range(s, hi)
                                if model_stream[i] != rtl[i])
            if max((abs(x) for x in model_stream[s:hi]), default=0) != \
                    max((abs(x) for x in rtl[s:hi]), default=0):
                peak_disagree.append(p["case"])
        ok = not unexplained and not settled_mism and not peak_disagree
        per_copy.append({
            "file": copy["file"],
            "cfg_bases": copy["cfg_bases"],
            "reconstruction_verbatim": copy["reconstruction_verbatim"].strip(),
            "verdict": "PASS" if ok else "FAIL",
            "out_samples_compared": len(model_stream),
            "settled_region_samples_compared": settled,
            "settled_region_mismatching_samples": settled_mism,
            "mismatching_samples": len(mism),
            "mismatches_explained_by_leaf_pm8_clip": len(clip_explained),
            "unexplained_mismatching_samples": len(unexplained),
            "first_unexplained_mismatch_index":
                unexplained[0] if unexplained else None,
            "settled_peak_disagreements": peak_disagree,
        })

    return {
        "claim": "claim (1) ONLY -- the RTL matches the frozen fixed-point "
                 "model exactly. Nothing here is a model-vs-reference or a "
                 "listening claim.",
        "method": "each RTL copy's own decimate_and_output cascade loop, "
                  "reconstruction assignment and qmul/clamp8/qround1 "
                  "functions are spliced VERBATIM into a generated probe "
                  "(only the cfg coefficient window and leading whitespace "
                  "are substituted), run under iverilog on every declared "
                  "case, and compared to the model sample-for-sample over the "
                  "whole run INCLUDING the settled region",
        "pass_requires": "for every copy: zero mismatches inside the settled "
                         "region, zero settled-peak disagreements, and zero "
                         "mismatches anywhere that are not explained by that "
                         "leaf's own +/-8 reconstruction clip (a leaf stage, "
                         "not part of the shared decimator); plus the cascade "
                         "text being identical across the three copies",
        "cases": len(plan),
        "cascade_text_identical_across_copies": len(norms) == 1,
        "verdict": ("PASS" if all(c["verdict"] == "PASS" for c in per_copy)
                    and len(norms) == 1 else "FAIL"),
        "copies": per_copy,
    }


# ------------------------------------------------------- in-situ leaf legs ---

LEAF_LEGS = [
    {"leaf": "voice:attacky-slice / voice:sine-fm-lp24-v2 / "
             "voice:unison-stack (SXT-022/026a/034)",
     "runner": ["model/voice/run_model.py",
                "--sequence", "seq-notes-repeated-v1"],
     "rtl": "rtl/voice/tb_voice.sv",
     "comparator": ["tools/compare_rtl_model.py"]},
    {"leaf": "osc:Classic (SXT-033)",
     "runner": ["model/oscillators/classic/run_model.py",
                "--inputs", "model/oscillators/classic/inputs/horn.json",
                "--sequence", "seq-notes-repeated-v1", "--rtl"],
     "rtl": "rtl/oscillators/classic/tb_classic.sv",
     "comparator": ["tools/compare_classic_rtl_model.py"]},
    {"leaf": "osc:Sine (SXT-040)",
     "runner": ["model/oscillators/sine/run_model.py",
                "--inputs", "model/oscillators/sine/inputs/tentacles.json",
                "--sequence", "seq-notes-repeated-v1", "--rtl"],
     "rtl": "rtl/oscillators/sine/tb_sine.sv",
     "comparator": ["tools/compare_sine_rtl_model.py"]},
]


def leaf_legs(workroot, run_rtl=False):
    rows = []
    for spec in LEAF_LEGS:
        out = os.path.join(workroot, re.sub(r"\W+", "-", spec["leaf"])[:40])
        cmd = [sys.executable] + spec["runner"] + ["--out-dir", out]
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            rows.append({"leaf": spec["leaf"], "status": "NOT_RUN",
                         "stderr": r.stderr[-400:]})
            continue
        with open(os.path.join(out, "model_trace.json"), encoding="utf-8") as f:
            trace = json.load(f)
        blocks = trace["blocks"]
        live = [b["b"] for b in blocks if b["voices"]]
        last = max(live) if live else None
        post = [b for b in blocks if last is not None and b["b"] > last]
        peaks = [max((abs(x) for x in b["mono_block"]), default=0)
                 for b in post]
        nz = sum(1 for p in peaks if p > 0)
        tail = post[-1]["mono_block"][:8] if post else None
        row = {
            "leaf": spec["leaf"],
            "status": "MEASURED",
            "runner": " ".join(spec["runner"]),
            "rtl": spec["rtl"],
            "blocks": len(blocks),
            "last_block_with_a_live_voice": last,
            "blocks_after_last_voice_death": len(post),
            "output_samples_after_last_voice_death": len(post) * BLOCK,
            "post_death_blocks_with_nonzero_output": nz,
            "post_death_mono_peak_q21": max(peaks) if peaks else None,
            "post_death_final_block_head": tail,
            "ring_out_region_exists_in_this_render": len(post) > 0,
            "live_limit_cycle_at_this_leafs_output": nz == len(post) and nz > 0,
            # answered by the committed comparator below, never assumed
            "ring_out_inside_committed_comparator_window": None,
            "committed_comparator": " ".join(spec["comparator"]),
            "committed_comparator_summary": {"verdict": "NOT_RUN",
                                             "why": "--leaf-rtl not requested"},
        }
        if run_rtl:
            # `--out` rather than stdout: these comparators pass
            # suppress_stdout=False, so the simulation's own $display output
            # lands on stdout and a stdout parse would silently read NOT_RUN.
            sfile = os.path.join(out, "committed-comparator-summary.json")
            cmp_cmd = [sys.executable] + spec["comparator"] + \
                ["--run-dir", out, "--out", sfile]
            c = subprocess.run(cmp_cmd, cwd=REPO, capture_output=True,
                               text=True)
            try:
                with open(sfile, encoding="utf-8") as f:
                    summary = json.load(f)
            except (OSError, ValueError):
                summary = {"verdict": "NOT_RUN", "returncode": c.returncode,
                           "stderr": c.stderr[-400:]}
            row["committed_comparator_summary"] = summary
            # Does that comparator's compared window actually reach the
            # ring-out region? It does iff it compared one 48 kHz mono sample
            # for every block of the render, including the post-death blocks.
            mono = (summary.get("checked") or {}).get("mono")
            if summary.get("verdict") in ("PASS", "FAIL") and mono is not None:
                row["committed_comparator_mono_samples_compared"] = mono
                row["render_mono_samples"] = len(blocks) * BLOCK
                row["ring_out_inside_committed_comparator_window"] = \
                    bool(mono >= len(blocks) * BLOCK and post)
            else:
                row["ring_out_inside_committed_comparator_window"] = None
        rows.append(row)
    return rows


# ------------------------------------------------------------------- main ---

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write the measurement artifact here")
    ap.add_argument("--drive-blocks", type=int, default=DRIVE_BLOCKS)
    ap.add_argument("--max-silence-blocks", type=int,
                    default=MAX_SILENCE_BLOCKS)
    ap.add_argument("--contrast-blocks", type=int, default=2048,
                    help="silence blocks for the float64 contrast leg")
    ap.add_argument("--rtl", action="store_true",
                    help="include the spliced-RTL leg (needs iverilog)")
    ap.add_argument("--leaves", action="store_true",
                    help="include the in-situ affected-leaf legs")
    ap.add_argument("--leaf-rtl", action="store_true",
                    help="also run each leaf's committed comparator (slow)")
    ap.add_argument("--workdir", default="/tmp/halfband-limit-cycle")
    args = ap.parse_args()

    cases = declared_cases(args.drive_blocks * BLOCK_OS)
    sweep = run_sweep(cases, max_silence_blocks=args.max_silence_blocks)
    control = run_sweep(cases, cls=ZeroedAtBlockBoundary,
                        max_silence_blocks=args.max_silence_blocks)

    art = {
        "format": FORMAT,
        "issue": ISSUE,
        "finding": "F-176-2",
        "claim_scope": "FROZEN-MODEL PROPERTY ONLY. A measured property of "
                       "model/voice/voice_model.py::HalfbandD2 plus a claim-(1) "
                       "RTL-matches-model check. No reference render is read, "
                       "no pinned engine is executed, no budget is graded, and "
                       "nothing here is a fidelity, preset-support or "
                       "musical-quality claim.",
        "declared_input_range": {
            "bound_q21": CLIP8,
            "bound": 8.0,
            "why": "every consumer clips the decimator's input to +/-8.0 (the "
                   "engine's sceneout hard clip) immediately upstream: "
                   "model/voice/run_model.py limit_i(+/-qint(8.0)) and "
                   "rtl/voice/tb_voice.sv clamp8",
        },
        "method": {
            "settled_amplitude": "EXACT, by zero-input state recurrence: the "
                                 "full 72-word decimator state is hashed after "
                                 "every 64-sample block of silence; on a "
                                 "recurrence the block sequence between the "
                                 "two occurrences repeats forever by "
                                 "construction, and the reported period is the "
                                 "minimal output period of that cycle",
            "not": "no settled amplitude is extrapolated from the tail of a "
                   "finite render; a case with no recurrence inside the cap is "
                   "reported NO_VERDICT, never 0",
            "drive_input_samples": args.drive_blocks * BLOCK_OS,
            "max_silence_blocks": args.max_silence_blocks,
            "block_input_samples": BLOCK_OS,
            "block_output_samples": BLOCK,
        },
        "frozen_coefficients": {
            "HALFBAND_A_Q": list(vm.HALFBAND_A_Q),
            "HALFBAND_B_Q": list(vm.HALFBAND_B_Q),
            "decision_record": "decision-records/0002-halfband-coefficients.md",
        },
        "not_measured_here": [
            "model/effects/type-distortion/distortion_model.py::HalfbandD2 is "
            "a DIFFERENT class (HalfRateFilter(M=3), Q24.43 allpass state, "
            "oversampling rather than scene decimation); its dead-band is not "
            "measured by this tool and no bound here applies to it",
        ],
        "sweep": {"summary": summarize(sweep), "cases": sweep},
        "failure_control": failure_control(sweep, control),
        "float_contrast": float_contrast(cases, sweep,
                                        silence_blocks=args.contrast_blocks),
    }

    if args.rtl:
        art["rtl_leg"] = rtl_leg(cases, sweep,
                                 os.path.join(args.workdir, "rtl"))
    if args.leaves:
        art["leaf_legs"] = leaf_legs(os.path.join(args.workdir, "leaves"),
                                     run_rtl=args.leaf_rtl)

    s = art["sweep"]["summary"]
    print(json.dumps({
        "cases": s["cases"],
        "unresolved": s["cases_unresolved"],
        "nonzero_limit_cycles": s["cases_with_nonzero_limit_cycle"],
        "worst_settled_peak_q21": s["worst_settled_peak_q21"],
        "worst_settled_peak_int16_lsb": s["worst_settled_peak_int16_lsb"],
        "worst_settled_peak_dbfs": s["worst_settled_peak_dbfs"],
        "worst_below_one_int16_lsb": s["worst_below_one_int16_lsb"],
        "worst_cases": s["worst_cases"],
        "failure_control": art["failure_control"]["verdict"],
        "float_contrast_all_tails_round_to_zero":
            art["float_contrast"]["all_float_tails_round_to_zero_q21"],
        "rtl_leg": art.get("rtl_leg", {}).get("verdict", "NOT_RUN"),
    }, indent=2))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(art, f, indent=1, sort_keys=False)
            f.write("\n")

    rc = 0
    if s["cases_unresolved"]:
        print("FAIL: unresolved cases (no state recurrence)", file=sys.stderr)
        rc = 1
    if art["failure_control"]["verdict"] != "PASS":
        print("FAIL: failure control did not hold", file=sys.stderr)
        rc = 1
    if s["worst_settled_peak_q21"] is not None and \
            s["worst_settled_peak_q21"] >= INT16_LSB_Q21:
        print("ESCALATE: worst settled amplitude reaches one int16 LSB "
              "(#181 stop/escalate condition -> #12)", file=sys.stderr)
        rc = 2
    if args.rtl and art["rtl_leg"]["verdict"] != "PASS":
        print("FAIL: spliced-RTL leg is not exact", file=sys.stderr)
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
